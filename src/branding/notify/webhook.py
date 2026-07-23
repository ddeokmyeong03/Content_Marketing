"""Webhook(Slack 호환) 알림 채널."""
from __future__ import annotations

import logging

import httpx

from .base import Notification, Notifier

logger = logging.getLogger("branding.notify")

_EMOJI = {"success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️"}


class WebhookNotifier(Notifier):
    """`{"text": ...}` JSON을 POST. Slack/Discord incoming webhook과 호환."""

    def __init__(
        self,
        url: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._url = url
        self._timeout = timeout
        self._transport = transport

    def send(self, note: Notification) -> None:
        emoji = _EMOJI.get(note.level, "ℹ️")
        text = f"{emoji} *{note.subject}*"
        if note.body:
            text += f"\n{note.body}"
        with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
            resp = client.post(self._url, json={"text": text})
            if resp.status_code >= 400:
                logger.warning("Webhook 알림 실패 (%s): %s", resp.status_code, resp.text[:200])
