import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import sqlite3

from ..models import (
    Post, ContentPlan, ContentPlanTopic, PostStatus, PostContent, PostMetric, AccountMetric,
    BreakoutPattern,
)
from ..models.enums import Platform as _Platform
from ..models.enums import Platform, MediaType, ContentPillar
from ..utils.time import now_utc, parse_dt
from .database import get_connection


def _row_to_post(row: sqlite3.Row) -> Post:
    # content_json 은 PostContent.model_dump_json() 결과이므로 그대로 역직렬화
    content = PostContent.model_validate_json(row["content_json"])
    return Post(
        id=row["id"],
        plan_id=row["plan_id"],
        platform=Platform(row["platform"]),
        media_type=MediaType(row["media_type"]),
        content_pillar=ContentPillar(row["content_pillar"]),
        topic=row["topic"],
        content=content,
        status=PostStatus(row["status"]),
        scheduled_at=parse_dt(row["scheduled_at"]),
        published_at=parse_dt(row["published_at"]),
        meta_post_id=row["meta_post_id"],
        permalink=row["permalink"],
        created_at=parse_dt(row["created_at"]),
        week_number=row["week_number"],
    )


class PostRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save(self, post: Post) -> Post:
        content_json = post.content.model_dump_json()
        conn = self._conn()
        if post.id is None:
            cur = conn.execute(
                """INSERT INTO posts
                   (plan_id, platform, media_type, content_pillar, topic,
                    content_json, status, scheduled_at, published_at, meta_post_id,
                    permalink, week_number, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post.plan_id,
                    post.platform.value,
                    post.media_type.value,
                    post.content_pillar.value,
                    post.topic,
                    content_json,
                    post.status.value,
                    post.scheduled_at.isoformat() if post.scheduled_at else None,
                    post.published_at.isoformat() if post.published_at else None,
                    post.meta_post_id,
                    post.permalink,
                    post.week_number,
                    post.created_at.isoformat(),
                ),
            )
            post = post.model_copy(update={"id": cur.lastrowid})
        else:
            conn.execute(
                """UPDATE posts SET
                   status=?, scheduled_at=?, published_at=?, meta_post_id=?,
                   permalink=?, content_json=?
                   WHERE id=?""",
                (
                    post.status.value,
                    post.scheduled_at.isoformat() if post.scheduled_at else None,
                    post.published_at.isoformat() if post.published_at else None,
                    post.meta_post_id,
                    post.permalink,
                    content_json,
                    post.id,
                ),
            )
        conn.commit()
        conn.close()
        return post

    def get_by_id(self, post_id: int) -> Optional[Post]:
        conn = self._conn()
        row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        conn.close()
        return _row_to_post(row) if row else None

    def list_by_status(self, status: PostStatus) -> list[Post]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM posts WHERE status=? ORDER BY scheduled_at ASC, created_at ASC",
            (status.value,),
        ).fetchall()
        conn.close()
        return [_row_to_post(r) for r in rows]

    def list_pending_publish(self) -> list[Post]:
        """발행 시간이 지난 APPROVED 상태 게시물 조회 (UTC 기준)"""
        now = now_utc().isoformat()
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE status='approved' AND (scheduled_at IS NULL OR scheduled_at <= ?)
               ORDER BY scheduled_at ASC""",
            (now,),
        ).fetchall()
        conn.close()
        return [_row_to_post(r) for r in rows]

    def recent_topics(self, weeks: int = 4) -> list[str]:
        """최근 N주간 생성된 포스트 주제 목록 (중복 방지용)"""
        since = (now_utc() - timedelta(weeks=weeks)).isoformat()
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT topic FROM posts WHERE created_at >= ? ORDER BY created_at DESC",
            (since,),
        ).fetchall()
        conn.close()
        return [r["topic"] for r in rows]

    def update_status(self, post_id: int, status: PostStatus) -> None:
        conn = self._conn()
        conn.execute("UPDATE posts SET status=? WHERE id=?", (status.value, post_id))
        conn.commit()
        conn.close()

    def log_publish_attempt(
        self, post_id: int, success: bool, error_msg: Optional[str] = None, response: Optional[dict] = None
    ) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO publish_log (post_id, attempt_at, success, error_msg, response_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                post_id,
                now_utc().isoformat(),
                1 if success else 0,
                error_msg,
                json.dumps(response) if response else None,
            ),
        )
        conn.commit()
        conn.close()


class PlanRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save(self, plan: ContentPlan) -> ContentPlan:
        topics_json = json.dumps([t.model_dump(mode="json") for t in plan.topics])
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO content_plans
               (week_start, week_end, theme, theme_ko, topics_json, generated_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                plan.week_start.isoformat(),
                plan.week_end.isoformat(),
                plan.theme,
                plan.theme_ko,
                topics_json,
                plan.generated_at.isoformat(),
                plan.status,
            ),
        )
        plan = plan.model_copy(update={"id": cur.lastrowid})
        conn.commit()
        conn.close()
        return plan

    def get_latest(self) -> Optional[ContentPlan]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM content_plans ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_plan(row)

    def _row_to_plan(self, row: sqlite3.Row) -> ContentPlan:
        topics_data = json.loads(row["topics_json"])
        topics = [ContentPlanTopic(**t) for t in topics_data]
        return ContentPlan(
            id=row["id"],
            week_start=date.fromisoformat(row["week_start"]),
            week_end=date.fromisoformat(row["week_end"]),
            theme=row["theme"],
            theme_ko=row["theme_ko"],
            topics=topics,
            generated_at=parse_dt(row["generated_at"]),
            status=row["status"],
        )


class SettingsStore:
    """웹에서 등록한 런타임 설정(키·ID) 저장 (key-value). .env보다 우선 적용."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def set(self, key: str, value: str) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO settings_store (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, now_utc().isoformat()),
        )
        conn.commit()
        conn.close()

    def get(self, key: str) -> Optional[str]:
        conn = self._conn()
        row = conn.execute("SELECT value FROM settings_store WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else None

    def all(self) -> dict[str, str]:
        conn = self._conn()
        rows = conn.execute("SELECT key, value FROM settings_store").fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows if r["value"]}


class TokenRepository:
    """Meta/Threads 액세스 토큰 영속화. 토큰 자동 갱신 시 사용."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def upsert(
        self,
        platform: str,
        access_token: str,
        token_type: str = "long_lived",
        expires_at: Optional[datetime] = None,
    ) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO token_store (platform, access_token, token_type, expires_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(platform) DO UPDATE SET
                   access_token=excluded.access_token,
                   token_type=excluded.token_type,
                   expires_at=excluded.expires_at,
                   updated_at=excluded.updated_at""",
            (
                platform,
                access_token,
                token_type,
                expires_at.isoformat() if expires_at else None,
                now_utc().isoformat(),
            ),
        )
        conn.commit()
        conn.close()

    def get_token(self, platform: str) -> Optional[str]:
        conn = self._conn()
        row = conn.execute(
            "SELECT access_token FROM token_store WHERE platform=?", (platform,)
        ).fetchone()
        conn.close()
        return row["access_token"] if row else None

    def get_expiry(self, platform: str) -> Optional[datetime]:
        conn = self._conn()
        row = conn.execute(
            "SELECT expires_at FROM token_store WHERE platform=?", (platform,)
        ).fetchone()
        conn.close()
        return parse_dt(row["expires_at"]) if row and row["expires_at"] else None


_METRIC_COLUMNS = {"engagement_rate", "saved", "likes", "comments", "shares", "reach", "views"}
# config의 primary_metric 값 → post_metrics 컬럼 매핑
_METRIC_ALIAS = {"saves": "saved", "follows": "engagement_rate"}


class MetricsRepository:
    """발행 성과(post_metrics) 저장 및 상위 성과 조회 — 피드백 루프의 저장소."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save_snapshot(self, metric: PostMetric) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO post_metrics
               (post_id, platform, fetched_at, likes, comments, shares, saved,
                reach, views, profile_visits, follows, total_interactions,
                engagement_rate, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metric.post_id,
                metric.platform.value,
                metric.fetched_at.isoformat(),
                metric.likes,
                metric.comments,
                metric.shares,
                metric.saved,
                metric.reach,
                metric.views,
                metric.profile_visits,
                metric.follows,
                metric.total_interactions,
                metric.engagement_rate,
                json.dumps(metric.raw) if metric.raw else None,
            ),
        )
        conn.commit()
        conn.close()

    def latest_for_post(self, post_id: int) -> Optional[PostMetric]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM post_metrics WHERE post_id=? ORDER BY fetched_at DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return PostMetric(
            post_id=row["post_id"],
            platform=_Platform(row["platform"]),
            likes=row["likes"],
            comments=row["comments"],
            shares=row["shares"],
            saved=row["saved"],
            reach=row["reach"],
            views=row["views"],
            profile_visits=row["profile_visits"],
            follows=row["follows"],
            total_interactions=row["total_interactions"],
            engagement_rate=row["engagement_rate"],
            fetched_at=parse_dt(row["fetched_at"]),
            raw=json.loads(row["raw_json"]) if row["raw_json"] else {},
        )

    def top_performers(
        self, weeks: int = 8, limit: int = 10, order_by: str = "engagement_rate"
    ) -> list[dict]:
        """최근 N주 발행분 중, 각 게시물의 최신 스냅샷 기준 상위 성과.

        기획 프롬프트에 '무엇이 먹혔는지' 재주입하기 위한 학습 데이터.
        반환: [{topic, pillar, chosen_hook, engagement_rate, value}]
        """
        order_by = _METRIC_ALIAS.get(order_by, order_by)
        order_col = order_by if order_by in _METRIC_COLUMNS else "engagement_rate"
        since = (now_utc() - timedelta(weeks=weeks)).isoformat()
        conn = self._conn()
        rows = conn.execute(
            f"""SELECT p.topic AS topic, p.content_pillar AS pillar,
                       p.content_json AS content_json, m.engagement_rate AS er,
                       m.{order_col} AS val
                FROM post_metrics m
                JOIN posts p ON p.id = m.post_id
                JOIN (SELECT post_id, MAX(fetched_at) AS mx
                      FROM post_metrics GROUP BY post_id) latest
                  ON latest.post_id = m.post_id AND latest.mx = m.fetched_at
                WHERE m.fetched_at >= ?
                ORDER BY m.{order_col} DESC
                LIMIT ?""",
            (since, limit),
        ).fetchall()
        conn.close()

        results = []
        for r in rows:
            chosen_hook = None
            try:
                chosen_hook = json.loads(r["content_json"]).get("chosen_hook")
            except (ValueError, TypeError):
                pass
            results.append(
                {
                    "topic": r["topic"],
                    "pillar": r["pillar"],
                    "chosen_hook": chosen_hook,
                    "engagement_rate": r["er"],
                    "value": r["val"],
                }
            )
        return results


