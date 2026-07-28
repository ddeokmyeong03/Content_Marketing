"""Instagram 발행.

단일 이미지: /media(image_url, caption) → 컨테이너 준비 대기 → /media_publish
카루셀: 각 이미지 자식 컨테이너 생성 → 전부 준비 대기 → CAROUSEL 부모 컨테이너
        → 준비 대기 → /media_publish

컨테이너 생성은 비동기다. Meta가 이미지를 내려받아 처리하는 동안 상태는
IN_PROGRESS이며, FINISHED가 되기 전에 발행하면 실패한다. 고정 시간 대기는 이미지
크기·네트워크에 따라 부족하거나 과할 수 있으므로 `status_code`를 폴링한다.

⚠️ Instagram Graph API는 '공개적으로 접근 가능한 이미지 URL'을 요구합니다.
   슬라이드(content.slides) 또는 content.image_urls 가 비면 발행할 수 없습니다.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

from ..models import Post
from ..models.enums import MediaType
from .base import GraphHTTP, MetaAPIError, PublishResult

logger = logging.getLogger("branding.publisher.instagram")

CAROUSEL_MIN = 2
CAROUSEL_MAX = 10

# 컨테이너 상태 (GET /{container-id}?fields=status_code)
STATUS_FINISHED = "FINISHED"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_ERROR = "ERROR"
STATUS_EXPIRED = "EXPIRED"
STATUS_PUBLISHED = "PUBLISHED"
_TERMINAL_FAILURES = frozenset({STATUS_ERROR, STATUS_EXPIRED})

DEFAULT_POLL_INTERVAL = 3.0   # 초
DEFAULT_POLL_ATTEMPTS = 20    # 최대 약 60초 대기


class InstagramPublisher:
    def __init__(
        self,
        access_token: str,
        user_id: str,
        base: str = "https://graph.facebook.com",
        version: str = "v21.0",
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL,
        poll_max_attempts: int = DEFAULT_POLL_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ):
        if not access_token:
            raise MetaAPIError("Instagram 액세스 토큰이 없습니다.")
        if not user_id:
            raise MetaAPIError("Instagram 사용자 ID(META_IG_USER_ID)가 없습니다.")
        self._token = access_token
        self._user_id = user_id
        self._http = GraphHTTP(base, version, transport=transport)
        self._poll_interval = poll_interval_seconds
        self._poll_attempts = max(1, poll_max_attempts)
        self._sleep = sleep  # 테스트에서 지연 없이 주입 가능

    def publish(self, post: Post) -> PublishResult:
        image_urls = self._resolve_image_urls(post)
        caption = post.full_caption_ko()

        if post.media_type == MediaType.CAROUSEL and len(image_urls) > 1:
            container_id = self._create_carousel(image_urls[:CAROUSEL_MAX], caption)
        else:
            container_id = self._create_single(image_urls[0], caption)

        # 부모/단일 컨테이너가 준비된 뒤에 발행
        self._wait_until_ready(container_id)

        published = self._http.post(
            f"{self._user_id}/media_publish",
            data={"creation_id": container_id, "access_token": self._token},
        )
        media_id = published.get("id")
        if not media_id:
            raise MetaAPIError("Instagram 발행 응답에 id가 없습니다.", body=published)

        permalink = None
        try:
            info = self._http.get(
                str(media_id), params={"fields": "permalink", "access_token": self._token}
            )
            permalink = info.get("permalink")
        except MetaAPIError:
            permalink = None

        return PublishResult(meta_post_id=str(media_id), permalink=permalink, raw=published)

    def _resolve_image_urls(self, post: Post) -> list[str]:
        """발행에 쓸 이미지 URL을 정하고, 없으면 무엇이 빠졌는지 알려준다.

        슬라이드가 일부만 렌더링된 상태로 반쪽짜리 캐러셀이 나가지 않도록,
        빠진 슬라이드 번호를 그대로 알려주고 발행을 막는다.
        """
        content = post.content
        if content.slides:
            missing = content.missing_slide_images()
            if missing:
                raise MetaAPIError(
                    "Instagram 발행에는 공개 이미지 URL이 필요합니다. "
                    f"이미지가 없는 슬라이드: {missing} "
                    "(렌더링·업로드 후 image_url을 채우세요)."
                )
            image_urls = content.publish_image_urls()
        else:
            image_urls = list(content.image_urls)

        if not image_urls:
            raise MetaAPIError(
                "Instagram 발행에는 공개 이미지 URL이 필요합니다. "
                "content.image_urls 와 content.slides 가 모두 비어 있습니다."
            )
        if post.media_type == MediaType.CAROUSEL and len(image_urls) < CAROUSEL_MIN:
            raise MetaAPIError(
                f"캐러셀은 이미지가 최소 {CAROUSEL_MIN}장 필요합니다 (현재 {len(image_urls)}장)."
            )
        return image_urls

    def _container_status(self, container_id: str) -> str:
        info = self._http.get(
            str(container_id),
            params={"fields": "status_code", "access_token": self._token},
        )
        return str(info.get("status_code") or "")

    def _wait_until_ready(self, container_id: str) -> None:
        """컨테이너가 FINISHED가 될 때까지 폴링.

        ERROR/EXPIRED면 즉시 실패로 올리고, 준비되지 않은 채 시도 횟수를 소진하면
        일시 오류로 올려(재시도 대상) 다음 주기에 다시 시도되게 한다.
        """
        for attempt in range(self._poll_attempts):
            status = self._container_status(container_id)
            if status in (STATUS_FINISHED, STATUS_PUBLISHED):
                return
            if status in _TERMINAL_FAILURES:
                raise MetaAPIError(
                    f"Instagram 컨테이너 처리 실패 (status_code={status}). "
                    "이미지 URL이 공개 접근 가능한지 확인하세요."
                )
            logger.debug(
                "컨테이너 %s 준비 대기 중 (status=%s, %d/%d)",
                container_id, status or "UNKNOWN", attempt + 1, self._poll_attempts,
            )
            self._sleep(self._poll_interval)

        raise MetaAPIError(
            f"Instagram 컨테이너가 제한 시간 내에 준비되지 않았습니다 "
            f"(container={container_id}, {self._poll_attempts}회 확인).",
            retryable=True,
        )

    def _create_single(self, image_url: str, caption: str) -> str:
        created = self._http.post(
            f"{self._user_id}/media",
            data={"image_url": image_url, "caption": caption, "access_token": self._token},
        )
        cid = created.get("id")
        if not cid:
            raise MetaAPIError("Instagram 컨테이너 생성 실패", body=created)
        return cid

    def _create_carousel(self, image_urls: list[str], caption: str) -> str:
        children = []
        for url in image_urls:
            child = self._http.post(
                f"{self._user_id}/media",
                data={
                    "image_url": url,
                    "is_carousel_item": "true",
                    "access_token": self._token,
                },
            )
            child_id = child.get("id")
            if not child_id:
                raise MetaAPIError("카루셀 자식 컨테이너 생성 실패", body=child)
            children.append(child_id)

        # 자식이 전부 준비되어야 부모 컨테이너를 만들 수 있다
        for child_id in children:
            self._wait_until_ready(child_id)

        parent = self._http.post(
            f"{self._user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "access_token": self._token,
            },
        )
        pid = parent.get("id")
        if not pid:
            raise MetaAPIError("카루셀 부모 컨테이너 생성 실패", body=parent)
        return pid
