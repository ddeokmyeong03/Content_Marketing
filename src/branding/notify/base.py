"""알림 추상화."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Notification:
    subject: str
    body: str = ""
    level: str = "info"  # info | success | warning | error


class Notifier(ABC):
    @abstractmethod
    def send(self, note: Notification) -> None: ...

    # 편의 메서드
    def info(self, subject: str, body: str = "") -> None:
        self.send(Notification(subject, body, "info"))

    def success(self, subject: str, body: str = "") -> None:
        self.send(Notification(subject, body, "success"))

    def warning(self, subject: str, body: str = "") -> None:
        self.send(Notification(subject, body, "warning"))

    def error(self, subject: str, body: str = "") -> None:
        self.send(Notification(subject, body, "error"))


class MultiNotifier(Notifier):
    """여러 알림 채널로 동시 전송. 한 채널 실패가 다른 채널을 막지 않음."""

    def __init__(self, notifiers: list[Notifier]):
        self._notifiers = notifiers

    def send(self, note: Notification) -> None:
        for n in self._notifiers:
            try:
                n.send(note)
            except Exception:  # noqa: BLE001 - 알림 실패는 본 작업을 막지 않음
                import logging

                logging.getLogger("branding.notify").warning(
                    "알림 채널 전송 실패: %s", type(n).__name__
                )
