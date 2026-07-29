"""타깃 발굴 — 공식 읽기 전용 API로 반응할 대상을 찾아 점수화한다.

⚠️ **실행은 사람이 한다.** 타 계정 팔로우·좋아요는 공식 Graph API에 엔드포인트가
없고, 비공식 자동화는 ToS 위반으로 계정 정지 위험이 있다. 여기서는 발굴·점수화까지만
하고, 운영자가 체크리스트를 보고 직접 반응한다.

쓰는 엔드포인트 (모두 공식·읽기 전용):
  - `/ig_hashtag_search`         해시태그명 → 해시태그 ID
  - `/{hashtag-id}/top_media`    해당 해시태그의 인기 게시물
  - `business_discovery`         공개 비즈니스/크리에이터 계정 정보
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config.brand_config import BrandConfig
from ..config.settings import Settings
from ..db import HashtagQuotaRepository, TargetRepository, TokenRepository
from ..models import TargetCandidate, TargetKind, TargetStatus
from ..models.enums import Platform
from ..publisher.base import GraphHTTP, MetaAPIError
from ..utils.time import now_utc, parse_dt
from .scoring import AccountSignal, PostSignal, score_account, score_posts

logger = logging.getLogger("branding.discovery")

# 해시태그 게시물 응답에는 소유자 username이 없다(플랫폼 정책).
# 그래서 게시물 후보는 permalink를 열어 사람이 확인하는 흐름이 된다.
MEDIA_FIELDS = "id,caption,media_type,permalink,like_count,comments_count,timestamp"
CAPTION_EXCERPT = 90


@dataclass
class DiscoveryReport:
    candidates: list[TargetCandidate]
    hashtags_queried: list[str]
    hashtags_skipped: list[str]     # 주간 한도 때문에 건너뛴 해시태그
    quota_remaining: int
    errors: list[str]


class DiscoveryService:
    def __init__(
        self,
        settings: Settings,
        brand: BrandConfig,
        target_repo: Optional[TargetRepository] = None,
        quota_repo: Optional[HashtagQuotaRepository] = None,
        token_repo: Optional[TokenRepository] = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.brand = brand
        self.cfg = brand.discovery
        self.targets = target_repo or TargetRepository(settings.db_path)
        self.quota = quota_repo or HashtagQuotaRepository(
            settings.db_path, limit=self.cfg.max_hashtag_queries_per_week
        )
        self.tokens = token_repo or TokenRepository(settings.db_path)
        self._transport = transport

    # --- 하부 ---

    def _http(self) -> GraphHTTP:
        return GraphHTTP(
            self.settings.meta_graph_base,
            self.settings.meta_graph_version,
            transport=self._transport,
        )

    def _token(self) -> str:
        return self.tokens.get_token(Platform.INSTAGRAM.value) or self.settings.meta_access_token

    def _require_config(self) -> tuple[str, str]:
        user_id = self.settings.meta_ig_user_id
        token = self._token()
        if not user_id:
            raise MetaAPIError("META_IG_USER_ID 가 필요합니다 (해시태그 검색은 IG 계정 기준).")
        if not token:
            raise MetaAPIError("Instagram 액세스 토큰이 없습니다.")
        return user_id, token

    def hashtags(self) -> list[str]:
        """탐색할 해시태그. 설정이 없으면 브랜드 태그를 쓴다."""
        tags = [t.lstrip("#").strip() for t in self.cfg.hashtags if t.strip()]
        if tags:
            return tags
        return [t.lstrip("#").strip() for t in self.brand.hashtag_strategy.instagram.brand_tags]

    # --- 해시태그 발굴 ---

    def search_hashtag_id(self, name: str) -> Optional[str]:
        user_id, token = self._require_config()
        payload = self._http().get(
            "ig_hashtag_search",
            params={"user_id": user_id, "q": name.lstrip("#"), "access_token": token},
        )
        data = payload.get("data") or []
        return str(data[0]["id"]) if data and data[0].get("id") else None

    def fetch_hashtag_media(self, hashtag_id: str, limit: int) -> list[dict]:
        user_id, token = self._require_config()
        payload = self._http().get(
            f"{hashtag_id}/top_media",
            params={
                "user_id": user_id,
                "fields": MEDIA_FIELDS,
                "limit": limit,
                "access_token": token,
            },
        )
        return payload.get("data") or []

    def _media_to_candidates(self, media: list[dict], hashtag: str) -> list[TargetCandidate]:
        now = now_utc()
        signals = []
        for m in media:
            ts = parse_dt(m.get("timestamp")) if m.get("timestamp") else None
            age = (now - ts).total_seconds() / 86400 if ts else 999.0
            signals.append(
                PostSignal(
                    external_id=str(m.get("id")),
                    like_count=int(m.get("like_count") or 0),
                    comments_count=int(m.get("comments_count") or 0),
                    age_days=age,
                )
            )
        scored = score_posts(signals)

        out: list[TargetCandidate] = []
        for m in media:
            ext = str(m.get("id"))
            s = scored.get(ext)
            if s is None:
                continue
            likes = int(m.get("like_count") or 0)
            comments = int(m.get("comments_count") or 0)
            out.append(
                TargetCandidate(
                    platform=Platform.INSTAGRAM,
                    kind=TargetKind.POST,
                    external_id=ext,
                    permalink=m.get("permalink"),
                    source=f"#{hashtag}",
                    caption_excerpt=(m.get("caption") or "")[:CAPTION_EXCERPT],
                    like_count=likes,
                    comments_count=comments,
                    score=s.score,
                    reasons=s.reasons,
                )
            )
        return out

    # --- 계정 발굴 ---

    def fetch_business_account(self, username: str) -> Optional[dict]:
        """공개 비즈니스/크리에이터 계정 정보 (business_discovery)."""
        user_id, token = self._require_config()
        fields = (
            f"business_discovery.username({username})"
            "{username,followers_count,media_count,"
            "media.limit(9){like_count,comments_count,permalink}}"
        )
        payload = self._http().get(
            user_id, params={"fields": fields, "access_token": token}
        )
        return payload.get("business_discovery")

    def _account_to_candidate(self, data: dict) -> TargetCandidate:
        media = (data.get("media") or {}).get("data") or []
        likes = [int(m.get("like_count") or 0) for m in media]
        comments = [int(m.get("comments_count") or 0) for m in media]
        avg_likes = sum(likes) / len(likes) if likes else 0.0
        avg_comments = sum(comments) / len(comments) if comments else 0.0
        followers = int(data.get("followers_count") or 0)
        username = data.get("username") or ""

        scored = score_account(
            AccountSignal(username, followers, avg_likes, avg_comments),
            self.cfg.min_followers,
            self.cfg.max_followers,
        )
        return TargetCandidate(
            platform=Platform.INSTAGRAM,
            kind=TargetKind.ACCOUNT,
            external_id=username,
            permalink=f"https://www.instagram.com/{username}/" if username else None,
            username=username,
            source="business_discovery",
            followers_count=followers,
            like_count=int(avg_likes),
            comments_count=int(avg_comments),
            engagement_rate=round((avg_likes + avg_comments) / followers, 4) if followers else 0.0,
            score=scored.score,
            reasons=scored.reasons,
        )

    # --- 오케스트레이션 ---

    def discover(self, limit_per_hashtag: int = 25) -> DiscoveryReport:
        """해시태그·시드 계정에서 후보를 찾아 저장한다."""
        queried: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        saved: list[TargetCandidate] = []

        for tag in self.hashtags():
            if not self.quota.allows(tag):
                skipped.append(tag)
                continue
            try:
                hashtag_id = self.search_hashtag_id(tag)
                self.quota.record(tag)   # 조회를 시도한 시점에 한도가 소모된다
                queried.append(tag)
                if not hashtag_id:
                    errors.append(f"#{tag}: 해시태그를 찾지 못했습니다.")
                    continue
                media = self.fetch_hashtag_media(hashtag_id, limit_per_hashtag)
                for candidate in self._media_to_candidates(media, tag):
                    saved.append(self.targets.upsert(candidate))
            except MetaAPIError as e:
                errors.append(f"#{tag}: {e}")

        for username in self.cfg.seed_accounts:
            try:
                data = self.fetch_business_account(username.lstrip("@"))
                if not data:
                    errors.append(f"@{username}: 공개 비즈니스 계정이 아니거나 조회 불가")
                    continue
                saved.append(self.targets.upsert(self._account_to_candidate(data)))
            except MetaAPIError as e:
                errors.append(f"@{username}: {e}")

        if skipped:
            logger.warning(
                "주간 해시태그 한도로 %d개를 건너뛰었습니다 (남은 여유 %d): %s",
                len(skipped), self.quota.remaining(), ", ".join(skipped),
            )
        return DiscoveryReport(
            candidates=sorted(saved, key=lambda c: c.score, reverse=True),
            hashtags_queried=queried,
            hashtags_skipped=skipped,
            quota_remaining=self.quota.remaining(),
            errors=errors,
        )

    def checklist(self, size: Optional[int] = None) -> list[TargetCandidate]:
        """오늘 실행할 목록 — 점수 상위 N건."""
        return self.targets.list_by_status(
            TargetStatus.NEW, limit=size or self.cfg.daily_checklist
        )
