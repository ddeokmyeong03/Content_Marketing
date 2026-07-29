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


class TargetKind(str, Enum):
    """발굴 대상 종류."""
    POST = "post"        # 해시태그로 찾은 게시물 — 사람이 열어서 댓글·좋아요
    ACCOUNT = "account"  # business_discovery로 조회한 계정 — 사람이 팔로우·소통


class TargetStatus(str, Enum):
    NEW = "new"          # 발굴됨, 아직 실행 안 함
    ACTIONED = "actioned"  # 사람이 실행 완료
    SKIPPED = "skipped"    # 적합하지 않아 건너뜀


class ContentPillar(str, Enum):
    STARTUP_REALITY = "startup_reality"
    AUTOMATION_TIPS = "automation_tips"
    BUSINESS_GROWTH = "business_growth"
    MINDSET = "mindset"
