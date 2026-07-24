from branding.ai.deconstruct import pattern_from_tool_input
from branding.db import BreakoutPatternRepository, init_db
from branding.db.database import _apply_migrations, get_connection


def _tool_data() -> dict:
    return {
        "hook_type": "story_hook",
        "psychology_levers": ["curiosity_gap", "future_pacing"],
        "spread_hypothesis": "구체적 전환 서사가 공유를 유발",
        "replicable_formula": "[before]→[구체 전환]→[after]",
        "confidence": 70,
    }


def test_external_pattern_from_tool_input_sets_source():
    p = pattern_from_tool_input(
        _tool_data(), post_id=None, source="external", source_ref="https://example.com/p/1",
    )
    assert p.source == "external"
    assert p.post_id is None
    assert p.source_ref == "https://example.com/p/1"
    assert p.hook_type == "story_hook"


def test_internal_default_source():
    p = pattern_from_tool_input(_tool_data(), post_id=5, breakout_score=60)
    assert p.source == "internal"
    assert p.post_id == 5


def test_external_pattern_persists_without_post(tmp_path):
    db = tmp_path / "content.db"
    init_db(db)
    repo = BreakoutPatternRepository(db)
    pattern = pattern_from_tool_input(
        _tool_data(), post_id=None, source="external", source_ref="@competitor",
    )
    saved = repo.save(pattern)          # post_id NULL 이어도 FK 통과
    assert saved.id is not None

    top = repo.top(limit=5)
    assert top[0].source == "external"
    assert top[0].source_ref == "@competitor"
    assert top[0].post_id is None


def test_migration_adds_source_columns(tmp_path):
    db = tmp_path / "legacy.db"
    conn = get_connection(db)
    conn.execute("""CREATE TABLE breakout_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, detected_at DATETIME,
        breakout_score REAL, hook_type TEXT, psychology_levers TEXT, format TEXT,
        topic_angle TEXT, structure_notes TEXT, emotional_trigger TEXT,
        spread_hypothesis TEXT, replicable_formula TEXT, confidence INTEGER,
        metrics_snapshot TEXT)""")
    conn.commit()
    _apply_migrations(conn)
    conn.commit()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(breakout_patterns)")}
    conn.close()
    assert {"source", "source_ref"} <= cols
