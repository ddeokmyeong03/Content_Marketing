"""platform=both 부분 발행 원자성 검증.

`both` 는 인스타그램·스레드를 순서대로 호출한다. 앞이 성공하고 뒤가 실패하면
게시물은 FAILED 로 남고 재시도 대상이 되는데, 성공한 쪽을 기록해 두지 않으면
재시도가 이미 올라간 게시물을 한 번 더 올린다 — 되돌릴 수 없는 중복 게시다.

여기서 지키려는 불변식: **한 플랫폼에는 최대 한 번만 발행된다.**
"""
from datetime import datetime, timezone

import pytest

from branding.config.settings import Settings
from branding.db import PostRepository, init_db
from branding.models import Post, PostContent, PostPublication
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.notify.base import Notification, Notifier
from branding.publisher import PublishService
from branding.publisher.base import MetaAPIError, PublishResult


class RecordingNotifier(Notifier):
    def __init__(self):
        self.sent: list[Notification] = []

    def send(self, note: Notification) -> None:
        self.sent.append(note)


class FakePublisher:
    """호출 횟수를 세는 퍼블리셔 — 중복 발행은 곧 호출 횟수로 드러난다."""

    def __init__(self, platform: Platform, calls: list[Platform], error: MetaAPIError | None = None):
        self.platform = platform
        self.calls = calls
        self.error = error

    def publish(self, post):
        self.calls.append(self.platform)
        if self.error:
            raise self.error
        return PublishResult(
            meta_post_id=f"{self.platform.value}-id",
            permalink=f"https://{self.platform.value}.example.com/p/1",
            raw={"id": f"{self.platform.value}-id"},
        )


def _service(settings, calls, failing: dict[Platform, MetaAPIError] | None = None,
             notifier: Notifier | None = None):
    """`_publisher_for` 만 갈아끼워 네트워크 없이 발행 경로를 그대로 태운다."""
    failing = failing or {}
    service = PublishService(settings, notifier=notifier)
    service._publisher_for = lambda p: FakePublisher(p, calls, failing.get(p))
    return service


def _settings(tmp_path, **kw) -> Settings:
    s = Settings(
        meta_threads_user_id="123", meta_ig_user_id="456", data_dir=tmp_path, **kw
    )
    init_db(s.db_path)
    return s


def _both_post(repo: PostRepository) -> Post:
    return repo.save(Post(
        platform=Platform.BOTH,
        media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET,
        topic="양쪽 발행",
        content=PostContent(caption_ko="본문", cta=""),
        status=PostStatus.APPROVED,
        scheduled_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    ))


TRANSIENT = MetaAPIError("일시 오류", status=503, retryable=True)


# --- 기록 저장소 ---

def test_publication_is_recorded_per_platform(tmp_path):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)

    repo.record_publication(PostPublication(
        post_id=post.id, platform=Platform.INSTAGRAM, meta_post_id="ig-1",
    ))

    assert repo.published_platforms(post.id) == {Platform.INSTAGRAM}
    assert [p.meta_post_id for p in repo.list_publications(post.id)] == ["ig-1"]


def test_recording_same_platform_twice_overwrites(tmp_path):
    """재시도 경로에서 다시 기록해도 행이 늘지 않아야 한다."""
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)

    for meta_id in ("ig-1", "ig-2"):
        repo.record_publication(PostPublication(
            post_id=post.id, platform=Platform.INSTAGRAM, meta_post_id=meta_id,
        ))

    publications = repo.list_publications(post.id)
    assert len(publications) == 1
    assert publications[0].meta_post_id == "ig-2"


# --- 부분 성공 후 재시도 ---

def test_partial_success_is_recorded_before_the_failure(tmp_path):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    calls: list[Platform] = []

    outcome = _service(settings, calls, {Platform.THREADS: TRANSIENT}).publish_post(post)

    assert outcome.success is False
    assert outcome.will_retry is True
    assert outcome.published == [Platform.INSTAGRAM]      # 올라간 것은 사실로 남는다
    assert repo.published_platforms(post.id) == {Platform.INSTAGRAM}
    assert repo.get_by_id(post.id).status == PostStatus.FAILED


