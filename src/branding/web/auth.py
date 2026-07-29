"""대시보드 인증.

대시보드는 API 키 등록·발행·승인을 할 수 있는 운영 콘솔이다. 인증 없이 외부에
노출되면 계정을 통째로 내주는 것과 같으므로, 두 겹으로 막는다:

  1. 비밀번호가 설정돼 있으면 모든 엔드포인트에 HTTP Basic 인증을 건다
  2. 비밀번호가 없으면 루프백 바인딩만 허용한다 (`cli/commands/web.py`에서 검사)

즉 '인증 없는 콘솔이 실수로 공개되는' 경로를 만들 수 없다.
"""
from __future__ import annotations

import ipaddress
import logging
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..config.settings import Settings

logger = logging.getLogger("branding.web.auth")

_basic = HTTPBasic(auto_error=False)

# 이 호스트들에 바인딩할 때만 인증 없이 실행할 수 있다
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", ""}


def is_loopback(host: str) -> bool:
    """바인드 주소가 이 기기 밖에서 접근 불가능한가."""
    host = (host or "").strip().lower()
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _warn_if_non_ascii(user: str, password: str) -> None:
    """HTTP Basic은 ASCII만 안전하게 실어 나른다.

    한글 등을 쓰면 브라우저가 보낸 값이 디코딩되지 않아 '비밀번호가 맞는데도
    계속 401'이 되는데, 원인을 찾기 어렵다. 조용히 잠기지 않도록 미리 알린다.
    """
    for label, value in (("사용자", user), ("비밀번호", password)):
        if not value.isascii():
            logger.warning(
                "대시보드 %s에 ASCII가 아닌 문자가 있습니다 — HTTP Basic 인증은 "
                "ASCII만 지원하므로 로그인에 실패합니다. 영문·숫자·기호로 바꾸세요.",
                label,
            )


def auth_dependencies(settings: Settings) -> list:
    """설정에 비밀번호가 있으면 Basic 인증 의존성을 돌려준다."""
    password = (settings.web_auth_password or "").strip()
    if not password:
        return []

    user = (settings.web_auth_user or "admin").strip()
    _warn_if_non_ascii(user, password)

    def verify(credentials: Optional[HTTPBasicCredentials] = Depends(_basic)) -> None:
        # 타이밍 공격을 피하려고 항상 두 값을 모두 비교한다
        supplied_user = credentials.username if credentials else ""
        supplied_pw = credentials.password if credentials else ""
        ok_user = secrets.compare_digest(supplied_user.encode(), user.encode())
        ok_pw = secrets.compare_digest(supplied_pw.encode(), password.encode())
        if not (credentials and ok_user and ok_pw):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="인증이 필요합니다.",
                headers={"WWW-Authenticate": "Basic"},
            )

    return [Depends(verify)]
