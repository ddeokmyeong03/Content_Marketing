from datetime import timedelta

from branding.analysis import PostAttrInput, attribute
from branding.analysis import BreakoutService
from branding.config.settings import Settings
from branding.db import (
    AccountMetricsRepository, MetricsRepository, PostRepository, init_db,
)
from branding.models import AccountMetric, Post, PostContent, PostMetric
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.utils.time import now_utc


# --- 순수 귀인 로직 ---

def test_attribute_distributes_growth_by_follows():
    items = [
        PostAttrInput(post_id=1, follows=30),
        PostAttrInput(post_id=2, follows=10),
    ]
    res = attribute(items, total_growth=100)
    by_id = {r.post_id: r for r in res}
    assert by_id[1].attributed_followers == 75.0   # 30/40 * 100
    assert by_id[2].attributed_followers == 25.0
    assert all(r.method == "direct" for r in res)
    # 합계 == 관측 성장
    assert round(sum(r.attributed_followers for r in res)) == 100


def test_attribute_uses_interactions_when_no_follows():
    items = [
        PostAttrInput(post_id=1, follows=0, interactions=900),
        PostAttrInput(post_id=2, follows=0, interactions=100),
    ]
    res = attribute(items, total_growth=50)
    by_id = {r.post_id: r for r in res}
    assert by_id[1].attributed_followers == 45.0   # modeled
    assert by_id[1].method == "modeled"


def test_attribute_zero_growth_gives_zero():
    res = attribute([PostAttrInput(post_id=1, follows=5)], total_growth=0)
    assert res[0].attributed_followers == 0.0


def test_attribute_equal_split_when_no_signal():
    items = [PostAttrInput(post_id=1), PostAttrInput(post_id=2)]
    res = attribute(items, total_growth=10)
    assert all(r.attributed_followers == 5.0 for r in res)


# --- 서비스 조립 ---

def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    return s


def test_attribution_service_assembles(tmp_path):
    s = _settings(tmp_path)
    prepo, mrepo, arepo = (
        PostRepository(s.db_path), MetricsRepository(s.db_path), AccountMetricsRepository(s.db_path),
    )
    arepo.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1000,
                                      fetched_at=now_utc() - timedelta(days=25)))
    arepo.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1200,
                                      fetched_at=now_utc()))

    def add(topic, follows):
        p = prepo.save(Post(
            platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
            content_pillar=ContentPillar.AUTOMATION_TIPS, topic=topic,
            content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
            meta_post_id=f"m-{topic}", published_at=now_utc() - timedelta(days=10),
        ))
        mrepo.save_snapshot(PostMetric(post_id=p.id, platform=Platform.INSTAGRAM,
                                       reach=5000, follows=follows))

    add("강한글", 150)
    add("약한글", 50)

    groups = BreakoutService(s).attribute_growth(days=30)
    assert len(groups) == 1
    g = groups[0]
    assert g.follower_growth == 200
    assert g.rows[0].post.topic == "강한글"          # 귀인 큰 순
    assert g.rows[0].result.attributed_followers == 150.0   # 150/200*200
