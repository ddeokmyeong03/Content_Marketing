"""런타임 설정 해석 — .env 기반 Settings 위에 DB(settings_store) 등록값을 덮어쓴다.

웹 대시보드에서 등록한 키를 CLI·스케줄러·진단이 모두 동일하게 사용하도록 하는 단일 지점.
"""
from __future__ import annotations

from typing import Optional

from .settings import Settings, get_settings


def resolve_settings(base: Optional[Settings] = None, store=None) -> Settings:
    from ..db import SettingsStore  # 지연 임포트(순환 방지)

    base = base or get_settings()
    store = store or SettingsStore(base.db_path)
    try:
        overrides = {
            k: v for k, v in store.all().items() if k in Settings.model_fields and v
        }
    except Exception:  # noqa: BLE001 - DB 미초기화 등
        overrides = {}
    return base.model_copy(update=overrides) if overrides else base
