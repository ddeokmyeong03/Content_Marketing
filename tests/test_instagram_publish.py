"""Instagram 발행 — 컨테이너 준비 폴링과 캐러셀 슬라이드 구조 검증.

컨테이너 생성은 비동기다. 고정 시간 대기는 이미지 크기·네트워크에 따라 부족해
발행이 실패하므로 status_code 가 FINISHED 가 될 때까지 확인해야 한다.
"""
import httpx
import pytest

from branding.models import CarouselSlide, Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform
from branding.publisher.base import MetaAPIError
from branding.publisher.instagram import CAROUSEL_MAX, InstagramPublisher


def _post(media_type=MediaType.IMAGE, **content_kw) -> Post:
    return Post(
        platform=Platform.INSTAGRAM,
        media_type=media_type,
        content_pillar=ContentPillar.AUTOMATION_TIPS,
        topic="테스트",
        content=PostContent(caption_ko="본문", cta="저장해두세요", **content_kw),
    )


class FakeGraph:
    """컨테이너 생성 → 상태 조회 → 발행 흐름을 흉내내는 MockTransport 핸들러.

    `statuses` 는 컨테이너별로 순차 반환할 status_code 목록.
    """

    def __init__(self, statuses: list[str] | None = None):
        self.statuses = statuses if statuses is not None else ["FINISHED"]
        self.created: list[dict] = []
        self.status_calls = 0
        self.published: list[dict] = []
        self._next_id = 100

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/media_publish"):
            self.published.append(dict(httpx.QueryParams(request.content.decode())))
            return httpx.Response(200, json={"id": "IG_MEDIA_1"})
        if request.method == "POST" and path.endswith("/media"):
            self._next_id += 1
            self.created.append(dict(httpx.QueryParams(request.content.decode())))
            return httpx.Response(200, json={"id": str(self._next_id)})
        if request.method == "GET" and "status_code" in request.url.params.get("fields", ""):
            idx = min(self.status_calls, len(self.statuses) - 1)
            self.status_calls += 1
            return httpx.Response(200, json={"status_code": self.statuses[idx]})
        if request.method == "GET":  # permalink 조회
            return httpx.Response(200, json={"permalink": "https://instagram.com/p/x"})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})


def _publisher(handler: FakeGraph, **kw) -> InstagramPublisher:
    return InstagramPublisher(
        access_token="tok",
        user_id="123",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,   # 테스트는 대기 없이
        **kw,
    )


# --- 컨테이너 준비 폴링 ---

