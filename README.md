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
| `branding brand show` | 브랜드 설정 확인 |
| `branding plan generate --captions` | 주간 계획 + 캡션 생성 (DB 저장) |
| `branding queue list` / `show` / `approve` / `reject` | 발행 큐 검토·승인 |
| `branding post now <id>` | 특정 게시물 즉시 발행 |
| `branding token set -p threads -t <TOKEN>` | 액세스 토큰 저장(.env보다 우선) |
| `branding serve publish-once` | 예약 지난 승인 게시물 1회 발행 |
| `branding serve run` | 스케줄러 데몬 (발행 폴링 + 주간 자동 생성) |

## 자동화 수준

`brand/config.yaml`의 `automation.auto_approve`:
- `false` (기본): 생성물은 `DRAFT` → 사람이 `queue approve` 후 발행
- `true`: 생성물이 곧바로 `APPROVED` → 스케줄러가 예약 시각에 자동 발행 (완전 자동)

## 발행 요건

- **Threads**: 텍스트 발행은 토큰 + `META_THREADS_USER_ID`만 있으면 동작.
- **Instagram**: Graph API가 **공개 이미지 URL**을 요구합니다. 이미지 생성·호스팅은
  아직 미구현이며, `content.image_urls`가 채워져야 발행됩니다.
