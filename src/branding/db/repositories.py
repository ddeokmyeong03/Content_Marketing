import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import sqlite3

from ..models import (
    Post, ContentPlan, ContentPlanTopic, PostStatus, PostContent, PostMetric, AccountMetric,
    BreakoutPattern, Comment, CommentStatus, TargetCandidate, TargetKind, TargetStatus,
)
from ..models.enums import Platform as _Platform
from ..models.enums import Platform, MediaType, ContentPillar
from ..security import SecretBox, is_encrypted
from ..utils.time import now_utc, parse_dt
from .database import get_connection


def _row_value(row: sqlite3.Row, key: str, default=None):
    """마이그레이션 전 DB에서도 안전하게 컬럼을 읽는다(없으면 기본값)."""
    return row[key] if key in row.keys() else default


def _row_to_post(row: sqlite3.Row) -> Post:
    # content_json 은 PostContent.model_dump_json() 결과이므로 그대로 역직렬화
    content = PostContent.model_validate_json(row["content_json"])
    return Post(
        publish_attempts=_row_value(row, "publish_attempts", 0) or 0,
        next_retry_at=parse_dt(_row_value(row, "next_retry_at")),
        last_error=_row_value(row, "last_error"),
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
        """발행 대상 조회 (UTC 기준).

        두 종류를 함께 집어간다:
          1. 예약 시각이 지난 APPROVED 게시물 (정상 경로)
          2. 일시 장애로 FAILED 되었고 재시도 시각이 된 게시물 (복구 경로)
        재시도 예정이 없는(next_retry_at IS NULL) 영구 실패 건은 제외된다.
        """
        now = now_utc().isoformat()
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM posts
               WHERE (status='approved' AND (scheduled_at IS NULL OR scheduled_at <= ?))
                  OR (status='failed' AND next_retry_at IS NOT NULL AND next_retry_at <= ?)
               ORDER BY scheduled_at ASC""",
            (now, now),
        ).fetchall()
        conn.close()
        return [_row_to_post(r) for r in rows]

    def mark_publish_failure(
        self,
        post_id: int,
        error_msg: str,
        attempts: int,
        next_retry_at: Optional[datetime],
    ) -> None:
        """발행 실패 기록. `next_retry_at`이 None이면 영구 실패(더 이상 집어가지 않음)."""
        conn = self._conn()
        conn.execute(
            """UPDATE posts
               SET status=?, publish_attempts=?, next_retry_at=?, last_error=?
               WHERE id=?""",
            (
                PostStatus.FAILED.value,
                attempts,
                next_retry_at.isoformat() if next_retry_at else None,
                error_msg,
                post_id,
            ),
        )
        conn.commit()
        conn.close()

    def clear_publish_retry(self, post_id: int) -> None:
        """발행 성공 시 재시도 상태 초기화."""
        conn = self._conn()
        conn.execute(
            "UPDATE posts SET publish_attempts=0, next_retry_at=NULL, last_error=NULL WHERE id=?",
            (post_id,),
        )
        conn.commit()
        conn.close()

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
    """웹에서 등록한 런타임 설정(키·ID) 저장 (key-value). .env보다 우선 적용.

    값은 저장 시점에 암호화된다(`security.SecretBox`). 기존 평문 값도 그대로 읽히며
    다음 쓰기에서 암호화된다.
    """

    def __init__(self, db_path: str | Path, box: Optional["SecretBox"] = None):
        self.db_path = db_path
        self._box = box or SecretBox.for_db_path(db_path)

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def set(self, key: str, value: str) -> None:
        conn = self._conn()
        conn.execute(
            """INSERT INTO settings_store (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, self._box.encrypt(value), now_utc().isoformat()),
        )
        conn.commit()
        conn.close()

    def get(self, key: str) -> Optional[str]:
        conn = self._conn()
        row = conn.execute(
            "SELECT value FROM settings_store WHERE key=?", (key,)
        ).fetchone()
        conn.close()
        return self._box.decrypt(row["value"]) if row else None

    def all(self) -> dict[str, str]:
        conn = self._conn()
        rows = conn.execute("SELECT key, value FROM settings_store").fetchall()
        conn.close()
        return {r["key"]: self._box.decrypt(r["value"]) for r in rows if r["value"]}

    def raw_all(self) -> dict[str, str]:
        """복호화하지 않은 원본 값 — 마이그레이션 진단용."""
        conn = self._conn()
        rows = conn.execute("SELECT key, value FROM settings_store").fetchall()
        conn.close()
        return {r["key"]: r["value"] for r in rows if r["value"]}

    def reencrypt_all(self) -> list[str]:
        """평문으로 저장된 값을 암호화해 다시 쓴다. 바뀐 키 목록을 돌려준다."""
        changed = []
        for key, value in self.raw_all().items():
            if not is_encrypted(value):
                self.set(key, value)
                changed.append(key)
        return changed


