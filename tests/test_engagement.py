import httpx
import pytest

from branding.ai.reply_gen import draft_from_tool_input
from branding.config.settings import Settings
from branding.db import CommentRepository, PostRepository, init_db
from branding.engagement import EngagementService
from branding.models import Comment, Post, PostContent
from branding.models.enums import (
    CommentStatus, ContentPillar, MediaType, Platform, PostStatus,
)


def _settings(tmp_path, **kw) -> Settings:
    base = {"anthropic_api_key": "", "meta_access_token": "tok",
            "meta_ig_user_id": "IG1", "meta_threads_user_id": "TH1",
            "threads_publish_delay_seconds": 0}
    base.update(kw)
    s = Settings(data_dir=tmp_path, **base)
    init_db(s.db_path)
    return s


def _post(db_path, platform=Platform.THREADS) -> Post:
    return PostRepository(db_path).save(Post(
        platform=platform, media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET, topic="번아웃",
        content=PostContent(caption_ko="본문", cta=""),
        status=PostStatus.PUBLISHED, meta_post_id="MEDIA1",
    ))


# --- 초안 파싱 (순수 함수) ---

def test_draft_parsing_needs_reply():
    d = draft_from_tool_input({"needs_reply": True, "reply": "공감해요!", "intent": "agreement"})
    assert d.needs_reply and d.reply == "공감해요!"


def test_draft_parsing_spam_clears_reply():
    d = draft_from_tool_input({"needs_reply": False, "reply": "무시", "intent": "spam"})
    assert d.needs_reply is False and d.reply == ""


def test_draft_parsing_empty_reply_is_not_needs_reply():
    d = draft_from_tool_input({"needs_reply": True, "reply": "   ", "intent": "other"})
    assert d.needs_reply is False


# --- 댓글 수집 ---

def test_fetch_comments_saves_new_only(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        assert "MEDIA1/replies" in str(request.url)   # Threads는 /replies
        return httpx.Response(200, json={"data": [
            {"id": "C1", "text": "저도 그랬어요", "username": "kim",
             "timestamp": "2026-07-20T10:00:00+0000"},
            {"id": "C2", "text": "질문 있어요", "username": "lee",
             "timestamp": "2026-07-20T11:00:00+0000"},
        ]})

    s = _settings(tmp_path)
    post = _post(s.db_path)
    svc = EngagementService(s, transport=httpx.MockTransport(handler))

    first = svc.fetch_for_post(post)
    assert len(first) == 2
    # 재수집 시 중복 저장 안 함
    second = svc.fetch_for_post(post)
    assert second == []
    assert len(CommentRepository(s.db_path).list_by_status(CommentStatus.NEW)) == 2


def test_instagram_uses_comments_endpoint(tmp_path):
    def handler(request):
        assert "MEDIA1/comments" in str(request.url)
        return httpx.Response(200, json={"data": []})

    s = _settings(tmp_path)
    post = _post(s.db_path, platform=Platform.INSTAGRAM)
    EngagementService(s, transport=httpx.MockTransport(handler)).fetch_for_post(post)


# --- 답글 발행 ---

def test_threads_reply_uses_reply_to_id_and_publish(tmp_path):
    seen = {}

    def handler(request):
        url = str(request.url)
        body = request.content.decode()
        if url.endswith("/threads"):
            assert "reply_to_id=C1" in body
            seen["created"] = True
            return httpx.Response(200, json={"id": "CONTAINER1"})
        if url.endswith("/threads_publish"):
            assert "creation_id=CONTAINER1" in body
            return httpx.Response(200, json={"id": "REPLY1"})
        return httpx.Response(400, json={"error": {"message": "unexpected"}})

    s = _settings(tmp_path)
    post = _post(s.db_path)
    repo = CommentRepository(s.db_path)
    c = repo.upsert(Comment(post_id=post.id, platform=Platform.THREADS,
                            external_id="C1", author="kim", text="저도요",
                            draft_reply="공감해요. 어떤 부분이 가장 힘드셨어요?"))

    out = EngagementService(s, transport=httpx.MockTransport(handler)).post_reply(c)
    assert out.success and seen.get("created")
    saved = repo.get_by_id(c.id)
    assert saved.status == CommentStatus.REPLIED
    assert saved.reply_external_id == "REPLY1"


def test_instagram_reply_posts_to_comment_replies(tmp_path):
    def handler(request):
        assert "C9/replies" in str(request.url)
        assert "message=" in request.content.decode()
        return httpx.Response(200, json={"id": "R9"})

    s = _settings(tmp_path)
    post = _post(s.db_path, platform=Platform.INSTAGRAM)
    repo = CommentRepository(s.db_path)
    c = repo.upsert(Comment(post_id=post.id, platform=Platform.INSTAGRAM,
                            external_id="C9", author="lee", text="좋아요",
                            draft_reply="감사해요! 어떤 게 가장 도움됐나요?"))
    out = EngagementService(s, transport=httpx.MockTransport(handler)).post_reply(c)
    assert out.success
    assert repo.get_by_id(c.id).status == CommentStatus.REPLIED


def test_reply_failure_marks_failed(tmp_path):
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "권한 없음"}})

    s = _settings(tmp_path)
    post = _post(s.db_path, platform=Platform.INSTAGRAM)
    repo = CommentRepository(s.db_path)
    c = repo.upsert(Comment(post_id=post.id, platform=Platform.INSTAGRAM,
                            external_id="C7", text="x", draft_reply="답글"))
    out = EngagementService(s, transport=httpx.MockTransport(handler)).post_reply(c)
    assert out.success is False
    saved = repo.get_by_id(c.id)
    assert saved.status == CommentStatus.FAILED
    assert "권한" in saved.error


def test_reply_without_draft_is_rejected(tmp_path):
    s = _settings(tmp_path)
    post = _post(s.db_path)
    c = CommentRepository(s.db_path).upsert(Comment(
        post_id=post.id, platform=Platform.THREADS, external_id="C0", text="x"))
    out = EngagementService(s).post_reply(c)
    assert out.success is False
    assert "없습니다" in out.error


# --- 초안 생성 파이프라인 (AI 목업) ---

def test_draft_replies_ignores_spam(tmp_path, monkeypatch):
    s = _settings(tmp_path, anthropic_api_key="sk-x")
    post = _post(s.db_path)
    repo = CommentRepository(s.db_path)
    repo.upsert(Comment(post_id=post.id, platform=Platform.THREADS,
                        external_id="S1", author="bot", text="팔로우 맞팔 dm"))
    repo.upsert(Comment(post_id=post.id, platform=Platform.THREADS,
                        external_id="S2", author="kim", text="어떻게 시작했어요?"))

    import branding.ai.reply_gen as rg
    from branding.ai.reply_gen import ReplyDraft

    def fake_generate(**kw):
        if "맞팔" in kw["comment_text"]:
            return ReplyDraft(False, "", "spam")
        return ReplyDraft(True, "작게 시작했어요. 어떤 걸 준비 중이세요?", "question")

    monkeypatch.setattr(rg, "generate_reply", fake_generate)

    from branding.config import load_brand_config
    brand = load_brand_config("brand/config.yaml")
    drafted = EngagementService(s).draft_replies(brand, "sk-x")

    assert len(drafted) == 1
    assert repo.list_by_status(CommentStatus.IGNORED)[0].external_id == "S1"
    assert repo.list_by_status(CommentStatus.DRAFTED)[0].draft_reply.startswith("작게")
