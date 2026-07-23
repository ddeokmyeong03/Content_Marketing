from ..config.settings import Settings
from .base import MultiNotifier, Notification, Notifier
from .console import ConsoleNotifier
from .webhook import WebhookNotifier

__all__ = [
    "Notification",
    "Notifier",
    "MultiNotifier",
    "ConsoleNotifier",
    "WebhookNotifier",
    "get_notifier",
]


def get_notifier(settings: Settings) -> Notifier:
    """설정 기반 알림기 구성. 콘솔은 항상 켜고, webhook URL이 있으면 추가."""
    channels: list[Notifier] = [ConsoleNotifier()]
    if settings.notify_webhook_url:
        channels.append(WebhookNotifier(settings.notify_webhook_url))
    return MultiNotifier(channels)
