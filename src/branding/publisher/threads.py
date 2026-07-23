"""Threads 발행.

흐름: 컨테이너 생성(/threads) → 잠시 대기 → 발행(/threads_publish) → permalink 조회.
Threads 텍스트 게시물은 최대 500자입니다.
"""
from __future__ import annotations

import time

from ..models import Post
from .base import GraphHTTP, MetaAPIError, PublishResult

THREADS_TEXT_LIMIT = 500


def build_threads_text(post: Post) -> str:
    """Threads용 텍스트 구성 (본문 + CTA + 소수 해시태그, 500자 제한)."""
    parts = [post.content.caption_ko.strip()]
    if post.content.cta:
        parts.append(post.content.cta.strip())
    # Threads는 해시태그를 절제해서 사용 (최대 3개)
    tags = [t if t.startswith("#") else f"#{t}" for t in post.content.hashtags_ko[:3]]
    body = "\n\n".join(p for p in parts if p)
    if tags:
        body = f"{body}\n\n{' '.join(tags)}"
    if len(body) > THREADS_TEXT_LIMIT:
        body = body[: THREADS_TEXT_LIMIT - 1].rstrip() + "…"
    return body


class ThreadsPublisher:
    def __init__(
        self,
        access_token: str,
        user_id: str,
        base: str = "https://graph.threads.net",
        version: str = "v1.0",
        publish_delay_seconds: int = 5,
    ):
        if not access_token:
            raise MetaAPIError("Threads 액세스 토큰이 없습니다.")
        if not user_id:
            raise MetaAPIError("Threads 사용자 ID(META_THREADS_USER_ID)가 없습니다.")
        self._token = access_token
        self._user_id = user_id
        self._http = GraphHTTP(base, version)
        self._delay = publish_delay_seconds

    def publish(self, post: Post) -> PublishResult:
        text = build_threads_text(post)

        # 1) 컨테이너 생성
        created = self._http.post(
            f"{self._user_id}/threads",
            data={"media_type": "TEXT", "text": text, "access_token": self._token},
        )
        creation_id = created.get("id")
        if not creation_id:
            raise MetaAPIError("Threads 컨테이너 생성 응답에 id가 없습니다.", body=created)

        # 2) 처리 대기 (Threads 권장)
        if self._delay > 0:
            time.sleep(self._delay)

        # 3) 발행
        published = self._http.post(
            f"{self._user_id}/threads_publish",
            data={"creation_id": creation_id, "access_token": self._token},
        )
        media_id = published.get("id")
        if not media_id:
            raise MetaAPIError("Threads 발행 응답에 id가 없습니다.", body=published)

        # 4) permalink 조회 (실패해도 발행 자체는 성공)
        permalink = None
        try:
            info = self._http.get(
                str(media_id), params={"fields": "permalink", "access_token": self._token}
            )
            permalink = info.get("permalink")
        except MetaAPIError:
            permalink = None

        return PublishResult(meta_post_id=str(media_id), permalink=permalink, raw=published)
