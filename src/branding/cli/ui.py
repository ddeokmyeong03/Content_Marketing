"""CLI 출력 헬퍼.

rich 는 `[...]` 를 스타일 태그로 해석한다. 그래서 예외 메시지나 설치 명령을 그대로
넣으면 대괄호 부분이 **조용히 사라진다**:

    console.print(f"설치: pip install -e '.[web]'")   →   설치: pip install -e '.'

안내대로 따라 한 사람은 의존성이 설치되지 않아 같은 오류를 다시 만난다. 오류 메시지가
틀린 명령을 알려주는 것은 없는 것만 못하므로, 마크업이 아닌 텍스트는 반드시 `plain()`
을 거쳐 출력한다.
"""
from __future__ import annotations

from rich.markup import escape


def plain(text: object) -> str:
    """마크업으로 해석되면 안 되는 텍스트(예외·경로·설치 명령)를 그대로 보이게 한다."""
    return escape(str(text))