def test_waits_until_container_is_finished_before_publishing():
    graph = FakeGraph(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
    post = _post(image_urls=["https://cdn.example.com/a.png"])

    result = _publisher(graph).publish(post)

    assert result.meta_post_id == "IG_MEDIA_1"
    assert graph.status_calls == 3          # 준비될 때까지 확인
    assert len(graph.published) == 1        # 준비된 뒤에 한 번만 발행


def test_container_error_fails_without_publishing():
    graph = FakeGraph(["IN_PROGRESS", "ERROR"])
    post = _post(image_urls=["https://cdn.example.com/a.png"])

    with pytest.raises(MetaAPIError) as excinfo:
        _publisher(graph).publish(post)

    assert "ERROR" in str(excinfo.value)
    assert graph.published == []            # 실패한 컨테이너를 발행하지 않음


def test_timeout_is_retryable_so_scheduler_can_try_again():
    graph = FakeGraph(["IN_PROGRESS"])      # 끝내 준비되지 않음
    post = _post(image_urls=["https://cdn.example.com/a.png"])

    with pytest.raises(MetaAPIError) as excinfo:
        _publisher(graph, poll_max_attempts=3).publish(post)

    assert excinfo.value.retryable is True  # 영구 실패가 아니라 재시도 대상
    assert graph.status_calls == 3
    assert graph.published == []


# --- 캐러셀: 자식 컨테이너도 모두 준비되어야 한다 ---

def test_carousel_waits_for_every_child_then_parent():
    graph = FakeGraph(["FINISHED"])
    slides = [
        CarouselSlide(index=1, role="hook", headline="훅", image_url="https://cdn/1.png"),
        CarouselSlide(index=2, role="body", headline="본문", image_url="https://cdn/2.png"),
        CarouselSlide(index=3, role="cta", headline="CTA", image_url="https://cdn/3.png"),
    ]
    post = _post(MediaType.CAROUSEL, slides=slides)

    _publisher(graph).publish(post)

    # 자식 3개 + 부모 1개 = 컨테이너 4개 생성
    assert len(graph.created) == 4
    # 자식 3회 + 부모 1회 상태 확인
    assert graph.status_calls == 4
    assert len(graph.published) == 1


def test_carousel_uses_slide_order_not_insertion_order():
    graph = FakeGraph(["FINISHED"])
    slides = [
        CarouselSlide(index=3, headline="세번째", image_url="https://cdn/3.png"),
        CarouselSlide(index=1, headline="첫번째", image_url="https://cdn/1.png"),
        CarouselSlide(index=2, headline="두번째", image_url="https://cdn/2.png"),
    ]
    post = _post(MediaType.CAROUSEL, slides=slides)

    _publisher(graph).publish(post)

    child_urls = [c["image_url"] for c in graph.created if c.get("is_carousel_item")]
    assert child_urls == ["https://cdn/1.png", "https://cdn/2.png", "https://cdn/3.png"]


def test_carousel_respects_platform_max_slides():
    graph = FakeGraph(["FINISHED"])
    slides = [
        CarouselSlide(index=i, headline=f"s{i}", image_url=f"https://cdn/{i}.png")
        for i in range(1, 15)
    ]
    post = _post(MediaType.CAROUSEL, slides=slides)

    _publisher(graph).publish(post)

    children = [c for c in graph.created if c.get("is_carousel_item")]
    assert len(children) == CAROUSEL_MAX     # 10장까지만 발행


# --- 이미지가 없을 때: 무엇이 빠졌는지 알려준다 ---

def test_missing_images_names_the_incomplete_slides():
    graph = FakeGraph()
    slides = [
        CarouselSlide(index=1, headline="훅", image_url="https://cdn/1.png"),
        CarouselSlide(index=2, headline="본문"),                 # 이미지 없음
        CarouselSlide(index=3, headline="CTA"),                  # 이미지 없음
    ]
    post = _post(MediaType.CAROUSEL, slides=slides)

    # 슬라이드가 있으나 일부만 렌더링된 상태 → 반쪽짜리 발행 대신 원인을 짚어 실패
    assert post.content.publish_image_urls() == ["https://cdn/1.png"]
    assert post.content.missing_slide_images() == [2, 3]

    with pytest.raises(MetaAPIError) as excinfo:
        _publisher(graph).publish(post)
    assert "[2, 3]" in str(excinfo.value)   # 빠진 슬라이드를 그대로 알려준다
    assert graph.created == []              # 부분 발행하지 않음


def test_no_images_at_all_explains_what_is_empty():
    graph = FakeGraph()
    with pytest.raises(MetaAPIError) as excinfo:
        _publisher(graph).publish(_post())
    assert "image_urls" in str(excinfo.value)
    assert graph.created == []


def test_slides_without_any_image_report_missing_indexes():
    graph = FakeGraph()
    post = _post(MediaType.CAROUSEL, slides=[
        CarouselSlide(index=1, headline="훅"),
        CarouselSlide(index=2, headline="본문"),
    ])
    with pytest.raises(MetaAPIError) as excinfo:
        _publisher(graph).publish(post)
    assert "[1, 2]" in str(excinfo.value)


# --- 슬라이드 구조 자체 ---

def test_slides_take_precedence_over_flat_image_urls():
    content = PostContent(
        caption_ko="c", cta="",
        image_urls=["https://old/legacy.png"],
        slides=[CarouselSlide(index=1, headline="새 슬라이드", image_url="https://new/1.png")],
    )
    assert content.publish_image_urls() == ["https://new/1.png"]


def test_flat_image_urls_still_work_without_slides():
    content = PostContent(caption_ko="c", cta="", image_urls=["https://cdn/a.png"])
    assert content.publish_image_urls() == ["https://cdn/a.png"]
    assert content.missing_slide_images() == []


def test_slide_structure_survives_db_round_trip(tmp_path):
    from branding.config.settings import Settings
    from branding.db import PostRepository, init_db

    settings = Settings(data_dir=tmp_path)
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)

    post = _post(MediaType.CAROUSEL, slides=[
        CarouselSlide(
            index=1, role="hook", headline="이걸 몰라서 6개월을 날렸습니다",
            body="자동화 도구만 늘리던 시절", emphasis=["6개월"],
            image_brief="다크 배경 텍스트 카드",
        ),
    ])
    saved = repo.save(post)

    loaded = repo.get_by_id(saved.id)
    slide = loaded.content.slides[0]
    assert slide.headline == "이걸 몰라서 6개월을 날렸습니다"
    assert slide.role == "hook"
    assert slide.emphasis == ["6개월"]
    assert slide.image_brief == "다크 배경 텍스트 카드"
    assert slide.image_url is None          # 아직 렌더링 전
