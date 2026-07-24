"""운영 대시보드 — FastAPI 백엔드.

기존 서비스/리포지토리 계층을 그대로 재사용하는 얇은 API + 단일 페이지 UI.
검토 큐 승인/거절, BGI 분석(브레이크아웃·귀인·승리공식), 계정 성장을 한 화면에서.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from ..analysis import BreakoutService
from ..config import get_settings, load_brand_config
from ..config.settings import Settings
from ..db import (
    AccountMetricsRepository, BreakoutPatternRepository, MetricsRepository,
    PlanRepository, PostRepository, init_db,
)
from ..models import PostStatus
from ..models.enums import Platform

TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)

    app = FastAPI(title="브랜딩 운영 대시보드", docs_url="/api/docs")
    posts = PostRepository(settings.db_path)
    plans = PlanRepository(settings.db_path)
    accounts = AccountMetricsRepository(settings.db_path)
    patterns = BreakoutPatternRepository(settings.db_path)

    def _post_row(p) -> dict:
        return {
            "id": p.id,
            "platform": p.platform.value,
            "pillar": p.content_pillar.value,
            "topic": p.topic,
            "status": p.status.value,
            "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
            "engagement_score": p.content.engagement_score,
        }

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return TEMPLATE.read_text(encoding="utf-8")

    @app.get("/api/stats")
    def stats() -> dict:
        counts = {s.value: len(posts.list_by_status(s)) for s in PostStatus}
        acc = {}
        for pf in (Platform.INSTAGRAM, Platform.THREADS):
            latest = accounts.latest(pf)
            if latest:
                acc[pf.value] = {
                    "followers": latest.followers_count,
                    "growth_30d": accounts.follower_growth(pf, days=30),
                }
        plan = plans.get_latest()
        return {
            "counts": counts,
            "accounts": acc,
            "plan_theme": plan.theme_ko if plan else None,
        }

    @app.get("/api/queue")
    def queue(status: str = "draft") -> list[dict]:
        if status == "all":
            rows = [p for s in PostStatus for p in posts.list_by_status(s)]
        else:
            try:
                rows = posts.list_by_status(PostStatus(status))
            except ValueError:
                raise HTTPException(400, f"알 수 없는 상태: {status}")
        return [_post_row(p) for p in rows]

    @app.get("/api/posts/{post_id}")
    def post_detail(post_id: int) -> dict:
        p = posts.get_by_id(post_id)
        if not p:
            raise HTTPException(404, "게시물을 찾을 수 없습니다.")
        c = p.content
        return {
            **_post_row(p),
            "caption_ko": c.caption_ko,
            "caption_en": c.caption_en,
            "cta": c.cta,
            "chosen_hook": c.chosen_hook,
            "hook_variants": [h.model_dump() for h in c.hook_variants],
            "hashtags": c.hashtags_ko + c.hashtags_en,
            "engagement_notes": c.engagement_notes,
            "permalink": p.permalink,
        }

    def _transition(post_id: int, target: PostStatus, allowed: set[PostStatus]) -> dict:
        p = posts.get_by_id(post_id)
        if not p:
            raise HTTPException(404, "게시물을 찾을 수 없습니다.")
        if p.status not in allowed:
            raise HTTPException(409, f"'{p.status.value}' 상태에서는 변경할 수 없습니다.")
        posts.update_status(post_id, target)
        return {"id": post_id, "status": target.value}

    @app.post("/api/posts/{post_id}/approve")
    def approve(post_id: int) -> dict:
        return _transition(post_id, PostStatus.APPROVED, {PostStatus.DRAFT, PostStatus.REVIEW})

    @app.post("/api/posts/{post_id}/reject")
    def reject(post_id: int) -> dict:
        return _transition(post_id, PostStatus.REJECTED, {PostStatus.DRAFT, PostStatus.REVIEW})

    @app.get("/api/breakouts")
    def breakouts(weeks: int = 8) -> list[dict]:
        rows = BreakoutService(settings).analyze(weeks=weeks)
        return [
            {
                "post_id": r.post.id,
                "topic": r.post.topic,
                "platform": r.post.platform.value,
                "score": r.result.breakout_score,
                "is_breakout": r.result.is_breakout,
                "reasons": r.result.reasons,
            }
            for r in rows
        ]

    @app.get("/api/attribution")
    def attribution(days: int = 30) -> list[dict]:
        groups = BreakoutService(settings).attribute_growth(days=days)
        return [
            {
                "platform": g.platform.value,
                "follower_growth": g.follower_growth,
                "rows": [
                    {
                        "post_id": row.post.id,
                        "topic": row.post.topic,
                        "attributed": row.result.attributed_followers,
                        "method": row.result.method,
                        "direct_follows": row.result.direct_follows,
                    }
                    for row in g.rows
                ],
            }
            for g in groups
        ]

    @app.get("/api/patterns")
    def winning_patterns(limit: int = 20) -> list[dict]:
        return [
            {
                "id": p.id,
                "source": p.source,
                "source_ref": p.source_ref,
                "hook_type": p.hook_type,
                "psychology_levers": p.psychology_levers,
                "replicable_formula": p.replicable_formula,
                "spread_hypothesis": p.spread_hypothesis,
                "confidence": p.confidence,
            }
            for p in patterns.top(limit=limit)
        ]

    @app.get("/api/brand")
    def brand() -> dict:
        try:
            b = load_brand_config(settings.brand_config_path)
        except FileNotFoundError:
            return {}
        return {
            "niche": b.niche,
            "profession": b.persona.profession,
            "primary_metric": b.engagement.primary_metric,
            "intensity": b.psychology.intensity,
            "auto_approve": b.automation.auto_approve,
        }

    return app