class AccountMetricsRepository:
    """계정 단위 성과(account_metrics) 스냅샷 저장 및 시계열 조회."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save_snapshot(self, metric: AccountMetric) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO account_metrics
               (platform, fetched_at, followers_count, reach, profile_views, views, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                metric.platform.value,
                metric.fetched_at.isoformat(),
                metric.followers_count,
                metric.reach,
                metric.profile_views,
                metric.views,
                json.dumps(metric.raw) if metric.raw else None,
            ),
        )
        conn.commit()
        conn.close()

    def _row_to_metric(self, row: sqlite3.Row) -> AccountMetric:
        return AccountMetric(
            platform=_Platform(row["platform"]),
            followers_count=row["followers_count"],
            reach=row["reach"],
            profile_views=row["profile_views"],
            views=row["views"],
            fetched_at=parse_dt(row["fetched_at"]),
            raw=json.loads(row["raw_json"]) if row["raw_json"] else {},
        )

    def latest(self, platform: _Platform) -> Optional[AccountMetric]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM account_metrics WHERE platform=? ORDER BY fetched_at DESC LIMIT 1",
            (platform.value,),
        ).fetchone()
        conn.close()
        return self._row_to_metric(row) if row else None

    def history(self, platform: _Platform, days: int = 30) -> list[AccountMetric]:
        """최근 N일 스냅샷 (오래된 → 최신). 팔로워 델타 계산용."""
        since = (now_utc() - timedelta(days=days)).isoformat()
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM account_metrics
               WHERE platform=? AND fetched_at >= ?
               ORDER BY fetched_at ASC""",
            (platform.value, since),
        ).fetchall()
        conn.close()
        return [self._row_to_metric(r) for r in rows]

    def follower_growth(self, platform: _Platform, days: int = 30) -> Optional[int]:
        """기간 내 팔로워 순증가 (최신 - 최초)."""
        hist = self.history(platform, days)
        if len(hist) < 2:
            return None
        return hist[-1].followers_count - hist[0].followers_count

    def followers_at(self, platform: _Platform, when: datetime) -> Optional[int]:
        """주어진 시점의 팔로워 수 (그 시점 이전 최신 스냅샷, 없으면 이후 최초)."""
        conn = self._conn()
        row = conn.execute(
            """SELECT followers_count FROM account_metrics
               WHERE platform=? AND fetched_at <= ?
               ORDER BY fetched_at DESC LIMIT 1""",
            (platform.value, when.isoformat()),
        ).fetchone()
        if row is None:
            row = conn.execute(
                """SELECT followers_count FROM account_metrics
                   WHERE platform=? ORDER BY fetched_at ASC LIMIT 1""",
                (platform.value,),
            ).fetchone()
        conn.close()
        return row["followers_count"] if row else None


