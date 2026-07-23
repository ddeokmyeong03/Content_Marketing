"""콘솔(로그) 알림 채널."""
from __future__ import annotations

import logging

from .base import Notification, Notifier

logger = logging.getLogger("branding.notify")

_LEVEL_MAP = {
    "info": logging.INFO,
    "success": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class ConsoleNotifier(Notifier):
    def send(self, note: Notification) -> None:
        level = _LEVEL_MAP.get(note.level, logging.INFO)
        icon = {"success": "✓", "error": "✗", "warning": "⚠"}.get(note.level, "•")
        msg = f"[알림] {icon} {note.subject}"
        if note.body:
            msg += f" — {note.body}"
        logger.log(level, msg)
