import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import sqlite3

from ..models import Post, ContentPlan, ContentPlanTopic, PostStatus, PostContent, ImageBrief
from ..models.enums import Platform, MediaType, ContentPillar
from ..utils.time import now_utc, parse_dt
from .database import get_connection


def _row_to_post(row: sqlite3.Row) -> Post:
    content_data = json.loads(row["content_json"])
    image_brief = None
    if content_data.get("image_brief"):
        image_brief = ImageBrief(**content_data["image_brief"])
    content = PostContent(
        caption_ko=content_data["caption_ko"],
        caption_en=content_data.get("caption_en"),
        hooks=content_data.get("hooks", []),
        cta=content_data.get("cta", ""),
        hashtags_ko=content_data.get("hashtags_ko", []),
        hashtags_en=content_data.get("hashtags_en", []),
        image_brief=image_brief,
        image_urls=content_data.get("image_urls", []),
    )
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
                    content_json, status, scheduled_at, week_number, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post.plan_id,
                    post.platform.value,
                    post.media_type.value,
                    post.content_pillar.value,
                    post.topic,
                    content_json,
                    post.status.value,
                    post.scheduled_at.isoformat() if post.scheduled_at else None,
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
