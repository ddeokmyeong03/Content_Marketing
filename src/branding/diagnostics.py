"""연결 진단 — 실행 전에 키·토큰·ID가 실제로 동작하는지 검사한다.

'실행해 봐야 잘못된 걸 아는' 문제를 없애는 계층. 각 검사는 실제 API를 호출해
성공/실패와 **해결 힌트**를 돌려주고, 가능하면 올바른 값(숫자 사용자 ID 등)을
자동 탐색해 저장(autofix)한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .config.settings import Settings
from .db import SettingsStore, TokenRepository

logger = logging.getLogger("branding.diagnostics")

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


@dataclass
class Check:
    name: str
    status: str
    message: str
    hint: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "status": self.status, "message": self.message,
            "hint": self.hint, "data": self.data,
        }


class Diagnostics:
    def __init__(
        self,
        settings: Settings,
        store: Optional[SettingsStore] = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.store = store or SettingsStore(settings.db_path)
        self._transport = transport

    # --- HTTP helper ---
    def _get(self, url: str, params: dict) -> tuple[int, dict]:
        try:
            with httpx.Client(timeout=20.0, transport=self._transport) as c:
                r = c.get(url, params=params)
        except httpx.HTTPError as e:
            return 0, {"error": {"message": f"네트워크 오류: {e}"}}
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"error": {"message": r.text[:200]}}

    @staticmethod
    def _err(payload: dict) -> str:
        e = payload.get("error")
        if isinstance(e, dict):
            return str(e.get("message", ""))
        return str(e or "")

    def _token(self, platform: str) -> str:
        """token_store → settings_store/.env 순으로 토큰 해석 (실제 사용 순서와 동일)."""
        return TokenRepository(self.settings.db_path).get_token(platform) or \
            self.settings.meta_access_token

    # --- 개별 검사 ---

    def check_brand_config(self) -> Check:
        from .config import load_brand_config
        try:
            b = load_brand_config(self.settings.brand_config_path)
        except FileNotFoundError:
            return Check("브랜드 설정", FAIL, "brand/config.yaml 을 찾을 수 없습니다.",
                         "BRAND_CONFIG_PATH 를 확인하세요.")
        except Exception as e:  # noqa: BLE001 - YAML/스키마 오류
            return Check("브랜드 설정", FAIL, f"설정 파싱 실패: {e}",
                         "config.yaml 의 들여쓰기·필드명을 확인하세요.")
        if not b.niche:
            return Check("브랜드 설정", WARN, "niche 가 비어 있습니다.",
                         "니치가 구체적일수록 카피가 날카로워집니다.")
        return Check("브랜드 설정", OK, f"'{b.niche[:30]}' · 목표지표 {b.engagement.primary_metric}")

    def check_anthropic(self) -> Check:
        key = self.settings.anthropic_api_key
        if not key:
            return Check("Anthropic API", FAIL, "키가 설정되지 않았습니다.",
                         "설정·실행 탭에서 ANTHROPIC_API_KEY 를 등록하세요.")
        if not key.startswith("sk-"):
            return Check("Anthropic API", WARN, "키 형식이 일반적이지 않습니다(sk- 로 시작하지 않음).",
                         "복사 시 앞뒤 공백이 섞이지 않았는지 확인하세요.")
        try:
            with httpx.Client(timeout=20.0, transport=self._transport) as c:
                r = c.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                )
        except httpx.HTTPError as e:
            return Check("Anthropic API", FAIL, f"네트워크 오류: {e}", "방화벽/프록시를 확인하세요.")
        if r.status_code == 401:
            return Check("Anthropic API", FAIL, "키가 거부되었습니다(401).",
                         "키가 폐기되었거나 잘못 복사되었습니다. 새 키를 발급하세요.")
        if r.status_code >= 400:
            return Check("Anthropic API", FAIL, f"오류 {r.status_code}", r.text[:120])
        return Check("Anthropic API", OK, "키 정상 · 콘텐츠 생성 가능")

    def check_threads(self, autofix: bool = False) -> Check:
        token = self._token("threads")
        if not token:
            return Check("Threads 연결", SKIP, "토큰이 없습니다.",
                         "Threads 전용 토큰(threads_basic 권한)을 등록하세요.")
        status, payload = self._get(
            f"{self.settings.threads_graph_base}/v1.0/me",
            {"fields": "id,username", "access_token": token},
        )
        if status == 0:
            return Check("Threads 연결", FAIL, self._err(payload),
                         "네트워크/프록시가 graph.threads.net 접근을 막고 있습니다. "
                         "이 검사는 실제 운영 환경(로컬 PC)에서 실행하세요.")
        if status >= 400 or "error" in payload:
            msg = self._err(payload)
            hint = "Threads 전용 토큰인지 확인하세요 (Instagram/Facebook 토큰은 사용 불가)."
            if "decrypt" in msg.lower():
                hint = ("토큰이 Threads용이 아닙니다. Meta 개발자 앱 → Use cases → Threads 에서 "
                        "발급한 토큰(threads_basic 포함)을 사용하세요.")
            elif "OAuth" in msg or "parse" in msg.lower():
                hint = "토큰 값이 잘리거나 공백이 섞였습니다. 전체 문자열을 다시 복사하세요."
            elif "expire" in msg.lower():
                hint = "토큰이 만료되었습니다. 재발급 후 등록하세요."
            return Check("Threads 연결", FAIL, msg or f"오류 {status}", hint)

        real_id = str(payload.get("id", ""))
        username = payload.get("username", "")
        configured = self.settings.meta_threads_user_id
        data = {"id": real_id, "username": username}

        if configured != real_id:
            if autofix and real_id:
                self.store.set("meta_threads_user_id", real_id)
                return Check("Threads 연결", OK,
                             f"@{username} 연결됨 · 사용자 ID를 {real_id} 로 자동 수정했습니다.",
                             data=data)
            return Check(
                "Threads 연결", WARN,
                f"@{username} 토큰은 정상이나, 설정된 사용자 ID가 다릅니다"
                f"(설정값: '{configured or '없음'}').",
                f"올바른 숫자 ID는 {real_id} 입니다. --fix 로 자동 수정할 수 있습니다.",
                data=data,
            )
        return Check("Threads 연결", OK, f"@{username} ({real_id}) · 발행 가능", data=data)

    def check_instagram(self, autofix: bool = False) -> Check:
        token = self._token("instagram")
        if not token:
            return Check("Instagram 연결", SKIP, "토큰이 없습니다.",
                         "Instagram 발행이 필요하면 Meta 토큰을 등록하세요.")
        base = f"{self.settings.meta_graph_base}/{self.settings.meta_graph_version}"
        ig_id = self.settings.meta_ig_user_id

        if ig_id:
            status, payload = self._get(
                f"{base}/{ig_id}", {"fields": "username,followers_count", "access_token": token},
            )
            if status < 400 and "error" not in payload:
                return Check("Instagram 연결", OK,
                             f"@{payload.get('username','')} · 팔로워 {payload.get('followers_count',0)}",
                             data={"id": ig_id, "username": payload.get("username", "")})

        # ID가 없거나 틀렸으면 페이지에서 자동 탐색
        status, payload = self._get(f"{base}/me/accounts", {"access_token": token})
        if status == 0:
            return Check("Instagram 연결", FAIL, self._err(payload),
                         "네트워크/프록시가 graph.facebook.com 접근을 막고 있습니다. "
                         "이 검사는 실제 운영 환경(로컬 PC)에서 실행하세요.")
        if status >= 400 or "error" in payload:
            msg = self._err(payload)
            return Check("Instagram 연결", FAIL, msg or f"오류 {status}",
                         "토큰 권한(instagram_basic, instagram_content_publish, pages_show_list)을 확인하세요.")
        for page in payload.get("data", []):
            st2, p2 = self._get(
                f"{base}/{page.get('id')}",
                {"fields": "instagram_business_account", "access_token": token},
            )
            acct = (p2 or {}).get("instagram_business_account") or {}
            found = str(acct.get("id", ""))
            if found:
                if autofix:
                    self.store.set("meta_ig_user_id", found)
                    return Check("Instagram 연결", OK,
                                 f"비즈니스 계정 {found} 을 찾아 자동 저장했습니다.",
                                 data={"id": found})
                return Check("Instagram 연결", WARN,
                             f"연결된 비즈니스 계정을 찾았습니다: {found}",
                             "--fix 로 META_IG_USER_ID 를 자동 저장할 수 있습니다.",
                             data={"id": found})
        return Check("Instagram 연결", FAIL, "연결된 Instagram 비즈니스 계정을 찾지 못했습니다.",
                     "Instagram을 프로(비즈니스) 계정으로 전환하고 Facebook 페이지에 연결하세요.")

    def check_publish_readiness(self) -> Check:
        """실제 발행이 가능한 상태인지 요약."""
        ready = []
        if self._token("threads") and self.settings.meta_threads_user_id:
            ready.append("Threads(텍스트)")
        if self._token("instagram") and self.settings.meta_ig_user_id:
            ready.append("Instagram(이미지 URL 필요)")
        if not ready:
            return Check("발행 준비", FAIL, "발행 가능한 플랫폼이 없습니다.",
                         "토큰과 사용자 ID를 먼저 연결하세요.")
        return Check("발행 준비", OK, " · ".join(ready) + " 발행 가능")

    def run_all(self, autofix: bool = False) -> list[Check]:
        return [
            self.check_brand_config(),
            self.check_anthropic(),
            self.check_threads(autofix=autofix),
            self.check_instagram(autofix=autofix),
            self.check_publish_readiness(),
        ]
