"""Meta/Threads Graph API 발행 공통 기반.

일시적 오류(네트워크 끊김·레이트 리밋·5xx)는 같은 요청을 다시 보내면 성공할 수
있으므로 `GraphHTTP` 안에서 지수 백오프로 재시도한다. 토큰·권한·입력 오류는
재시도해도 결과가 같으므로 즉시 올린다. 이 구분이 `MetaAPIError.retryable`이다.

무인 운영에서 순간 장애 하나로 예약 게시물이 죽지 않게 하는 1차 방어선이며,
더 긴 장애는 `PublishService`가 잡 주기를 넘겨 재시도한다(2차 방어선).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

logger = logging.getLogger("branding.publisher.http")

# 재시도할 가치가 있는 Meta Graph API 오류 코드
#   1·2            서버 일시 오류 / 서비스 일시 중단
#   4·17·32·341    앱·사용자·페이지·애플리케이션 호출 한도
#   613            호출 한도 초과
#   80001~80004    플랫폼별 레이트 리밋
TRANSIENT_ERROR_CODES: frozenset[int] = frozenset(
    {1, 2, 4, 17, 32, 341, 613, 80001, 80002, 80003, 80004}
)
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})

DEFAULT_MAX_RETRIES = 2        # 최초 시도 + 재시도 2회 = 최대 3회
DEFAULT_BACKOFF_SECONDS = 1.0  # 1s → 2s (지수)


class MetaAPIError(Exception):
    """Graph API 호출 실패.

    `retryable`: 같은 요청을 그대로 다시 보낼 가치가 있는가.
    """

    def __init__(
        self,
        message: str,
        status: Optional[int] = None,
        body: Optional[dict] = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.body = body or {}
        self.retryable = retryable


@dataclass
class PublishResult:
    """발행 성공 결과."""

    meta_post_id: str
    permalink: Optional[str] = None
    raw: dict = field(default_factory=dict)


def classify_retryable(status: Optional[int], payload: dict) -> bool:
    """응답 상태·본문으로 일시적 오류 여부를 판정."""
    if status in RETRYABLE_STATUS:
        return True
    err = payload.get("error")
    if not isinstance(err, dict):
        return False
    if err.get("is_transient"):
        return True
    return err.get("code") in TRANSIENT_ERROR_CODES


class GraphHTTP:
    """`{base}/{version}` 접두사를 붙여 GET/POST를 수행하는 얇은 httpx 래퍼.

    실패 시 응답 본문의 error 메시지를 담아 MetaAPIError를 발생시키며,
    일시적 오류는 지수 백오프로 `max_retries`회까지 재시도합니다.
    """

    def __init__(
        self,
        base: str,
        version: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._base = f"{base.rstrip('/')}/{version}"
        self._timeout = timeout
        self._transport = transport  # 테스트에서 httpx.MockTransport 주입용
        self._max_retries = max(0, max_retries)
        self._backoff = backoff_seconds
        self._sleep = sleep  # 테스트에서 지연 없이 주입 가능

    def post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, data=data)

    def get(self, path: str, params: dict) -> dict:
        return self._request("GET", path, params=params)

    def _request(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """일시적 오류면 지수 백오프로 재시도하고, 그 외에는 즉시 올린다."""
        attempt = 0
        while True:
            try:
                return self._request_once(method, path, data=data, params=params)
            except MetaAPIError as e:
                if not e.retryable or attempt >= self._max_retries:
                    raise
                delay = self._backoff * (2**attempt)
                attempt += 1
                logger.warning(
                    "Graph API 일시 오류 — %.1f초 후 재시도 (%d/%d): %s",
                    delay,
                    attempt,
                    self._max_retries,
                    e,
                )
                self._sleep(delay)

    def _request_once(
        self,
        method: str,
        path: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        url = f"{self._base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.request(method, url, data=data, params=params)
        except httpx.HTTPError as e:
            # 네트워크 계층 오류는 언제나 재시도 대상
            raise MetaAPIError(f"네트워크 오류: {e}", retryable=True) from e

        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw_text": resp.text}

        if resp.status_code >= 400 or "error" in payload:
            err = payload.get("error", {})
            msg = err.get("message", resp.text) if isinstance(err, dict) else str(err)
            raise MetaAPIError(
                f"Graph API 오류 ({resp.status_code}): {msg}",
                status=resp.status_code,
                body=payload,
                retryable=classify_retryable(resp.status_code, payload),
            )
        return payload
