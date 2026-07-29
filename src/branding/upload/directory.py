"""디렉터리 업로더 — 이미 정적 웹 서버가 있는 환경용.

파일을 공개 디렉터리로 복사하고 `{base_url}/{key}`를 돌려준다. nginx·Netlify·
GitHub Pages 등 이미 정적 호스팅이 있는 운영자가 별도 저장소 계약 없이 쓸 수 있고,
네트워크가 없어도 동작해 테스트에도 쓰인다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .base import Uploader, UploadError, UploadResult


class DirectoryUploader(Uploader):
    name = "dir"

    def __init__(self, root: Path | str, base_url: str):
        self.root = Path(root)
        self.base_url = base_url.rstrip("/")

    def check(self) -> None:
        if not self.base_url:
            raise UploadError(
                "UPLOAD_PUBLIC_BASE_URL 이 필요합니다 — 복사한 파일이 어떤 URL로 "
                "노출되는지 알아야 발행할 수 있습니다."
            )
        if not str(self.root):
            raise UploadError("UPLOAD_DIR 이 필요합니다.")

    def upload(self, path: Path, key: str) -> UploadResult:
        self.check()
        path = Path(path)
        if not path.exists():
            raise UploadError(f"업로드할 파일이 없습니다: {path}")

        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        return UploadResult(key=key, url=f"{self.base_url}/{key}")
