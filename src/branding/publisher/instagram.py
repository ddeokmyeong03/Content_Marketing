"""Instagram 발행.

단일 이미지: /media(image_url, caption) → /media_publish
카루셀: 각 이미지 자식 컨테이너 생성 → CAROUSEL 부모 컨테이너 → /media_publish

⚠️ Instagram Graph API는 '공개적으로 접근 가능한 이미지 URL'을 요구합니다.
   post.content.image_urls 가 비어 있으면 발행할 수 없습니다(이미지 생성·호스팅 필요).
"""
from __future__ import annotations

import time

from ..models import Post
from ..models.enums import MediaType
from .base import GraphHTTP, MetaAPIError, PublishResult

CAROUSEL_MAX = 10


class InstagramPublisher:
    def __init__(
        self,
        access_token: str,
        user_id: str,
        base: str = "https://graph.facebook.com",
        version: str = "v21.0",
        publish_delay_seconds: int = 5,
    ):
        if not access_token:
            raise MetaAPIError("Instagram 액세스 토큰이 없습니다.")
        if not user_id:
            raise MetaAPIError("Instagram 사용자 ID(META_IG_USER_ID)가 없습니다.")
        self._token = access_token
        self._user_id = user_id
        self._http = GraphHTTP(base, version)
        self._delay = publish_delay_seconds

    def publish(self, post: Post) -> PublishResult:
        image_urls = post.content.image_urls
        if not image_urls:
            raise MetaAPIError(
                "Instagram 발행에는 공개 이미지 URL이 필요합니다. "
                "content.image_urls 가 비어 있습니다 (이미지 생성·호스팅 미구현)."
            )
        caption = post.full_caption_ko()

        if post.media_type == MediaType.CAROUSEL and len(image_urls) > 1:
            container_id = self._create_carousel(image_urls[:CAROUSEL_MAX], caption)
        else:
            container_id = self._create_single(image_urls[0], caption)

        if self._delay > 0:
            time.sleep(self._delay)

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
