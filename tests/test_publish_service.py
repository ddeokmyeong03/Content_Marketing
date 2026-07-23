from datetime import datetime, timezone

from branding.config.settings import Settings
from branding.db import PostRepository, init_db
from branding.models import Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.publisher import PublishService


def _settings(tmp_path) -> Settings:
    return Settings(
        anthropic_api_key="x",
        meta_access_token="",  # 토큰 없음 → 발행 실패 유도
        meta_threads_user_id="123",
        data_dir=tmp_path,
    )


def _make_post(repo: PostRepository) -> Post:
    post = Post(
        platform=Platform.THREADS,
        media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET,
        topic="t",
        content=PostContent(caption_ko="안녕하세요", cta="", hashtags_ko=[]),
        status=PostStatus.APPROVED,
        scheduled_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    return repo.save(post)


def test_publish_marks_failed_when_token_missing(tmp_path):
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)
    post = _make_post(repo)

    outcome = PublishService(settings).publish_post(post)

    assert outcome.success is False
    assert repo.get_by_id(post.id).status == PostStatus.FAILED


def test_run_pending_processes_due_posts(tmp_path):
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)
    _make_post(repo)

    outcomes = PublishService(settings).run_pending()

    assert len(outcomes) == 1  # 예약 시각이 지난 승인 게시물 1건 처리
