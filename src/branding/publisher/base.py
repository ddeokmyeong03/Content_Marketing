"""Meta/Threads Graph API 발행 공통 기반."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx


class MetaAPIError(Exception):
    """Graph API 호출 실패."""

    def __init__(self, message: str, status: Optional[int] = None, body: Optional[dict] = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


@dataclass
class PublishResult:
    """발행 성공 결과."""

    meta_post_id: str
    permalink: Optional[str] = None
    raw: dict = field(default_factory=dict)


class GraphHTTP:
    """`{base}/{version}` 접두사를 붙여 GET/POST를 수행하는 얇은 httpx 래퍼.

    실패 시 응답 본문의 error 메시지를 담아 MetaAPIError를 발생시킵니다.
    """

    def __init__(self, base: str, version: str, timeout: float = 30.0):
        self._base = f"{base.rstrip('/')}/{version}"
        self._timeout = timeout

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
        url = f"{self._base}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.request(method, url, data=data, params=params)
        except httpx.HTTPError as e:
            raise MetaAPIError(f"네트워크 오류: {e}") from e

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
            )
        return payload
