import yaml

from branding.config.brand_config import BrandConfig, load_brand_config
from branding.db import PostRepository, init_db
from branding.models import HookVariant, Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus


def test_config_backward_compatible_without_engine_sections():
    """참여 엔진 섹션이 없는 기존 config도 기본값으로 로드돼야 한다."""
    data = yaml.safe_load(open("brand/config.yaml", encoding="utf-8"))
    for key in ("niche", "audience", "psychology", "engagement"):
        data.pop(key, None)
    brand = BrandConfig(**data)
    assert brand.niche == ""
    assert brand.engagement.primary_metric == "saves"       # 기본값
    assert "curiosity_gap" in brand.psychology.levers        # 기본 레버
    assert brand.audience.sophistication == "중급"


def test_real_config_has_engine_fields():
    brand = load_brand_config("brand/config.yaml")
    assert brand.niche
    assert brand.audience.pains
    assert brand.engagement.hook_variants >= 1


def test_postcontent_roundtrip_preserves_engine_fields(tmp_path):
    """hook_variants·engagement 필드가 DB 저장/조회에서 보존되는지."""
    s_db = tmp_path / "content.db"
    init_db(s_db)
    repo = PostRepository(s_db)
    content = PostContent(
        caption_ko="본문",
        cta="저장해 두세요",
        hooks=["훅A", "훅B"],
        hook_variants=[
            HookVariant(text="훅A", technique="curiosity_gap", predicted_score=82),
            HookVariant(text="훅B", technique="contrarian_hook", predicted_score=75),
        ],
        chosen_hook="훅A",
        engagement_score=84,
        engagement_notes="구체성 보강",
    )
    post = Post(
        platform=Platform.INSTAGRAM,
        media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS,
        topic="t",
        content=content,
        status=PostStatus.DRAFT,
    )
    saved = repo.save(post)
    loaded = repo.get_by_id(saved.id)

    assert loaded.content.engagement_score == 84
    assert loaded.content.chosen_hook == "훅A"
    assert len(loaded.content.hook_variants) == 2
    assert loaded.content.hook_variants[0].technique == "curiosity_gap"
    assert loaded.content.hook_variants[0].predicted_score == 82
