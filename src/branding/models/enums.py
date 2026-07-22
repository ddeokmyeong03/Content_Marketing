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


class ContentPillar(str, Enum):
    STARTUP_REALITY = "startup_reality"
    AUTOMATION_TIPS = "automation_tips"
    BUSINESS_GROWTH = "business_growth"
    MINDSET = "mindset"
