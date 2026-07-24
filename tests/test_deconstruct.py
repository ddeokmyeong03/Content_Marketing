from branding.ai.deconstruct import pattern_from_tool_input
from branding.db import BreakoutPatternRepository, PostRepository, init_db
from branding.models import BreakoutPattern, Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus


def _make_post(repo: PostRepository, topic: str) -> int:
    p = repo.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic=topic,
        content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
        meta_post_id=f"m-{topic}",
    ))
    return p.id


def test_pattern_from_tool_input_maps_fields():
    data = {
        "hook_type": "contrarian_hook",
        "psychology_levers": ["contrarian", "specificity"],
        "format": "carousel",
        "topic_angle": "실패 고백",
        "structure_notes": "훅→반전→증거",
        "emotional_trigger": "안도",
        "spread_hypothesis": "공유율이 튄 것은 정체성 공감 문장 때문",
        "replicable_formula": "[통념 반박] + [구체 수치] + [정체성 호명]",
        "confidence": 88,
    }
    p = pattern_from_tool_input(data, post_id=7, breakout_score=64.0,
                               metrics_snapshot={"reach": 9000, "shares": 500})
    assert p.post_id == 7
    assert p.breakout_score == 64.0
    assert p.hook_type == "contrarian_hook"
    assert p.psychology_levers == ["contrarian", "specificity"]
    assert p.confidence == 88
    assert p.metrics_snapshot["reach"] == 9000


def test_pattern_from_tool_input_tolerates_missing_optionals():
    p = pattern_from_tool_input(
        {"hook_type": "x", "psychology_levers": [], "spread_hypothesis": "h",
         "replicable_formula": "f", "confidence": 50},
        post_id=1, breakout_score=50.0, metrics_snapshot={},
    )
    assert p.format == "" and p.topic_angle == ""


def test_pattern_repo_roundtrip_and_top(tmp_path):
    db = tmp_path / "content.db"
    init_db(db)
    prepo = PostRepository(db)
    id_a = _make_post(prepo, "A")
    id_b = _make_post(prepo, "B")
    repo = BreakoutPatternRepository(db)
    assert repo.exists_for_post(id_a) is False

    repo.save(BreakoutPattern(post_id=id_a, breakout_score=70, hook_type="result_hook",
                              psychology_levers=["social_proof"], confidence=90,
                              replicable_formula="F1", spread_hypothesis="s",
                              metrics_snapshot={"reach": 8000}))
    repo.save(BreakoutPattern(post_id=id_b, breakout_score=55, hook_type="question_hook",
                              psychology_levers=["curiosity_gap"], confidence=60,
                              replicable_formula="F2", spread_hypothesis="s2"))

    assert repo.exists_for_post(id_a) is True
    top = repo.top(limit=10)
    assert top[0].confidence == 90                # 신뢰도 내림차순
    assert top[0].psychology_levers == ["social_proof"]
    assert top[0].metrics_snapshot["reach"] == 8000
