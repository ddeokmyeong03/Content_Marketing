"""HTML → PNG (헤드리스 크로미엄).

브라우저가 필요한 유일한 지점이므로 여기에만 가둔다. `playwright`는 선택 의존성
(`pip install -e '.[render]'`)이며, 없으면 무엇을 설치해야 하는지 알려주고 실패한다.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("branding.render")

INSTALL_HINT = (
    "PNG 렌더링에는 playwright가 필요합니다.\n"
    "  pip install -e '.[render]'\n"
    "  playwright install chromium\n"
    "브라우저가 이미 설치돼 있다면 BRANDING_CHROMIUM_PATH 로 실행 파일을 지정할 수 있습니다."
)

# 브라우저를 직접 설치할 수 없는 환경(오프라인·고정 이미지)에서 실행 파일을 지정
CHROMIUM_PATH_ENV = "BRANDING_CHROMIUM_PATH"


def chromium_executable() -> Optional[str]:
    """지정된 크로미엄 실행 파일 경로. 없으면 playwright 기본 탐색을 따른다."""
    path = os.environ.get(CHROMIUM_PATH_ENV, "").strip()
    return path or None


class RenderUnavailable(RuntimeError):
    """렌더링 환경(브라우저)이 준비되지 않음."""


def is_available() -> bool:
    """playwright를 쓸 수 있는지."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def render_html_to_png(html: str, out_path: Path, width: int, height: int) -> Path:
    """HTML 문자열을 정확히 width×height PNG로 굽는다."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RenderUnavailable(INSTALL_HINT) from e

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            executable = chromium_executable()
            launch_kwargs = {"executable_path": executable} if executable else {}
            browser = p.chromium.launch(**launch_kwargs)
            try:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                # 로컬 문자열이므로 네트워크 대기 없이 즉시 렌더
                page.set_content(html, wait_until="load")
                page.screenshot(path=str(out_path))
            finally:
                browser.close()
    except RenderUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 - 브라우저 실행 실패를 한 종류로 묶어 안내
        raise RenderUnavailable(f"헤드리스 브라우저 실행 실패: {e}\n{INSTALL_HINT}") from e

    return out_path