class TokenRepository:
    """Meta/Threads 액세스 토큰 영속화. 토큰 자동 갱신 시 사용.

    토큰은 저장 시점에 암호화된다(기존 평문 값도 그대로 읽힘).
    """

    def __init__(self, db_path: str | Path, box: Optional["SecretBox"] = None):
        self.db_path = db_path
        self._box = box or SecretBox.for_db_path(db_path)

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
                self._box.encrypt(access_token),
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
        return self._box.decrypt(row["access_token"]) if row else None

    def reencrypt_all(self) -> list[str]:
        """평문으로 저장된 토큰을 암호화해 다시 쓴다. 바뀐 플랫폼 목록을 돌려준다."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT platform, access_token, token_type, expires_at FROM token_store"
        ).fetchall()
        conn.close()
        changed = []
        for r in rows:
            if r["access_token"] and not is_encrypted(r["access_token"]):
                self.upsert(
                    r["platform"], r["access_token"], r["token_type"],
                    parse_dt(r["expires_at"]) if r["expires_at"] else None,
                )
                changed.append(r["platform"])
        return changed

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


class CommentRepository:
    """댓글/답글 저장·조회. external_id 기준 중복 수집 방지."""

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def upsert(self, comment: Comment) -> Comment:
        """새 댓글만 삽입(이미 있으면 기존 레코드 유지 — 사람이 손댄 상태 보호)."""
        conn = self._conn()
        cur = conn.execute(
            """INSERT INTO comments
               (post_id, platform, external_id, author, text, status, draft_reply,
                replied_at, reply_external_id, error, commented_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(external_id) DO NOTHING""",
            (
                comment.post_id, comment.platform.value, comment.external_id,
                comment.author, comment.text, comment.status.value, comment.draft_reply,
                comment.replied_at.isoformat() if comment.replied_at else None,
                comment.reply_external_id, comment.error,
                comment.commented_at.isoformat() if comment.commented_at else None,
                comment.fetched_at.isoformat(),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid if cur.rowcount else None
        conn.close()
        return comment.model_copy(update={"id": new_id}) if new_id else comment

    def _row(self, row: sqlite3.Row) -> Comment:
        return Comment(
            id=row["id"],
            post_id=row["post_id"],
            platform=_Platform(row["platform"]),
            external_id=row["external_id"],
            author=row["author"] or "",
            text=row["text"] or "",
            status=CommentStatus(row["status"]),
            draft_reply=row["draft_reply"],
            replied_at=parse_dt(row["replied_at"]),
            reply_external_id=row["reply_external_id"],
            error=row["error"],
            commented_at=parse_dt(row["commented_at"]),
            fetched_at=parse_dt(row["fetched_at"]),
        )

    def get_by_id(self, comment_id: int) -> Optional[Comment]:
        conn = self._conn()
        row = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
        conn.close()
        return self._row(row) if row else None

    def exists(self, external_id: str) -> bool:
        conn = self._conn()
        row = conn.execute(
            "SELECT 1 FROM comments WHERE external_id=? LIMIT 1", (external_id,)
        ).fetchone()
        conn.close()
        return row is not None

    def list_by_status(self, *statuses: CommentStatus) -> list[Comment]:
        if not statuses:
            statuses = (CommentStatus.NEW,)
        marks = ",".join("?" for _ in statuses)
        conn = self._conn()
        rows = conn.execute(
            f"""SELECT * FROM comments WHERE status IN ({marks})
                ORDER BY commented_at DESC, id DESC""",
            tuple(s.value for s in statuses),
        ).fetchall()
        conn.close()
        return [self._row(r) for r in rows]

    def save_draft(self, comment_id: int, draft: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE comments SET draft_reply=?, status=? WHERE id=?",
            (draft, CommentStatus.DRAFTED.value, comment_id),
        )
        conn.commit()
        conn.close()

    def mark_replied(self, comment_id: int, reply_external_id: Optional[str]) -> None:
        conn = self._conn()
        conn.execute(
            """UPDATE comments SET status=?, replied_at=?, reply_external_id=?, error=NULL
               WHERE id=?""",
            (CommentStatus.REPLIED.value, now_utc().isoformat(), reply_external_id, comment_id),
        )
        conn.commit()
        conn.close()

    def mark_status(self, comment_id: int, status: CommentStatus,
                    error: Optional[str] = None) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE comments SET status=?, error=? WHERE id=?",
            (status.value, error, comment_id),
        )
        conn.commit()
        conn.close()


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


class TargetRepository:
    """발굴된 참여 대상 저장.

    같은 게시물·계정을 매일 다시 발굴해도 중복이 쌓이지 않도록
    (platform, kind, external_id)로 upsert 하며, 사람이 이미 처리한 항목의
    상태는 덮어쓰지 않는다.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def _row(self, row: sqlite3.Row) -> TargetCandidate:
        return TargetCandidate(
            id=row["id"],
            platform=Platform(row["platform"]),
            kind=TargetKind(row["kind"]),
            external_id=row["external_id"],
            permalink=row["permalink"],
            username=row["username"],
            source=row["source"] or "",
            caption_excerpt=row["caption_excerpt"] or "",
            followers_count=row["followers_count"] or 0,
            like_count=row["like_count"] or 0,
            comments_count=row["comments_count"] or 0,
            engagement_rate=row["engagement_rate"] or 0.0,
            score=row["score"] or 0.0,
            reasons=json.loads(row["reasons_json"]) if row["reasons_json"] else [],
            status=TargetStatus(row["status"]),
            note=row["note"] or "",
            discovered_at=parse_dt(row["discovered_at"]),
            actioned_at=parse_dt(row["actioned_at"]),
        )

    def upsert(self, c: TargetCandidate) -> TargetCandidate:
        """새 후보는 추가하고, 이미 있으면 지표·점수만 갱신한다.

        status/note/actioned_at 은 사람의 판단이므로 덮어쓰지 않는다.
        """
        conn = self._conn()
        conn.execute(
            """INSERT INTO target_candidates
               (platform, kind, external_id, permalink, username, source, caption_excerpt,
                followers_count, like_count, comments_count, engagement_rate, score,
                reasons_json, status, note, discovered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(platform, kind, external_id) DO UPDATE SET
                   permalink=excluded.permalink,
                   username=excluded.username,
                   source=excluded.source,
                   caption_excerpt=excluded.caption_excerpt,
                   followers_count=excluded.followers_count,
                   like_count=excluded.like_count,
                   comments_count=excluded.comments_count,
                   engagement_rate=excluded.engagement_rate,
                   score=excluded.score,
                   reasons_json=excluded.reasons_json""",
            (
                c.platform.value, c.kind.value, c.external_id, c.permalink, c.username,
                c.source, c.caption_excerpt, c.followers_count, c.like_count,
                c.comments_count, c.engagement_rate, c.score,
                json.dumps(c.reasons, ensure_ascii=False), c.status.value, c.note,
                c.discovered_at.isoformat(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM target_candidates WHERE platform=? AND kind=? AND external_id=?",
            (c.platform.value, c.kind.value, c.external_id),
        ).fetchone()
        conn.close()
        return self._row(row)

    def get_by_id(self, candidate_id: int) -> Optional[TargetCandidate]:
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM target_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        conn.close()
        return self._row(row) if row else None

    def list_by_status(
        self, status: TargetStatus = TargetStatus.NEW, limit: int = 50
    ) -> list[TargetCandidate]:
        """점수 높은 순 — 하루에 쓸 시간은 정해져 있으니 가장 값진 것부터."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM target_candidates WHERE status=?
               ORDER BY score DESC, discovered_at DESC LIMIT ?""",
            (status.value, limit),
        ).fetchall()
        conn.close()
        return [self._row(r) for r in rows]

    def set_status(
        self, candidate_id: int, status: TargetStatus, note: str = ""
    ) -> Optional[TargetCandidate]:
        conn = self._conn()
        actioned = now_utc().isoformat() if status != TargetStatus.NEW else None
        conn.execute(
            "UPDATE target_candidates SET status=?, note=?, actioned_at=? WHERE id=?",
            (status.value, note, actioned, candidate_id),
        )
        conn.commit()
        conn.close()
        return self.get_by_id(candidate_id)

    def counts(self) -> dict[str, int]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM target_candidates GROUP BY status"
        ).fetchall()
        conn.close()
        return {r["status"]: r["n"] for r in rows}


class HashtagQuotaRepository:
    """해시태그 검색 사용량 추적.

    Instagram은 7일 동안 **고유 해시태그 30개**까지만 조회를 허용한다. 이미 조회한
    해시태그를 다시 보는 것은 무료지만, 새 해시태그는 한도를 소모한다. 모르고 쓰면
    일주일간 발굴이 막히므로 남은 여유를 계산해 준다.
    """

    WINDOW_DAYS = 7

    def __init__(self, db_path: str | Path, limit: int = 30):
        self.db_path = db_path
        self.limit = limit

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def record(self, hashtag: str) -> None:
        conn = self._conn()
        conn.execute(
            "INSERT INTO hashtag_queries (hashtag, queried_at) VALUES (?, ?)",
            (hashtag.lstrip("#").lower(), now_utc().isoformat()),
        )
        conn.commit()
        conn.close()

    def recent_unique(self) -> set[str]:
        since = (now_utc() - timedelta(days=self.WINDOW_DAYS)).isoformat()
        conn = self._conn()
        rows = conn.execute(
            "SELECT DISTINCT hashtag FROM hashtag_queries WHERE queried_at >= ?", (since,)
        ).fetchall()
        conn.close()
        return {r["hashtag"] for r in rows}

    def remaining(self) -> int:
        return max(0, self.limit - len(self.recent_unique()))

    def allows(self, hashtag: str) -> bool:
        """이 해시태그를 지금 조회해도 되는가 (이미 본 것은 한도를 쓰지 않음)."""
        seen = self.recent_unique()
        if hashtag.lstrip("#").lower() in seen:
            return True
        return len(seen) < self.limit
