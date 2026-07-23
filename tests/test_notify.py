import json

import httpx

from branding.config.settings import Settings
from branding.notify import (
    ConsoleNotifier,
    MultiNotifier,
    Notification,
    Notifier,
    WebhookNotifier,
    get_notifier,
)


def test_webhook_notifier_posts_slack_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    n = WebhookNotifier("http://hook.test/abc", transport=httpx.MockTransport(handler))
    n.success("발행 완료", "https://example.com/p/1")

    assert captured["url"] == "http://hook.test/abc"
    assert "발행 완료" in captured["body"]["text"]
    assert "example.com" in captured["body"]["text"]


def test_multinotifier_isolates_channel_failure():
    class Boom(Notifier):
        def send(self, note: Notification) -> None:
            raise RuntimeError("channel down")

    calls = []

    class Rec(Notifier):
        def send(self, note: Notification) -> None:
            calls.append(note.subject)

    MultiNotifier([Boom(), Rec()]).info("hello")
    assert calls == ["hello"]  # 두 번째 채널은 계속 동작


def test_get_notifier_console_only_without_webhook(tmp_path):
    s = Settings(data_dir=tmp_path, notify_webhook_url="")
    notifier = get_notifier(s)
    assert isinstance(notifier, MultiNotifier)
    assert len(notifier._notifiers) == 1
    assert isinstance(notifier._notifiers[0], ConsoleNotifier)


def test_get_notifier_adds_webhook_when_configured(tmp_path):
    s = Settings(data_dir=tmp_path, notify_webhook_url="http://hook.test/x")
    notifier = get_notifier(s)
    assert any(isinstance(n, WebhookNotifier) for n in notifier._notifiers)
