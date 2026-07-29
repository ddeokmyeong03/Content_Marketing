"""대시보드 캐러셀 검토(1d) 검증.

캡션과 해시태그만 보여주면 캐러셀을 승인할 수 없다 — 사람이 봐야 하는 것은
카드에 실제로 인쇄되는 문구와, 그 카드가 발행 가능한 상태인지다.
"""
import pytest
from fastapi.testclient import TestClient

from branding.config.settings import Settings
from branding.db import PostRepository, init_db
from branding.models import CarouselSlide, Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.web import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def env(tmp_path):
    settings = Settings(data_dir=tmp_path)
    init_db(settings.db_path)
    return TestClient(create_app(settings)), settings, PostRepository(settings.db_path)


def _make_post(repo: PostRepository, slides: list[CarouselSlide]) -> Post:
    return repo.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="자동화 실수",
        content=PostContent(caption_ko="본문", cta="저장", slides=slides),
        status=PostStatus.DRAFT,
    ))


def test_detail_exposes_slide_copy_for_review(env):
    client, _, repo = env
    post = _make_post(repo, [
        CarouselSlide(index=1, role="hook", headline="6개월을 날린 실수",
                      body="도구만 늘렸습니다", emphasis=["6개월"]),
        CarouselSlide(index=2, role="cta", headline="지금 몇 개 쓰시나요?"),
    ])

    detail = client.get(f"/api/posts/{post.id}").json()

    assert [s["index"] for s in detail["slides"]] == [1, 2]
    first = detail["slides"][0]
    assert first["headline"] == "6개월을 날린 실수"
    assert first["body"] == "도구만 늘렸습니다"
    assert first["emphasis"] == ["6개월"]
    assert first["role"] == "hook"


def test_detail_reports_render_and_upload_state(env, tmp_path):
    client, _, repo = env
    png = tmp_path / "s1.png"
    png.write_bytes(PNG_BYTES)
    post = _make_post(repo, [
        CarouselSlide(index=1, headline="렌더만 됨", image_path=str(png)),
        CarouselSlide(index=2, headline="업로드까지 됨", image_path=str(png),
                      image_url="https://cdn.example.com/2.png"),
        CarouselSlide(index=3, headline="아직 아무것도"),
    ])

    slides = client.get(f"/api/posts/{post.id}").json()["slides"]

    assert (slides[0]["rendered"], slides[0]["uploaded"]) == (True, False)
    assert (slides[1]["rendered"], slides[1]["uploaded"]) == (True, True)
    assert (slides[2]["rendered"], slides[2]["uploaded"]) == (False, False)


def test_detail_lists_slides_blocking_publication(env):
    client, _, repo = env
    post = _make_post(repo, [
        CarouselSlide(index=1, headline="완료", image_url="https://cdn/1.png"),
        CarouselSlide(index=2, headline="미완"),
        CarouselSlide(index=3, headline="미완"),
    ])

    detail = client.get(f"/api/posts/{post.id}").json()

    # 발행을 막는 슬라이드를 그대로 알려준다
    assert detail["slides_missing_images"] == [2, 3]


def test_non_carousel_post_has_empty_slides(env):
    client, _, repo = env
    post = repo.save(Post(
        platform=Platform.THREADS, media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET, topic="텍스트 글",
        content=PostContent(caption_ko="본문", cta=""), status=PostStatus.DRAFT,
    ))
    detail = client.get(f"/api/posts/{post.id}").json()
    assert detail["slides"] == []
    assert detail["slides_missing_images"] == []


# --- 렌더 미리보기 ---

def test_preview_serves_rendered_png(env, tmp_path):
    client, _, repo = env
    png = tmp_path / "card.png"
    png.write_bytes(PNG_BYTES)
    post = _make_post(repo, [CarouselSlide(index=1, headline="훅", image_path=str(png))])

    r = client.get(f"/api/posts/{post.id}/slides/1/preview")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == PNG_BYTES


def test_preview_404s_when_not_rendered(env):
    client, _, repo = env
    post = _make_post(repo, [CarouselSlide(index=1, headline="훅")])
    r = client.get(f"/api/posts/{post.id}/slides/1/preview")
    assert r.status_code == 404
    assert "렌더링" in r.json()["detail"]


def test_preview_404s_for_unknown_slide(env):
    client, _, repo = env
    post = _make_post(repo, [CarouselSlide(index=1, headline="훅")])
    assert client.get(f"/api/posts/{post.id}/slides/99/preview").status_code == 404


def test_preview_404s_when_render_file_was_removed(env, tmp_path):
    client, _, repo = env
    missing = tmp_path / "gone.png"
    post = _make_post(repo, [CarouselSlide(index=1, headline="훅", image_path=str(missing))])
    r = client.get(f"/api/posts/{post.id}/slides/1/preview")
    assert r.status_code == 404
    assert "렌더 파일이 없습니다" in r.json()["detail"]
