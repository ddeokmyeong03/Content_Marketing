# CLAUDE.md — 프로젝트 컨텍스트

> 이 파일은 새 세션에서 자동으로 읽힙니다. **진행 상황·미해결 이슈는 `docs/HANDOFF.md`** 참조.

## 이 프로젝트의 정체

Instagram · Threads **개인 브랜드 콘텐츠 운영 자동화 시스템**.
단순 게시 자동화가 아니라 **"세부 니치 청중의 반응을 유도해 참여율을 극대화하고,
무엇이 왜 먹혔는지 학습하는 성장 엔진"** 이 본질이다. (이 목표를 축소 해석하지 말 것)

핵심 폐루프:
```
기획 → 심리 기반 카피 생성 → 검토·승인 → 발행 → 성과 수집
  ↑                                                    ↓
  └── 승리 공식 재주입 ← AI 역설계 ← 브레이크아웃 탐지 ←┘
```

## 아키텍처 맵

| 경로 | 역할 |
|------|------|
| `brand/config.yaml` | **모든 것의 기준점.** 니치·청중(pains/desires/objections)·심리 레버·목표지표·톤 |
| `src/branding/ai/` | 캡션·기획·훅 생성, `psychology.py`(행동심리 레버), `engagement.py`(자기평가 루프), `deconstruct.py`(역설계), `reply_gen.py`(답글) |
| `src/branding/analysis/` | `breakout.py`(이상치 탐지, 순수계산), `attribution.py`(성장 귀인), `service.py` |
| `src/branding/insights/` | Graph API 성과 수집 (게시물·계정) |
| `src/branding/engagement/` | 댓글 수집·AI 답글·발행 (계정 활성화) |
| `src/branding/publisher/` | Threads/Instagram 발행 + 상태 전이 |
| `src/branding/scheduler/` | APScheduler 6개 잡 (무인 운영) |
| `src/branding/web/` | FastAPI 운영 대시보드 + 단일 페이지 UI |
| `src/branding/render/` | 캐러셀 텍스트 카드 — `card.py`(HTML 생성, 순수함수) `png.py`(크로미엄) `service.py` |
| `src/branding/upload/` | 렌더 PNG → 공개 URL — `directory.py`(정적서버) `s3.py`(S3호환) `service.py` |
| `src/branding/diagnostics.py` | 연결 진단 (키·토큰·ID 검증, 자동 수정) |
| `docs/` | `USAGE`(실행) `GROWTH_ANALYSIS`(BGI 설계) `BUSINESS`(판매전략) `PITCH`(광고·랜딩) `HANDOFF`(진행상황) |

## 설계 원칙 (유지할 것)

1. **설정으로 튜닝** — 니치·타깃·심리레버·지표는 `brand/config.yaml`에서 코드 수정 없이 변경
2. **서비스/리포지토리 분리** — 비즈니스 로직은 서비스 계층에. CLI·웹·스케줄러는 얇은 진입점
3. **오프라인 테스트 가능** — HTTP는 `transport` 주입(`httpx.MockTransport`), AI 파싱은 순수 함수로 분리
4. **시간은 UTC aware로 저장**, 예약 계산은 로컬(KST) → `utils/time.py` 사용. `datetime.utcnow()` 금지
5. **DB 마이그레이션** — 새 컬럼은 `_MIGRATIONS`에 추가 (기존 DB 보호, idempotent)
6. **하위 호환** — config에 새 섹션 추가 시 기본값 제공

## 명령어

```bash
pip install -e '.[dev,web]'
python scripts/setup_db.py
pytest -q                       # 87건, 전부 오프라인

branding doctor run --fix       # 연결 진단 (문제 생기면 먼저 이것)
branding plan generate --captions
branding queue list / approve <id>
branding post now <id>
branding render check / sample / slides <id>   # 캐러셀 텍스트 카드 → PNG
branding upload check / slides <id> / status <id>   # PNG → 공개 URL (발행 전 필수)
branding engage sync / list / reply <id>
branding insights sync / breakouts / deconstruct / attribution
branding serve run              # 스케줄러 데몬
branding web run                # 대시보드 http://127.0.0.1:8000
python scripts/demo_seed.py     # 키 없이 분석 기능 시연용 가짜 데이터
```

## 반드시 지킬 제약

- **타 계정 팔로우·좋아요 자동화 금지.** 공식 Graph API에 엔드포인트가 없고, 비공식 자동화는
  ToS 위반 → 계정 정지 위험. 타깃 *발굴*까지만 자동화하고 실행은 사람이 한다.
- **설득은 사실 기반.** `psychology.banned_tactics`(허위 희소성·거짓 수치·낚시성 과장) 준수.
  제품 철학이자 마케팅 카피 톤이기도 함.
- **Instagram 발행은 공개 이미지 URL 필수** — 캐러셀은 `render slides` → `upload slides`로
  `slide.image_url`을 채워야 발행된다. 하나라도 비면 발행이 막히고 빠진 번호를 알려준다.
- **AI 이미지 모델은 한글 텍스트가 자주 깨진다** — 텍스트 카드는 `src/branding/render/`의
  HTML/CSS → 헤드리스 크로미엄 PNG 렌더를 쓴다(한글 완벽·브랜드 일관). AI 이미지는
  무텍스트 배경/일러스트용. 렌더는 `image_path`(로컬)까지만 채우며, 발행에 필요한
  공개 URL(`image_url`)은 업로드 단계에서 채워진다.

## 커밋 규칙

- 브랜치: `claude/automation-implementation-details-hlhzof` (현재 `main`과 동일 — 병합 완료)
- 커밋 메시지는 한국어, 무엇을/왜 중심
- 작업 후 `pytest -q` 통과 확인
