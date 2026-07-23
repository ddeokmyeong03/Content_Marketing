import httpx

from branding.config.settings import Settings
from branding.db import MetricsRepository, PostRepository, init_db
from branding.insights import InsightsService, parse_insights
from branding.models import Post, PostContent, HookVariant
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus


def test_parse_insights_handles_both_shapes():
    payload = {
        "data": [
            {"name": "reach", "values": [{"value": 1000}]},
            {"name": "saved", "total_value": {"value": 42}},
            {"name": "empty"},
        ]
    }
    out = parse_insights(payload)
    assert out["reach"] == 1000
    assert out["saved"] == 42
    assert out["empty"] == 0


def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path, meta_access_token="tok", meta_threads_user_id="1")
    init_db(s.db_path)
    return s


def _published_threads_post(repo: PostRepository) -> Post:
    post = Post(
        platform=Platform.THREADS,
        media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET,
        topic="t",
        content=PostContent(caption_ko="c", cta=""),
        status=PostStatus.PUBLISHED,
        meta_post_id="MEDIA123",
    )
    return repo.save(post)


def test_fetch_threads_post_maps_metrics(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "MEDIA123/insights" in str(request.url)
        return httpx.Response(200, json={"data": [
            {"name": "likes", "values": [{"value": 50}]},
            {"name": "replies", "values": [{"value": 8}]},
            {"name": "reposts", "values": [{"value": 3}]},
            {"name": "quotes", "values": [{"value": 2}]},
            {"name": "views", "values": [{"value": 500}]},
        ]})

    s = _settings(tmp_path)
    repo = PostRepository(s.db_path)
    post = _published_threads_post(repo)
    svc = InsightsService(s, transport=httpx.MockTransport(handler))

    m = svc.fetch_post(post)
    assert m.likes == 50
    assert m.comments == 8
    assert m.shares == 5           # reposts + quotes
    assert m.views == 500
    assert m.engagement_rate == round(63 / 500, 4)


def test_sync_stores_snapshot(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"data": [{"name": "likes", "values": [{"value": 10}]}]})

    s = _settings(tmp_path)
    repo = PostRepository(s.db_path)
    post = _published_threads_post(repo)
    svc = InsightsService(s, transport=httpx.MockTransport(handler))

    collected = svc.sync()
    assert len(collected) == 1
    latest = MetricsRepository(s.db_path).latest_for_post(post.id)
    assert latest is not None and latest.likes == 10


def test_top_performers_feedback_query(tmp_path):
    s = _settings(tmp_path)
    prepo = PostRepository(s.db_path)
    mrepo = MetricsRepository(s.db_path)

    # 두 게시물, 서로 다른 참여율
    for topic, hook, rate in [("저성과", "밋밋한 훅", 0.01), ("고성과", "강한 훅", 0.25)]:
        p = prepo.save(Post(
            platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
            content_pillar=ContentPillar.AUTOMATION_TIPS, topic=topic,
            content=PostContent(caption_ko="c", cta="", chosen_hook=hook),
            status=PostStatus.PUBLISHED, meta_post_id=f"m-{topic}",
        ))
        m = mrepo  # noqa
        from branding.models import PostMetric
        snap = PostMetric(post_id=p.id, platform=Platform.INSTAGRAM, engagement_rate=rate)
        mrepo.save_snapshot(snap)

    top = mrepo.top_performers(weeks=8, limit=5, order_by="engagement_rate")
    assert top[0]["topic"] == "고성과"
    assert top[0]["chosen_hook"] == "강한 훅"
