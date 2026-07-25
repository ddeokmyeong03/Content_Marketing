from enum import Enum


class PostStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"


class Platform(str, Enum):
    INSTAGRAM = "instagram"
    THREADS = "threads"
    BOTH = "both"


class MediaType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    CAROUSEL = "carousel"
    REEL = "reel"
    STORY = "story"


class CommentStatus(str, Enum):
    NEW = "new"            # 수집됨, 미처리
    DRAFTED = "drafted"    # AI 답글 초안 생성됨
    REPLIED = "replied"    # 답글 발행 완료
    IGNORED = "ignored"    # 응대 불필요(스팸 등)
    FAILED = "failed"      # 답글 발행 실패


class ContentPillar(str, Enum):
    STARTUP_REALITY = "startup_reality"
    AUTOMATION_TIPS = "automation_tips"
    BUSINESS_GROWTH = "business_growth"
    MINDSET = "mindset"
