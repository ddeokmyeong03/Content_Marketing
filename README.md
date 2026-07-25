# Content_Marketing

Instagram & Threads 브랜딩 자동 관리 서비스. `brand/config.yaml` 하나로 브랜드 정체성을
정의하면, Claude가 주간 콘텐츠 계획과 캡션을 생성하고, 스케줄러가 예약 시각에 맞춰
Meta/Threads Graph API로 자동 발행합니다.

## 설치

```bash
pip install -e '.[dev]'
cp .env.example .env   # 값 채우기
python scripts/setup_db.py
```

## 파이프라인

```
plan generate → (검토/승인) → serve run → Threads/Instagram 자동 발행
   AI 계획+캡션      queue          스케줄러         Publisher
```

## 주요 명령

| 명령 | 설명 |
|------|------|
| `branding doctor run [--fix]` | 연결 진단 — 키·토큰·계정 ID 검사 및 자동 수정 |
| `branding brand show` | 브랜드 설정 확인 |
| `branding plan generate --captions` | 주간 계획 + 캡션 생성 (DB 저장) |
| `branding queue list` / `show` / `approve` / `reject` | 발행 큐 검토·승인 |
| `branding post now <id>` | 특정 게시물 즉시 발행 |
| `branding token set -p threads -t <TOKEN>` | 액세스 토큰 저장(.env보다 우선) |
| `branding token refresh [--force]` | 만료 임박 롱리브드 토큰 갱신 |
| `branding insights sync` | 발행 게시물 + 계정 성과 수집 |
| `branding insights top` | 참여율 상위 성과 콘텐츠 확인 |
| `branding insights account` | 계정 팔로워·성장 추이 (BGI 기반) |
| `branding insights breakouts` | 팔로워 대비 압도적으로 뜬 게시물 탐지 |
| `branding insights deconstruct` | 브레이크아웃을 AI로 역설계 → 승리 공식 저장 |
| `branding insights patterns` | 저장된 승리 공식 라이브러리 확인 |
| `branding insights attribution` | 팔로워 성장을 게시물에 귀속 (유입 정량화) |
| `branding insights external` | 외부/경쟁사 바이럴을 역설계해 승리 공식에 추가 |
| `branding serve publish-once` | 예약 지난 승인 게시물 1회 발행 |
| `branding serve run` | 스케줄러 데몬 (발행/주간생성/토큰갱신/성과수집/검토알림) |
| `branding web run` | 운영 대시보드 (웹 UI) — 검토 승인·성장 분석·승리 공식 |

## 스케줄러 잡

`branding serve run` 이 등록하는 잡:
- **publish-poll**: N분마다 예약 지난 승인 게시물 발행
- **weekly-plan**: 매주 지정 요일/시각에 다음 주 콘텐츠 자동 생성
- **token-refresh**: 매일 만료 임박 토큰 자동 갱신
- **review-reminder**: `auto_approve=false`일 때 매일 검토 대기 게시물 알림

## 알림

발행 성공/실패, 주간 생성, 검토 리마인더는 알림으로 전달됩니다. 기본은 콘솔 로그이며,
`NOTIFY_WEBHOOK_URL`(Slack/Discord 호환 incoming webhook)을 설정하면 해당 채널로도 전송됩니다.

## 참여 엔진 (핵심)

이 서비스의 본질은 자동화 자체가 아니라 **세부 니치 청중의 반응을 유도해 참여율을 극대화**하는 것입니다.
콘텐츠 생성은 행동심리 기법을 언어에 녹여 설계됩니다:

- **니치·청중 타깃팅** — `brand/config.yaml`의 `niche` / `audience`(pains·desires·objections)를 프롬프트에 정조준 주입
- **행동심리 레버** — `psychology.levers`로 호기심 갭·손실 회피·역발상·사회적 증거 등을 활성화 (`ai/psychology.py`)
- **지표 정렬 CTA** — `engagement.primary_metric`(saves/comments/shares/follows)에 맞춰 훅·CTA 전략 자동 조정
- **훅 엔지니어링** — 서로 다른 기법의 훅 N개 생성 + 자기예측 점수로 최적 훅 채택
- **자기평가·개선 루프** — 생성 후 루브릭으로 참여 점수를 매기고, `min_hook_score` 미만이면 평가를 반영해 1회 자동 재생성 (`generate_optimized_caption`)
- **성과 측정 → 피드백 루프** — 발행 후 IG/Threads 실제 지표(저장·댓글·공유·도달)를 수집(`insights sync`)하고, 상위 성과 주제/훅을 **다음 주 기획에 재주입**(`MetricsRepository.top_performers` → 기획 프롬프트). 예측 → 측정 → 학습이 순환합니다.
- **브레이크아웃 성장 분석 (BGI)** — 팔로워 대비 압도적으로 뜬 게시물을 탐지(`insights breakouts`)하고 AI로 왜 떴는지 역설계(`insights deconstruct`)해 '승리 공식'으로 축적, 다음 기획·캡션 생성에 자동 재주입(폐루프). 상세: `docs/GROWTH_ANALYSIS.md`

> 니치·청중·심리 레버·목표 지표·설득 강도는 모두 `brand/config.yaml`에서 **코드 수정 없이** 조정합니다.

## 자동화 수준

`brand/config.yaml`의 `automation.auto_approve`:
- `false` (기본): 생성물은 `DRAFT` → 사람이 `queue approve` 후 발행
- `true`: 생성물이 곧바로 `APPROVED` → 스케줄러가 예약 시각에 자동 발행 (완전 자동)

## 발행 요건

- **Threads**: 텍스트 발행은 토큰 + `META_THREADS_USER_ID`만 있으면 동작.
- **Instagram**: Graph API가 **공개 이미지 URL**을 요구합니다. 이미지 생성·호스팅은
  아직 미구현이며, `content.image_urls`가 채워져야 발행됩니다.
