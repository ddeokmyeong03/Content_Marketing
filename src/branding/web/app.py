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
from ..config import get_settings, load_brand_config, resolve_settings
from ..config.settings import Settings
from ..diagnostics import Diagnostics
from ..db import (
    AccountMetricsRepository, BreakoutPatternRepository, CommentRepository,
    MetricsRepository, PlanRepository, PostRepository, SettingsStore, init_db,
)
from ..engagement import EngagementService
from ..insights import InsightsService
from ..models import PostStatus
from ..models.enums import CommentStatus, Platform
from ..publisher import PublishService
from ..services import generate_week
from .jobs import JobManager

TEMPLATE = Path(__file__).parent / "templates" / "dashboard.html"

# 웹에서 등록 가능한 설정 필드 (secret=마스킹 표시)
CONFIG_FIELDS = {
    "anthropic_api_key": True,
    "meta_access_token": True,
    "meta_app_secret": True,
    "meta_ig_user_id": False,
    "meta_threads_user_id": False,
    "meta_app_id": False,
    "notify_webhook_url": False,
}


def _mask(val: str) -> str:
    return f"{val[:4]}…{val[-3:]}" if len(val) > 9 else "****"


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)

    app = FastAPI(title="브랜딩 운영 대시보드", docs_url="/api/docs")
    jobs = JobManager()
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

    store = SettingsStore(settings.db_path)

    def _resolved() -> Settings:
        return resolve_settings(settings, store)

    # /api/config 저장 후에도 즉시 반영되도록 매 요청 해석

    @app.get("/api/config")
    def get_config() -> dict:
        saved = store.all()
        out = {}
        for name, secret in CONFIG_FIELDS.items():
            val = saved.get(name) or getattr(settings, name, "") or ""
            if not val:
                out[name] = {"set": False, "secret": secret}
            elif secret:
                out[name] = {"set": True, "secret": True, "masked": _mask(val)}
            else:
                out[name] = {"set": True, "secret": False, "value": val}
        return out

    @app.post("/api/config")
    def set_config(payload: dict) -> dict:
        changed = []
        for k, v in (payload or {}).items():
            if k in CONFIG_FIELDS and isinstance(v, str) and v.strip():
                store.set(k, v.strip())
                changed.append(k)
        return {"ok": True, "changed": changed}

    # --- 댓글 응대 (계정 활성화) ---

    @app.get("/api/comments")
    def list_comments(status: str = "drafted") -> list[dict]:
        repo = CommentRepository(settings.db_path)
        if status == "all":
            rows = repo.list_by_status(*list(CommentStatus))
        else:
            try:
                rows = repo.list_by_status(CommentStatus(status))
            except ValueError:
                raise HTTPException(400, f"알 수 없는 상태: {status}")
        return [
            {
                "id": c.id, "platform": c.platform.value, "author": c.author,
                "text": c.text, "draft_reply": c.draft_reply, "status": c.status.value,
                "post_id": c.post_id, "error": c.error,
            }
            for c in rows
        ]

    @app.post("/api/comments/{comment_id}/reply")
    def reply_comment(comment_id: int, payload: dict | None = None) -> dict:
        repo = CommentRepository(settings.db_path)
        comment = repo.get_by_id(comment_id)
        if not comment:
            raise HTTPException(404, "댓글을 찾을 수 없습니다.")
        message = (payload or {}).get("message") or None
        out = EngagementService(_resolved()).post_reply(comment, message=message)
        if not out.success:
            return {"ok": False, "error": out.error}
        return {"ok": True, "id": comment_id}

    @app.post("/api/comments/{comment_id}/ignore")
    def ignore_comment(comment_id: int) -> dict:
        repo = CommentRepository(settings.db_path)
        if not repo.get_by_id(comment_id):
            raise HTTPException(404, "댓글을 찾을 수 없습니다.")
        repo.mark_status(comment_id, CommentStatus.IGNORED)
        return {"ok": True, "id": comment_id}

    @app.post("/api/diagnostics")
    def diagnostics(autofix: bool = False) -> dict:
        """키·토큰·ID가 실제로 동작하는지 진단(+ 올바른 ID 자동 수정)."""
        checks = Diagnostics(_resolved(), store=store).run_all(autofix=autofix)
        return {
            "checks": [c.to_dict() for c in checks],
            "ok": all(c.status in ("ok", "skip") for c in checks),
        }

    # --- 수동 실행 액션 (백그라운드 잡: 수집 → 분석 → 생성 → 발행) ---

    def _body_collect(report):
        report("성과 수집 중…", 0.2)
        posts, accounts = InsightsService(_resolved()).sync_all()
        return {"message": f"게시물 {len(posts)}건 · 계정 {len(accounts)}건 수집"}

    def _body_analyze(report):
        rs = _resolved()
        if not rs.anthropic_api_key:
            raise RuntimeError("Anthropic API 키가 없습니다. 설정에서 등록하세요.")
        report("브레이크아웃 역설계 중…", 0.2)
        brand_cfg = load_brand_config(rs.brand_config_path)
        pats = BreakoutService(rs).deconstruct_new(
            brand_cfg, rs.anthropic_api_key, model=rs.anthropic_model, limit=5,
        )
        return {"message": f"승리 공식 {len(pats)}개 도출"}

    def _body_generate(report):
        rs = _resolved()
        if not rs.anthropic_api_key:
            raise RuntimeError("Anthropic API 키가 없습니다. 설정에서 등록하세요.")
        brand_cfg = load_brand_config(rs.brand_config_path)

        def progress(i, total, topic):
            report(f"[{i}/{total}] {topic[:24]} 생성 중…", 0.1 + 0.85 * i / max(total, 1))

        report("주간 계획 생성 중…", 0.05)
        res = generate_week(rs, brand_cfg, with_captions=True, progress=progress)
        return {"message": f"'{res.plan.theme_ko}' — {len(res.posts)}개 생성"}

    def _body_publish(report):
        report("예약 게시물 발행 중…", 0.3)
        outs = PublishService(_resolved()).run_pending()
        ok = sum(1 for o in outs if o.success)
        return {"message": f"발행 {ok}/{len(outs)}건"}

    def _body_engage(report):
        rs = _resolved()
        svc = EngagementService(rs)
        report("댓글 수집 중…", 0.2)
        new_comments = svc.sync_comments()
        drafted = []
        if new_comments and rs.anthropic_api_key:
            report(f"신규 {len(new_comments)}건 · 답글 초안 작성 중…", 0.6)
            brand_cfg = load_brand_config(rs.brand_config_path)
            drafted = svc.draft_replies(
                brand_cfg, rs.anthropic_api_key, model=rs.anthropic_model
            )
        return {"message": f"신규 댓글 {len(new_comments)}건 · 초안 {len(drafted)}건"}

    _ACTIONS = {
        "collect": _body_collect, "analyze": _body_analyze,
        "generate": _body_generate, "publish-due": _body_publish,
        "engage": _body_engage,
    }

    @app.post("/api/actions/{name}")
    def start_action(name: str) -> dict:
        body = _ACTIONS.get(name)
        if not body:
            raise HTTPException(404, f"알 수 없는 액션: {name}")
        job = jobs.start(name, body)
        return {"job_id": job.id, "status": job.status}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "잡을 찾을 수 없습니다.")
        return job.to_dict()

    @app.get("/api/growth-series")
    def growth_series(platform: str = "instagram", days: int = 90) -> dict:
        try:
            pf = Platform(platform)
        except ValueError:
            raise HTTPException(400, f"알 수 없는 플랫폼: {platform}")
        hist = accounts.history(pf, days=days)
        return {
            "platform": platform,
            "points": [
                {"t": m.fetched_at.isoformat(), "followers": m.followers_count, "reach": m.reach}
                for m in hist
            ],
        }

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
