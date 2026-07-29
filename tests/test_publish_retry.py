"""발행 재시도·백오프 검증.

일시 장애(레이트 리밋·5xx·네트워크)로 예약 게시물이 영구히 죽지 않아야 한다.
1차 방어선은 GraphHTTP의 in-process 재시도, 2차 방어선은 PublishService가
next_retry_at 을 예약해 스케줄러가 다음 주기에 다시 집어가는 것.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from branding.config.settings import Settings
from branding.db import PostRepository, init_db
from branding.models import Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.publisher import PublishService
from branding.publisher.base import GraphHTTP, MetaAPIError, classify_retryable
from branding.utils.time import now_utc


# --- 오류 분류 (순수 함수) ---

@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (429, {}, True),                                          # 레이트 리밋
        (503, {}, True),                                          # 일시 중단
        (500, {}, True),
        (400, {"error": {"message": "bad token"}}, False),        # 입력·토큰 오류
        (401, {"error": {"message": "invalid"}}, False),
        (400, {"error": {"code": 613}}, True),                    # 호출 한도 초과
        (400, {"error": {"code": 4}}, True),                      # 앱 호출 한도
        (400, {"error": {"is_transient": True}}, True),           # Meta가 일시 오류로 표기
        (400, {"error": {"code": 190}}, False),                   # 액세스 토큰 만료
    ],
)
def test_classify_retryable(status, payload, expected):
    assert classify_retryable(status, payload) is expected


# --- GraphHTTP in-process 재시도 ---

def _http(handler, **kw) -> GraphHTTP:
    return GraphHTTP(
        "https://graph.example.com",
        "v21.0",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,  # 테스트는 대기 없이
        **kw,
    )


def test_graph_http_retries_transient_then_succeeds():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": {"message": "일시 중단"}})
        return httpx.Response(200, json={"id": "17900"})

    assert _http(handler).post("me/threads", {"text": "x"}) == {"id": "17900"}
    assert len(calls) == 3  # 최초 1회 + 재시도 2회


def test_graph_http_does_not_retry_client_error():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})

    with pytest.raises(MetaAPIError) as excinfo:
        _http(handler).post("me/threads", {"text": "x"})

    assert excinfo.value.retryable is False
    assert len(calls) == 1  # 재시도하지 않음


def test_graph_http_gives_up_after_max_retries():
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500, json={"error": {"message": "boom"}})

    with pytest.raises(MetaAPIError) as excinfo:
        _http(handler, max_retries=2).post("me/threads", {"text": "x"})

    assert excinfo.value.retryable is True
    assert len(calls) == 3


def test_network_error_is_retryable():
    def handler(request):
        raise httpx.ConnectError("연결 끊김")

    with pytest.raises(MetaAPIError) as excinfo:
        _http(handler, max_retries=0).post("me/threads", {"text": "x"})

    assert excinfo.value.retryable is True


# --- PublishService 재시도 예약 (2차 방어선) ---

def _settings(tmp_path, **kw) -> Settings:
    s = Settings(meta_threads_user_id="123", data_dir=tmp_path, **kw)
    init_db(s.db_path)
    return s


def _approved_post(repo: PostRepository) -> Post:
    return repo.save(
        Post(
            platform=Platform.THREADS,
            media_type=MediaType.TEXT,
            content_pillar=ContentPillar.MINDSET,
            topic="재시도 테스트",
            content=PostContent(caption_ko="본문", cta=""),
            status=PostStatus.APPROVED,
            scheduled_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    )


def test_transient_failure_schedules_retry_and_is_requeued(tmp_path):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _approved_post(repo)

    outcome = PublishService(settings)._handle_failure(
        post, MetaAPIError("레이트 리밋", status=429, retryable=True)
    )

    assert outcome.will_retry is True
    assert outcome.attempts == 1

    stored = repo.get_by_id(post.id)
    assert stored.status == PostStatus.FAILED
    assert stored.publish_attempts == 1
    assert stored.next_retry_at is not None
    assert stored.last_error and "레이트 리밋" in stored.last_error

    # 재시도 시각이 지나면 다시 발행 큐에 잡힌다
    repo.mark_publish_failure(
        post.id, "레이트 리밋", attempts=1, next_retry_at=now_utc() - timedelta(minutes=1)
    )
    assert [p.id for p in repo.list_pending_publish()] == [post.id]


def test_retry_is_not_due_before_backoff_elapses(tmp_path):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _approved_post(repo)

    PublishService(settings)._handle_failure(
        post, MetaAPIError("일시 오류", status=503, retryable=True)
    )

    # 백오프가 지나기 전에는 큐에 잡히지 않아야 한다(중복 발행 방지)
    assert repo.list_pending_publish() == []


def test_non_retryable_failure_is_permanent(tmp_path):
    settings = _settings(tmp_path)
    repo = PostRepository(settings.db_path)
    post = _approved_post(repo)

    outcome = PublishService(settings)._handle_failure(
        post, MetaAPIError("Invalid OAuth access token", status=400, retryable=False)
    )

    assert outcome.will_retry is False
    stored = repo.get_by_id(post.id)
    assert stored.status == PostStatus.FAILED
    assert stored.next_retry_at is None      # 영구 실패 — 다시 집어가지 않음
    assert repo.list_pending_publish() == []


def test_retry_stops_after_max_attempts(tmp_path):
    settings = _settings(tmp_path, publish_max_attempts=3)
    repo = PostRepository(settings.db_path)
    post = _approved_post(repo)
    service = PublishService(settings)

    # 앞선 2회는 재시도 예약, 3회째에 시도 횟수 소진
    for expected_attempt in (1, 2):
        current = repo.get_by_id(post.id)
        outcome = service._handle_failure(
            current, MetaAPIError("일시 오류", status=503, retryable=True)
        )
        assert (outcome.attempts, outcome.will_retry) == (expected_attempt, True)

    final = service._handle_failure(
        repo.get_by_id(post.id), MetaAPIError("일시 오류", status=503, retryable=True)
    )
    assert final.attempts == 3
    assert final.will_retry is False
    assert repo.get_by_id(post.id).next_retry_at is None
    assert repo.list_pending_publish() == []


def test_backoff_grows_exponentially_and_is_capped(tmp_path):
    settings = _settings(tmp_path, publish_retry_backoff_minutes=5, publish_retry_max_minutes=30)
    service = PublishService(settings)

    assert service._retry_delay_minutes(1) == 5
    assert service._retry_delay_minutes(2) == 10
    assert service._retry_delay_minutes(3) == 20
    assert service._retry_delay_minutes(4) == 30   # 상한
    assert service._retry_delay_minutes(9) == 30
