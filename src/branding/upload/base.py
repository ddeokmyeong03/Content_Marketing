"""이미지 업로드 추상화.

Instagram Graph API는 '공개적으로 접근 가능한 이미지 URL'을 요구한다. 렌더러가
만든 로컬 PNG(`slide.image_path`)를 어딘가에 올려 공개 URL(`slide.image_url`)을
얻는 것이 발행의 마지막 조각이다.

호스팅 수단은 운영 환경마다 다르므로(고객이 이미 쓰는 S3/R2, 운영자의 정적 서버 등)
업로더를 갈아끼울 수 있게 추상화한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class UploadError(RuntimeError):
    """업로드 실패 (설정 누락·인증 오류·네트워크 등)."""


@dataclass
class UploadResult:
    key: str        # 저장소 내 경로/키
    url: str        # 공개 URL — 이 값이 slide.image_url 이 된다


class Uploader(ABC):
    """로컬 파일을 공개 URL로 만들어 주는 어댑터."""

    #: 사람이 읽는 이름 (진단 출력용)
    name: str = "uploader"

    @abstractmethod
    def upload(self, path: Path, key: str) -> UploadResult:
        """`path` 파일을 `key` 위치로 올리고 공개 URL을 돌려준다."""

    @abstractmethod
    def check(self) -> None:
        """설정이 갖춰졌는지 확인. 문제가 있으면 UploadError를 올린다."""


def slide_key(post_id: int, index: int, prefix: str = "") -> str:
    """게시물·슬라이드로부터 결정적인 저장 키를 만든다.

    같은 슬라이드를 다시 렌더링하면 같은 키에 덮어써서 사본이 쌓이지 않는다.
    """
    key = f"post_{post_id}/slide_{index:02d}.png"
    prefix = prefix.strip("/")
    return f"{prefix}/{key}" if prefix else key