def test_retry_does_not_republish_the_succeeded_platform(tmp_path):
    """이 시스템에서 가장 비싼 버그 — 재시도가 인스타그램을 두 번 올리는 것."""
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    calls: list[Platform] = []

    _service(settings, calls, {Platform.THREADS: TRANSIENT}).publish_post(post)
    assert calls == [Platform.INSTAGRAM, Platform.THREADS]

    # 재시도: 이번엔 스레드도 성공
    outcome = _service(settings, calls).publish_post(repo.get_by_id(post.id))

    assert calls == [Platform.INSTAGRAM, Platform.THREADS, Platform.THREADS]
    assert outcome.success is True
    assert outcome.published == [Platform.THREADS]
    assert outcome.skipped == [Platform.INSTAGRAM]
    assert repo.published_platforms(post.id) == {Platform.INSTAGRAM, Platform.THREADS}
    assert repo.get_by_id(post.id).status == PostStatus.PUBLISHED


def test_repeated_transient_failures_never_republish(tmp_path):
    """스레드가 계속 실패해도 인스타그램 호출은 최초 1회뿐이어야 한다."""
    settings = _settings(tmp_path, publish_max_attempts=5)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    calls: list[Platform] = []

    for _ in range(3):
        _service(settings, calls, {Platform.THREADS: TRANSIENT}).publish_post(
            repo.get_by_id(post.id)
        )

    assert calls.count(Platform.INSTAGRAM) == 1
    assert calls.count(Platform.THREADS) == 3


def test_primary_link_stays_on_the_first_platform_after_retry(tmp_path):
    """대표 메타데이터가 재시도에서 두 번째 플랫폼으로 뒤바뀌면 안 된다."""
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    calls: list[Platform] = []

    _service(settings, calls, {Platform.THREADS: TRANSIENT}).publish_post(post)
    _service(settings, calls).publish_post(repo.get_by_id(post.id))

    stored = repo.get_by_id(post.id)
    assert stored.meta_post_id == "instagram-id"
    assert stored.permalink == "https://instagram.example.com/p/1"


def test_fully_published_post_calls_no_api(tmp_path):
    """이미 양쪽 다 올라간 게시물을 다시 집어가도 발행하지 않는다."""
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    calls: list[Platform] = []
    _service(settings, calls).publish_post(post)
    assert len(calls) == 2

    outcome = _service(settings, calls).publish_post(repo.get_by_id(post.id))

    assert len(calls) == 2                      # 추가 호출 없음
    assert outcome.success is True
    assert outcome.published == []
    assert outcome.skipped == [Platform.INSTAGRAM, Platform.THREADS]


def test_first_platform_failure_publishes_nothing(tmp_path):
    """앞이 실패하면 뒤는 시도조차 하지 않는다 — 재시도가 온전히 양쪽을 맡는다."""
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    calls: list[Platform] = []

    outcome = _service(settings, calls, {Platform.INSTAGRAM: TRANSIENT}).publish_post(post)

    assert calls == [Platform.INSTAGRAM]
    assert outcome.published == []
    assert repo.published_platforms(post.id) == set()


def test_partial_failure_notification_names_what_already_went_out(tmp_path):
    """한쪽만 올라간 상태를 모르면 사람이 수동으로 중복 게시한다."""
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _both_post(repo)
    notifier = RecordingNotifier()

    _service(settings, [], {Platform.THREADS: TRANSIENT}, notifier).publish_post(post)

    body = notifier.sent[-1].body
    assert "이미 발행됨" in body
    assert "instagram" in body


# --- 단일 플랫폼 게시물은 영향받지 않는다 ---

@pytest.mark.parametrize("platform", [Platform.INSTAGRAM, Platform.THREADS])
def test_single_platform_publish_is_unchanged(tmp_path, platform):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = repo.save(Post(
        platform=platform, media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET, topic="단일",
        content=PostContent(caption_ko="본문", cta=""), status=PostStatus.APPROVED,
    ))
    calls: list[Platform] = []

    outcome = _service(settings, calls).publish_post(post)

    assert calls == [platform]
    assert outcome.success is True
    assert repo.get_by_id(post.id).status == PostStatus.PUBLISHED
    assert repo.published_platforms(post.id) == {platform}


def test_single_platform_retry_does_not_duplicate(tmp_path):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = repo.save(Post(
        platform=Platform.THREADS, media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET, topic="단일 재시도",
        content=PostContent(caption_ko="본문", cta=""), status=PostStatus.APPROVED,
    ))
    calls: list[Platform] = []
    _service(settings, calls).publish_post(post)

    _service(settings, calls).publish_post(repo.get_by_id(post.id))

    assert calls == [Platform.THREADS]
