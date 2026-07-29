"""S3 호환 오브젝트 스토리지 업로더 (AWS S3 · Cloudflare R2 · Backblaze B2 · MinIO).

`endpoint_url`만 바꾸면 같은 코드로 여러 제공자를 쓴다. SigV4 서명을 직접 구현하지
않고 boto3에 맡긴다 — 서명은 틀리기 쉬운데 실 엔드포인트 없이는 검증이 어렵기 때문.
boto3는 선택 의존성(`pip install -e '.[upload]'`)이다.

⚠️ 버킷이 공개 읽기를 허용해야 Instagram이 이미지를 가져갈 수 있다.
   (R2는 ACL을 지원하지 않으므로 버킷 정책·공개 도메인으로 설정한다)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .base import Uploader, UploadError, UploadResult

logger = logging.getLogger("branding.upload")

INSTALL_HINT = "S3 업로드에는 boto3가 필요합니다:\n  pip install -e '.[upload]'"


class S3Uploader(Uploader):
    name = "s3"

    def __init__(
        self,
        bucket: str,
        region: str = "",
        endpoint_url: str = "",
        access_key_id: str = "",
        secret_access_key: str = "",
        public_base_url: str = "",
        acl: str = "",
        client=None,
    ):
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url.rstrip("/")
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.public_base_url = public_base_url.rstrip("/")
        self.acl = acl                # 비우면 ACL을 보내지 않음 (R2 등 미지원 대비)
        self._client = client         # 테스트에서 스텁 주입

    # --- 설정 ---

    def check(self) -> None:
        if not self.bucket:
            raise UploadError("S3_BUCKET 이 필요합니다.")
        if not self.public_base_url and not self.endpoint_url and not self.region:
            raise UploadError(
                "공개 URL을 만들 수 없습니다. S3_PUBLIC_BASE_URL, S3_ENDPOINT_URL, "
                "S3_REGION 중 하나는 설정해야 합니다."
            )

    def client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as e:
            raise UploadError(INSTALL_HINT) from e

        kwargs = {}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.region:
            kwargs["region_name"] = self.region
        if self.access_key_id and self.secret_access_key:
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key
        # 자격증명을 주지 않으면 boto3 기본 체인(환경변수·프로필·IAM 역할)을 따른다
        self._client = boto3.client("s3", **kwargs)
        return self._client

    # --- 공개 URL ---

    def public_url(self, key: str) -> str:
        """업로드한 객체의 공개 URL.

        커스텀 도메인(public_base_url)이 있으면 그것을 우선한다 — R2·CDN을 쓰는
        환경에서는 엔드포인트 URL이 공개 주소가 아니기 때문.
        """
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        if self.endpoint_url:
            return f"{self.endpoint_url}/{self.bucket}/{key}"
        host = f"s3.{self.region}.amazonaws.com" if self.region else "s3.amazonaws.com"
        return f"https://{self.bucket}.{host}/{key}"

    # --- 업로드 ---

    def upload(self, path: Path, key: str) -> UploadResult:
        self.check()
        path = Path(path)
        if not path.exists():
            raise UploadError(f"업로드할 파일이 없습니다: {path}")

        extra: dict[str, str] = {"ContentType": "image/png"}
        if self.acl:
            extra["ACL"] = self.acl

        try:
            with path.open("rb") as f:
                self.client().put_object(
                    Bucket=self.bucket, Key=key, Body=f, **extra
                )
        except UploadError:
            raise
        except Exception as e:  # noqa: BLE001 - boto3 예외를 한 종류로 묶어 안내
            raise UploadError(f"S3 업로드 실패 ({key}): {e}") from e

        return UploadResult(key=key, url=self.public_url(key))
