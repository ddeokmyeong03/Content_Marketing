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
    created_at     DATETIME NOT NULL
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
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path) -> None:
    conn = get_connection(db_path)
    conn.executescript(CREATE_TABLES_SQL)
    _apply_migrations(conn)
    conn.commit()
    conn.close()
