from branding.models import Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform
from branding.publisher.threads import THREADS_TEXT_LIMIT, build_threads_text


def _post(caption: str, cta: str = "", tags=None) -> Post:
    return Post(
        platform=Platform.THREADS,
        media_type=MediaType.TEXT,
        content_pillar=ContentPillar.MINDSET,
        topic="테스트",
        content=PostContent(
            caption_ko=caption,
            cta=cta,
            hashtags_ko=tags or [],
        ),
    )


def test_threads_text_includes_caption_cta_and_limited_tags():
    text = build_threads_text(
        _post("본문입니다", cta="저장해두세요", tags=["창업", "자동화", "성장", "여분", "추가"])
    )
    assert "본문입니다" in text
    assert "저장해두세요" in text
    # 해시태그는 최대 3개, # 접두사 부착
    assert text.count("#") == 3
    assert "#창업" in text


def test_threads_text_truncated_to_limit():
    text = build_threads_text(_post("가" * 1000))
    assert len(text) <= THREADS_TEXT_LIMIT
    assert text.endswith("…")
