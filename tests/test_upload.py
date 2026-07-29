"""이미지 업로드(1c) 검증 — 렌더된 PNG를 공개 URL로 만드는 마지막 조각.

Instagram은 '공개 접근 가능한 URL'을 요구하므로, 이 단계가 끝나야 발행이 열린다.
"""
import pytest

from branding.config.settings import Settings
from branding.db import PostRepository, init_db
from branding.models import CarouselSlide, Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform
from branding.upload import (
    DirectoryUploader, S3Uploader, UploadError, UploadService, get_uploader, slide_key,
)


# --- 저장 키 ---

def test_slide_key_is_deterministic_and_zero_padded():
    assert slide_key(7, 3) == "post_7/slide_03.png"
    assert slide_key(7, 3) == slide_key(7, 3)      # 재렌더 시 같은 키에 덮어씀


def test_slide_key_applies_prefix():
    assert slide_key(7, 1, prefix="slides") == "slides/post_7/slide_01.png"
    assert slide_key(7, 1, prefix="/slides/") == "slides/post_7/slide_01.png"


# --- 제공자 선택 ---

def test_missing_provider_explains_what_to_set(tmp_path):
    with pytest.raises(UploadError, match="UPLOAD_PROVIDER"):
        get_uploader(Settings(data_dir=tmp_path))


def test_unknown_provider_is_rejected(tmp_path):
    with pytest.raises(UploadError, match="알 수 없는"):
        get_uploader(Settings(data_dir=tmp_path, upload_provider="ftp"))


def test_provider_factory_builds_configured_uploader(tmp_path):
    dir_up = get_uploader(Settings(
        data_dir=tmp_path, upload_provider="dir",
        upload_dir=tmp_path / "public", upload_public_base_url="https://cdn.example.com",
    ))
    assert isinstance(dir_up, DirectoryUploader)

    s3_up = get_uploader(Settings(
        data_dir=tmp_path, upload_provider="s3", s3_bucket="b", s3_region="ap-northeast-2",
    ))
    assert isinstance(s3_up, S3Uploader)


# --- 디렉터리 업로더 ---

def test_directory_upload_copies_file_and_builds_url(tmp_path):
    src = tmp_path / "slide.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n")
    uploader = DirectoryUploader(tmp_path / "public", "https://cdn.example.com/")

    result = uploader.upload(src, "slides/post_1/slide_01.png")

    assert result.url == "https://cdn.example.com/slides/post_1/slide_01.png"
    copied = tmp_path / "public" / "slides/post_1/slide_01.png"
    assert copied.exists() and copied.read_bytes() == src.read_bytes()


def test_directory_upload_requires_base_url(tmp_path):
    with pytest.raises(UploadError, match="UPLOAD_PUBLIC_BASE_URL"):
        DirectoryUploader(tmp_path, "").check()


def test_directory_upload_reports_missing_source(tmp_path):
    uploader = DirectoryUploader(tmp_path / "public", "https://cdn.example.com")
    with pytest.raises(UploadError, match="업로드할 파일이 없습니다"):
        uploader.upload(tmp_path / "nope.png", "k.png")


# --- S3 호환 업로더 (스텁 클라이언트) ---

class StubS3:
    def __init__(self):
        self.calls: list[dict] = []

    def put_object(self, **kw):
        kw["Body"] = kw["Body"].read()
        self.calls.append(kw)
        return {}


def _png(tmp_path):
    p = tmp_path / "slide.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_s3_upload_sends_png_content_type(tmp_path):
    stub = StubS3()
    uploader = S3Uploader(bucket="my-bucket", region="ap-northeast-2", client=stub)

    uploader.upload(_png(tmp_path), "slides/post_1/slide_01.png")

    call = stub.calls[0]
    assert call["Bucket"] == "my-bucket"
    assert call["Key"] == "slides/post_1/slide_01.png"
    assert call["ContentType"] == "image/png"
    assert "ACL" not in call          # R2 등 ACL 미지원 대비 — 기본은 보내지 않음


