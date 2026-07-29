import json
from pathlib import Path
from datetime import datetime
import sqlite3

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS content_plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start   DATE NOT NULL,
    week_end     DATE NOT NULL,
    theme        TEXT NOT NULL,
    theme_ko     TEXT NOT NULL,
    topics_json  TEXT NOT NULL,
    generated_at DATETIME NOT NULL,
    status       TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id        INTEGER REFERENCES content_plans(id),
    platform       TEXT NOT NULL,
    media_type     TEXT NOT NULL,
    content_pillar TEXT NOT NULL,
    topic          TEXT NOT NULL,
    content_json   TEXT NOT NULL,
    status         TEXT DEFAULT 'draft',
    scheduled_at   DATETIME,
    published_at   DATETIME,
    meta_post_id   TEXT,
    permalink      TEXT,
    week_number    INTEGER NOT NULL,
    created_at     DATETIME NOT NULL,
    publish_attempts INTEGER DEFAULT 0,
    next_retry_at    DATETIME,
    last_error       TEXT
);

CREATE TABLE IF NOT EXISTS settings_store (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS token_store (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    platform      TEXT NOT NULL UNIQUE,
    access_token  TEXT NOT NULL,
    token_type    TEXT NOT NULL DEFAULT 'long_lived',
    expires_at    DATETIME,
    updated_at    DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       INTEGER REFERENCES posts(id),
    attempt_at    DATETIME NOT NULL,
    success       INTEGER NOT NULL,
    error_msg     TEXT,
    response_json TEXT
);

-- 플랫폼별 발행 성공 기록. platform=both 인 게시물은 한 번의 발행 시도에서 두 곳을
-- 순서대로 호출하는데, 앞은 성공하고 뒤가 실패하면 재시도가 성공한 쪽을 다시 올려
-- 중복 게시가 된다. 여기에 성공을 즉시 남겨 재시도가 남은 플랫폼만 집어가게 한다.
CREATE TABLE IF NOT EXISTS post_publications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       INTEGER NOT NULL REFERENCES posts(id),
    platform      TEXT NOT NULL,
    meta_post_id  TEXT,
    permalink     TEXT,
    published_at  DATETIME NOT NULL,
    response_json TEXT,
    UNIQUE(post_id, platform)
);

CREATE TABLE IF NOT EXISTS post_metrics (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id            INTEGER REFERENCES posts(id),
    platform           TEXT NOT NULL,
    fetched_at         DATETIME NOT NULL,
    likes              INTEGER DEFAULT 0,
    comments           INTEGER DEFAULT 0,
    shares             INTEGER DEFAULT 0,
    saved              INTEGER DEFAULT 0,
    reach              INTEGER DEFAULT 0,
    views              INTEGER DEFAULT 0,
    profile_visits     INTEGER DEFAULT 0,
    follows            INTEGER DEFAULT 0,
    total_interactions INTEGER DEFAULT 0,
    engagement_rate    REAL DEFAULT 0,
    raw_json           TEXT
);

CREATE TABLE IF NOT EXISTS account_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,
    fetched_at      DATETIME NOT NULL,
    followers_count INTEGER DEFAULT 0,
    reach           INTEGER DEFAULT 0,
    profile_views   INTEGER DEFAULT 0,
    views           INTEGER DEFAULT 0,
    raw_json        TEXT
);

CREATE TABLE IF NOT EXISTS comments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id           INTEGER REFERENCES posts(id),
    platform          TEXT NOT NULL,
    external_id       TEXT NOT NULL UNIQUE,
    author            TEXT,
    text              TEXT,
    status            TEXT DEFAULT 'new',
    draft_reply       TEXT,
    replied_at        DATETIME,
    reply_external_id TEXT,
    error             TEXT,
    commented_at      DATETIME,
    fetched_at        DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS target_candidates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    kind             TEXT NOT NULL,
    external_id      TEXT NOT NULL,
    permalink        TEXT,
    username         TEXT,
    source           TEXT,
    caption_excerpt  TEXT,
    followers_count  INTEGER DEFAULT 0,
    like_count       INTEGER DEFAULT 0,
    comments_count   INTEGER DEFAULT 0,
    engagement_rate  REAL DEFAULT 0,
    score            REAL DEFAULT 0,
    reasons_json     TEXT,
    status           TEXT DEFAULT 'new',
    note             TEXT,
    discovered_at    DATETIME NOT NULL,
    actioned_at      DATETIME,
    UNIQUE(platform, kind, external_id)
);

-- 해시태그 검색은 7일간 30개(고유 기준) 제한이 있다. 소진하면 일주일을 기다려야
-- 하므로 조회 이력을 남겨 남은 여유를 계산한다.
CREATE TABLE IF NOT EXISTS hashtag_queries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    hashtag    TEXT NOT NULL,
    queried_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS breakout_patterns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id           INTEGER REFERENCES posts(id),
    detected_at       DATETIME NOT NULL,
    breakout_score    REAL DEFAULT 0,
    hook_type         TEXT,
    psychology_levers TEXT,
    format            TEXT,
    topic_angle       TEXT,
    structure_notes   TEXT,
    emotional_trigger TEXT,
    spread_hypothesis TEXT,
    replicable_formula TEXT,
    confidence        INTEGER DEFAULT 0,
    metrics_snapshot  TEXT,
    source            TEXT DEFAULT 'internal',
    source_ref        TEXT
);
"""

# 기존 DB에 신규 컬럼을 안전하게 추가하기 위한 마이그레이션
# (CREATE TABLE IF NOT EXISTS 는 이미 존재하는 테이블에 컬럼을 더하지 못함)
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "post_metrics": [
        ("profile_visits", "INTEGER DEFAULT 0"),
        ("follows", "INTEGER DEFAULT 0"),
        ("total_interactions", "INTEGER DEFAULT 0"),
    ],
    "breakout_patterns": [
        ("source", "TEXT DEFAULT 'internal'"),
        ("source_ref", "TEXT"),
    ],
    # 발행 재시도 상태 — 일시 장애로 실패한 게시물을 다시 집어가기 위한 컬럼
    "posts": [
        ("publish_attempts", "INTEGER DEFAULT 0"),
        ("next_retry_at", "DATETIME"),
        ("last_error", "TEXT"),
    ],
}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        # 테이블이 아직 없으면 건너뜀 (CREATE 단계에서 최신 스키마로 생성됨)
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col_name, col_def in columns:
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")  # 백그라운드 잡 동시 접근 시 잠금 대기
    return conn


def init_db(db_path: str | Path) -> None:
    conn = get_connection(db_path)
    conn.executescript(CREATE_TABLES_SQL)
    _apply_migrations(conn)
    conn.commit()
    conn.close()
