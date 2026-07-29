"""CLI 안내 문구 검증.

rich 는 `[...]` 를 스타일 태그로 해석한다. 그래서 설치 명령을 그대로 넣으면
대괄호가 **조용히 사라진다**:

    pip install -e '.[web]'   →   pip install -e '.'

안내대로 따라 한 사람은 의존성이 설치되지 않아 같은 오류를 다시 만나고, 무한히
같은 자리를 맴돈다. 오류 메시지가 틀린 명령을 알려주는 것은 없는 것만 못하다.
"""
import pytest
from rich.console import Console

from branding.cli.commands.render import RENDER_INSTALL_CMD
from branding.cli.commands.web import WEB_INSTALL_CMD
from branding.cli.ui import plain
from branding.render.png import INSTALL_HINT as RENDER_HINT
from branding.upload.s3 import INSTALL_HINT as UPLOAD_HINT


def _rendered(markup: str) -> str:
    """실제 콘솔에 찍히는 결과 문자열."""
    console = Console(file=None, record=True, width=200, no_color=True)
    console.print(markup)
    return console.export_text()


# --- 설치 명령이 그대로 살아남는가 ---

@pytest.mark.parametrize(
    "command,extra",
    [
        (WEB_INSTALL_CMD, "[web]"),
        (RENDER_INSTALL_CMD, "[render]"),
        (UPLOAD_HINT, "[upload]"),
        (RENDER_HINT, "[render]"),
    ],
)
def test_install_hints_keep_their_extras_when_printed(command, extra):
    out = _rendered(f"[red]{plain(command)}[/red]")
    assert extra in out, f"설치 명령에서 {extra} 가 사라졌습니다: {out!r}"


def test_unescaped_markup_really_does_swallow_the_extra():
    """이 테스트가 지키려는 버그가 실재함을 고정한다 — plain() 없이는 사라진다."""
    out = _rendered("[red]pip install -e '.[web]'[/red]")
    assert "[web]" not in out


# --- 예외 메시지 일반 ---

def test_exception_text_with_brackets_survives():
    error = ValueError("렌더링되지 않은 슬라이드가 있습니다: [1, 2]")
    assert "[1, 2]" in _rendered(f"[red]{plain(error)}[/red]")


def test_plain_leaves_ordinary_text_alone():
    assert plain("평범한 메시지") == "평범한 메시지"