def test_s3_sends_acl_only_when_configured(tmp_path):
    stub = StubS3()
    S3Uploader(bucket="b", region="r", acl="public-read", client=stub).upload(
        _png(tmp_path), "k.png"
    )
    assert stub.calls[0]["ACL"] == "public-read"


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        # 커스텀 도메인이 최우선 — R2·CDN은 엔드포인트가 공개 주소가 아니다
        (dict(bucket="b", public_base_url="https://cdn.example.com",
              endpoint_url="https://acc.r2.cloudflarestorage.com"),
         "https://cdn.example.com/k.png"),
        (dict(bucket="b", endpoint_url="https://acc.r2.cloudflarestorage.com"),
         "https://acc.r2.cloudflarestorage.com/b/k.png"),
        (dict(bucket="b", region="ap-northeast-2"),
         "https://b.s3.ap-northeast-2.amazonaws.com/k.png"),
    ],
)
def test_s3_public_url_by_provider_shape(kwargs, expected):
    assert S3Uploader(**kwargs).public_url("k.png") == expected


def test_s3_requires_bucket():
    with pytest.raises(UploadError, match="S3_BUCKET"):
        S3Uploader(bucket="").check()


def test_s3_requires_a_way_to_build_public_url():
    with pytest.raises(UploadError, match="공개 URL"):
        S3Uploader(bucket="b").check()


def test_s3_wraps_client_errors(tmp_path):
    class Failing:
        def put_object(self, **kw):
            raise RuntimeError("AccessDenied")

    with pytest.raises(UploadError, match="AccessDenied"):
        S3Uploader(bucket="b", region="r", client=Failing()).upload(_png(tmp_path), "k.png")


# --- 서비스 ---

def _settings(tmp_path) -> Settings:
    s = Settings(
        data_dir=tmp_path, upload_provider="dir",
        upload_dir=tmp_path / "public", upload_public_base_url="https://cdn.example.com",
        upload_prefix="slides",
    )
    init_db(s.db_path)
    return s


def _post_with_slides(settings, rendered: bool) -> Post:
    repo = PostRepository(settings.db_path)
    slides = []
    for i in (1, 2):
        path = None
        if rendered:
            png = settings.data_dir / f"r{i}.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n")
            path = str(png)
        slides.append(CarouselSlide(index=i, role="hook", headline=f"슬라이드 {i}", image_path=path))
    return repo.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="t",
        content=PostContent(caption_ko="c", cta="", slides=slides),
    ))


def test_upload_fills_image_url_and_unblocks_publishing(tmp_path):
    settings = _settings(tmp_path)
    post = _post_with_slides(settings, rendered=True)

    results = UploadService(settings, get_uploader(settings)).upload_post(post)

    assert [r.index for r in results] == [1, 2]
    assert results[0].url == f"https://cdn.example.com/slides/post_{post.id}/slide_01.png"

    reloaded = PostRepository(settings.db_path).get_by_id(post.id)
    # 발행 경로가 요구하는 상태 — 빠진 이미지가 없어야 한다
    assert reloaded.content.missing_slide_images() == []
    assert len(reloaded.content.publish_image_urls()) == 2


def test_unrendered_slides_are_reported_before_uploading(tmp_path):
    settings = _settings(tmp_path)
    post = _post_with_slides(settings, rendered=False)

    with pytest.raises(ValueError, match=r"렌더링되지 않은 슬라이드가 있습니다: \[1, 2\]"):
        UploadService(settings, get_uploader(settings)).upload_post(post)


def test_already_uploaded_slides_are_skipped(tmp_path):
    settings = _settings(tmp_path)
    post = _post_with_slides(settings, rendered=True)
    service = UploadService(settings, get_uploader(settings))
    service.upload_post(post)

    again = service.upload_by_id(post.id)

    assert all(r.skipped for r in again)     # 재업로드 비용을 쓰지 않음


def test_force_reuploads_everything(tmp_path):
    settings = _settings(tmp_path)
    post = _post_with_slides(settings, rendered=True)
    service = UploadService(settings, get_uploader(settings))
    service.upload_post(post)

    again = service.upload_by_id(post.id, force=True)

    assert not any(r.skipped for r in again)


def test_post_without_slides_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    post = PostRepository(settings.db_path).save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="t",
        content=PostContent(caption_ko="c", cta=""),
    ))
    with pytest.raises(ValueError, match="슬라이드가 없습니다"):
        UploadService(settings, get_uploader(settings)).upload_post(post)
