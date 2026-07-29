from ..config.settings import Settings
from .base import Uploader, UploadError, UploadResult, slide_key
from .directory import DirectoryUploader
from .s3 import S3Uploader
from .service import UploadedSlide, UploadService

__all__ = [
    "Uploader",
    "UploadError",
    "UploadResult",
    "slide_key",
    "DirectoryUploader",
    "S3Uploader",
    "UploadService",
    "UploadedSlide",
    "get_uploader",
]

PROVIDERS = ("dir", "s3")


def get_uploader(settings: Settings) -> Uploader:
    """설정에 맞는 업로더를 만든다.

    제공자를 고르지 않았으면 무엇을 설정해야 하는지 알려주고 실패한다 —
    조용히 아무것도 안 하면 발행 단계에서야 원인을 찾게 된다.
    """
    provider = (settings.upload_provider or "").strip().lower()
    if not provider:
        raise UploadError(
            "업로드 제공자가 설정되지 않았습니다. UPLOAD_PROVIDER 를 "
            f"{' 또는 '.join(PROVIDERS)} 중 하나로 지정하세요."
        )
    if provider == "dir":
        return DirectoryUploader(
            root=settings.upload_dir, base_url=settings.upload_public_base_url
        )
    if provider == "s3":
        return S3Uploader(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            public_base_url=settings.upload_public_base_url,
            acl=settings.s3_acl,
        )
    raise UploadError(
        f"알 수 없는 업로드 제공자: {provider} (가능: {', '.join(PROVIDERS)})"
    )
