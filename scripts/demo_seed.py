"""오프라인 데모용 가짜 데이터 시드 스크립트.

실제 API/키 없이 BGI 분석 파이프라인(브레이크아웃 탐지·성장 귀인 등)을
눈으로 확인하기 위한 합성 데이터를 DB에 넣는다. AI 생성/역설계(P3·P6)와
실제 발행만 키가 필요하고, 그 외 분석은 이 데이터로 전부 동작한다.

사용:
    export DATA_DIR=$(mktemp -d)      # 실데이터와 분리 권장
    python scripts/demo_seed.py
    branding insights breakouts
    branding insights attribution
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from branding.config import get_settings
from branding.db import (
    AccountMetricsRepository, MetricsRepository, PostRepository, init_db,
)
from branding.models import AccountMetric, Post, PostContent, PostMetric
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.utils.time import now_utc

settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
init_db(settings.db_path)

pr = PostRepository(settings.db_path)
mr = MetricsRepository(settings.db_path)
ar = AccountMetricsRepository(settings.db_path)

# 1) 계정 스냅샷 2개 → 팔로워 성장 +420
ar.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=2000,
                               reach=15000, fetched_at=now_utc() - timedelta(days=28)))
ar.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=2420,
                               reach=41000, fetched_at=now_utc()))

# 2) 평범한 게시물 8개 + 브레이크아웃 1개
def add(topic, reach, shares, follows, saved, pillar=ContentPillar.AUTOMATION_TIPS):
    p = pr.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=pillar, topic=topic,
        content=PostContent(caption_ko=f"{topic} 본문입니다.", cta="저장해 두세요",
                            chosen_hook=f"{topic} — 강력한 첫 문장"),
        status=PostStatus.PUBLISHED, meta_post_id=f"demo-{topic}",
        published_at=now_utc() - timedelta(days=6),
    ))
    mr.save_snapshot(PostMetric(
        post_id=p.id, platform=Platform.INSTAGRAM, reach=reach, shares=shares,
        follows=follows, saved=saved, likes=reach // 20, comments=reach // 100,
        total_interactions=reach // 8,
    ))
    return p.id

for i in range(8):
    add(f"평범한 팁 {i+1}", reach=2000, shares=4, follows=2, saved=8)

viral = add("혼자 다 하려다 번아웃 직전이었던 이야기", reach=38000,
            shares=1200, follows=380, saved=2100, pillar=ContentPillar.STARTUP_REALITY)

print(f"✓ 시드 완료: {settings.db_path}")
print(f"  계정 성장 +420, 게시물 9개(브레이크아웃 1개, post #{viral})")
print("  이제 실행해 보세요:")
print("    branding insights breakouts")
print("    branding insights attribution")