class BreakoutPatternRepository:
    """AI 역설계된 '승리 공식'(breakout_patterns) 저장·조회."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def save(self, pattern: BreakoutPattern) -> BreakoutPattern:
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO breakout_patterns
               (post_id, detected_at, breakout_score, hook_type, psychology_levers,
                format, topic_angle, structure_notes, emotional_trigger,
                spread_hypothesis, replicable_formula, confidence, metrics_snapshot,
                source, source_ref)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pattern.post_id,
                pattern.detected_at.isoformat(),
                pattern.breakout_score,
                pattern.hook_type,
                json.dumps(pattern.psychology_levers, ensure_ascii=False),
                pattern.format,
                pattern.topic_angle,
                pattern.structure_notes,
                pattern.emotional_trigger,
                pattern.spread_hypothesis,
                pattern.replicable_formula,
                pattern.confidence,
                json.dumps(pattern.metrics_snapshot, ensure_ascii=False),
                pattern.source,
                pattern.source_ref,
            ),
        )
        conn.commit()
        result = pattern.model_copy(update={"id": cur.lastrowid})
        conn.close()
        return result

    def _row(self, row: sqlite3.Row) -> BreakoutPattern:
        keys = row.keys()
        return BreakoutPattern(
            id=row["id"],
            post_id=row["post_id"],
            source=(row["source"] if "source" in keys and row["source"] else "internal"),
            source_ref=(row["source_ref"] if "source_ref" in keys else None),
            breakout_score=row["breakout_score"],
            hook_type=row["hook_type"] or "",
            psychology_levers=json.loads(row["psychology_levers"]) if row["psychology_levers"] else [],
            format=row["format"] or "",
            topic_angle=row["topic_angle"] or "",
            structure_notes=row["structure_notes"] or "",
            emotional_trigger=row["emotional_trigger"] or "",
            spread_hypothesis=row["spread_hypothesis"] or "",
            replicable_formula=row["replicable_formula"] or "",
            confidence=row["confidence"] or 0,
            metrics_snapshot=json.loads(row["metrics_snapshot"]) if row["metrics_snapshot"] else {},
            detected_at=parse_dt(row["detected_at"]),
        )

    def exists_for_post(self, post_id: int) -> bool:
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM breakout_patterns WHERE post_id=? LIMIT 1", (post_id,)
        ).fetchone()
        conn.close()
        return row is not None

    def top(self, limit: int = 10) -> list[BreakoutPattern]:
        """신뢰도·브레이크아웃 점수 상위 승리 공식 (엔진 재주입용)."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM breakout_patterns
               ORDER BY confidence DESC, breakout_score DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [self._row(r) for r in rows]
