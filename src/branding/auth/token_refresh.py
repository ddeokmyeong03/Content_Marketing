"""Meta/Threads 롱리브드 토큰 자동 갱신.

- Instagram/Facebook: GET /oauth/access_token?grant_type=fb_exchange_token
    (client_id + client_secret + 현재 토큰 → 새 롱리브드 토큰, ~60일)
- Threads: GET /refresh_access_token?grant_type=th_refresh_token
    (현재 토큰만으로 갱신, ~60일; 최소 24시간 이상 사용된 토큰이어야 함)

만료가 threshold 이내로 임박했을 때만 갱신하고, 결과를 token_store에 반영합니다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import httpx

from ..config.settings import Settings
from ..db import TokenRepository
from ..models.enums import Platform
from ..utils.time import now_utc

logger = logging.getLogger("branding.auth")

DEFAULT_EXPIRES_SECONDS = 60 * 24 * 3600  # 60일 (expires_in 누락 시 fallback)


@dataclass
class RefreshResult:
    platform: str
    refreshed: bool
    reason: str = ""


class TokenRefresher:
    def __init__(
        self,
        settings: Settings,
        token_repo: Optional[TokenRepository] = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.token_repo = token_repo or TokenRepository(settings.db_path)
        self._transport = transport

    def _get(self, url: str, params: dict) -> dict:
        with httpx.Client(timeout=30.0, transport=self._transport) as client:
            resp = client.get(url, params=params)
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if resp.status_code >= 400 or "error" in payload:
            err = payload.get("error", {})
            msg = err.get("message", resp.text) if isinstance(err, dict) else str(err)
            raise RuntimeError(f"토큰 갱신 API 오류 ({resp.status_code}): {msg}")
        return payload

    def _current_token(self, platform: Platform) -> Optional[str]:
        return self.token_repo.get_token(platform.value) or self.settings.meta_access_token

    def _store(self, platform: Platform, payload: dict) -> None:
        new_token = payload["access_token"]
        expires_in = int(payload.get("expires_in") or DEFAULT_EXPIRES_SECONDS)
        expires_at = now_utc() + timedelta(seconds=expires_in)
        self.token_repo.upsert(platform.value, new_token, expires_at=expires_at)
        logger.info("%s 토큰 갱신 완료 (만료: %s)", platform.value, expires_at.date())

    def refresh_platform(self, platform: Platform) -> RefreshResult:
        current = self._current_token(platform)
        if not current:
            return RefreshResult(platform.value, False, "현재 토큰 없음")

        if platform == Platform.THREADS:
            payload = self._get(
                f"{self.settings.threads_graph_base}/refresh_access_token",
                params={"grant_type": "th_refresh_token", "access_token": current},
            )
        else:  # INSTAGRAM (Facebook Graph)
            if not (self.settings.meta_app_id and self.settings.meta_app_secret):
                return RefreshResult(
                    platform.value, False, "META_APP_ID/META_APP_SECRET 미설정"
                )
            base = f"{self.settings.meta_graph_base}/{self.settings.meta_graph_version}"
            payload = self._get(
                f"{base}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.settings.meta_app_id,
                    "client_secret": self.settings.meta_app_secret,
                    "fb_exchange_token": current,
                },
            )

        self._store(platform, payload)
        return RefreshResult(platform.value, True, "갱신됨")

    def refresh_if_needed(
        self, platform: Platform, threshold_days: Optional[int] = None
    ) -> RefreshResult:
        threshold = (
            threshold_days
            if threshold_days is not None
            else self.settings.token_refresh_threshold_days
        )
        expiry = self.token_repo.get_expiry(platform.value)
        if expiry is not None and expiry - now_utc() > timedelta(days=threshold):
            return RefreshResult(platform.value, False, f"만료까지 {threshold}일 초과 — 갱신 불필요")
        return self.refresh_platform(platform)

    def refresh_all_if_needed(self) -> list[RefreshResult]:
        results = []
        for platform in (Platform.INSTAGRAM, Platform.THREADS):
            try:
                results.append(self.refresh_if_needed(platform))
            except Exception as e:  # noqa: BLE001
                logger.warning("%s 토큰 갱신 실패: %s", platform.value, e)
                results.append(RefreshResult(platform.value, False, f"오류: {e}"))
        return results
