# 실행 & 실사용 가이드

이 서비스는 `branding` CLI로 동작합니다. 이 문서는 설치부터 무인 운영까지 실제 사용 순서를 다룹니다.

---

## 목차
1. [설치 & 초기화](#1-설치--초기화-최초-1회)
2. [자격증명 발급 — Anthropic / Meta / Threads](#2-자격증명-발급-실사용의-실제-관문)
3. [브랜드·니치 설정](#3-브랜드니치-설정-brandconfigyaml--가장-중요)
4. [실사용 워크플로우](#4-실사용-워크플로우)
5. [무인 운영 (스케줄러)](#5-무인-운영-스케줄러)
6. [학습 루프](#6-학습-루프-참여율-개선의-핵심)
7. [명령어 레퍼런스](#7-명령어-레퍼런스)
8. [트러블슈팅](#8-트러블슈팅)

---

## 1. 설치 & 초기화 (최초 1회)

```bash
git clone https://github.com/ddeokmyeong03/Content_Marketing.git
cd Content_Marketing
pip install -e '.[dev]'          # branding 명령 설치
cp .env.example .env             # 자격증명 입력용
python scripts/setup_db.py       # SQLite DB 초기화 (data/content.db)
```

요구사항: Python 3.11+

---

## 2. 자격증명 발급 (실사용의 실제 관문)

### 2-1. Anthropic API 키 (콘텐츠 생성 — 필수)
1. https://console.anthropic.com → **API Keys** → 키 발급
2. `.env`에 `ANTHROPIC_API_KEY=sk-ant-...`

### 2-2. Meta / Threads 발행 자격증명

발행에는 **액세스 토큰 + 사용자 ID**가 필요합니다. Threads(텍스트)가 가장 간단해 먼저 권장합니다.

#### (A) Meta 앱 만들기
1. https://developers.facebook.com → **My Apps → Create App**
2. 유형: **Business** 선택
3. 생성된 앱의 **App ID / App Secret** 확보 → `.env`의 `META_APP_ID`, `META_APP_SECRET`
   (토큰 자동 갱신에 사용)

#### (B) Threads 발행 토큰 (권장 최단 경로)
1. 앱에 **Threads API** 제품 추가
2. 필요한 권한(scope): `threads_basic`, `threads_content_publish`
3. Threads 계정 연결 후 **액세스 토큰** 발급 → `.env`의 `META_ACCESS_TOKEN`
4. **Threads 사용자 ID** 확인:
   ```bash
   curl "https://graph.threads.net/v1.0/me?fields=id,username&access_token=<TOKEN>"
   ```
   반환된 `id` → `.env`의 `META_THREADS_USER_ID`

#### (C) Instagram 발행 토큰
1. 앱에 **Instagram Graph API** 추가. Instagram은 **비즈니스/크리에이터 계정**이어야 하며 Facebook 페이지에 연결돼 있어야 합니다.
2. 필요한 권한: `instagram_basic`, `instagram_content_publish`, `pages_show_list`
3. **Instagram 비즈니스 계정 ID** 확인:
   ```bash
   curl "https://graph.facebook.com/v21.0/me/accounts?access_token=<TOKEN>"
   # 페이지 id 확보 후:
   curl "https://graph.facebook.com/v21.0/<PAGE_ID>?fields=instagram_business_account&access_token=<TOKEN>"
   ```
   반환된 `instagram_business_account.id` → `.env`의 `META_IG_USER_ID`

> ⚠️ Instagram Graph API는 발행 시 **공개적으로 접근 가능한 이미지 URL**을 요구합니다. 현재 이미지 생성·호스팅은 미구현이라, 실발행은 **Threads(텍스트)** 중심입니다. IG는 `content.image_urls`가 채워져야 발행됩니다.

#### (D) 롱리브드 토큰(60일)으로 교환 & 저장
단기 토큰을 받았다면 60일짜리로 교환하는 게 좋습니다. `.env`에 `META_APP_ID/SECRET`을 넣은 뒤:
```bash
branding token set -p threads -t <SHORT_OR_LONG_TOKEN>   # DB에 저장 (.env보다 우선)
branding token refresh --force                            # 롱리브드로 교환·갱신
branding token show                                       # 만료일 확인
```
스케줄러가 켜져 있으면 만료 임박 시 **자동 갱신**됩니다.

### 2-3. (선택) 알림 채널
Slack/Discord Incoming Webhook URL을 만들어 `.env`의 `NOTIFY_WEBHOOK_URL`에 넣으면 발행 성공/실패·검토 리마인더가 해당 채널로도 전송됩니다.

---

## 2-4. 연결 진단 (문제가 생기면 먼저 이것부터)

키·토큰·계정 ID가 **실제로 동작하는지** 검사하고 해결법을 알려줍니다.

```bash
branding doctor run          # 검사만
branding doctor run --fix    # 올바른 사용자 ID를 찾아 자동 저장
```
웹 대시보드의 **설정·실행 탭 → 🩺 연결 진단** 버튼도 동일하게 동작합니다.

자주 나오는 진단 결과:

| 증상 | 원인 · 해결 |
|------|------------|
| `Failed to decrypt` | Threads 전용 토큰이 아님. Meta 앱 → Use cases → **Threads** 에서 재발급(`threads_basic`) |
| `Cannot parse access token` | 토큰이 잘리거나 공백이 섞임. 전체를 다시 복사 |
| `Object with ID 'xxx' does not exist` | 사용자 ID에 **핸들**을 넣음. `--fix` 가 올바른 **숫자 ID**를 찾아 저장 |
| Instagram 계정 못 찾음 | 프로(비즈니스) 계정 전환 + Facebook 페이지 연결 필요 |

## 3. 브랜드·니치 설정 (`brand/config.yaml`) — 가장 중요

이 파일이 **참여 엔진의 방향**을 결정합니다. 코드 수정 없이 여기만 바꿉니다.

```yaml
niche: "혼자 일하는 1인 창업가를 위한 '진짜 작동하는' 비즈니스 자동화"

audience:                          # 후킹 언어의 원료
  pains: ["혼자 다 하느라 성장할 시간이 없다", "도구만 늘고 더 복잡해졌다"]
  desires: ["일을 줄이고도 매출이 도는 시스템", "핵심에만 집중하는 하루"]
  objections: ["그거 이미 다 아는 얘기 아냐?", "나 같은 소규모엔 안 맞을 듯"]
  sophistication: "중급"            # 초급 | 중급 | 고급

engagement:
  primary_metric: "saves"          # saves | comments | shares | follows ← 훅·CTA 전략을 좌우
  hook_variants: 5                 # 생성·평가할 훅 개수
  min_hook_score: 70               # 미만이면 캡션 1회 자동 재생성 (높일수록 품질↑·비용↑)

psychology:
  intensity: "assertive_factual"   # honest | assertive_factual | aggressive
  levers: [curiosity_gap, loss_aversion, contrarian, social_proof, specificity]
  banned_tactics: ["허위 희소성", "거짓 수치", "낚시성 과장"]

automation:
  auto_approve: false              # false=검토 후 발행 / true=완전 자동
```

확인: `branding brand show`

**튜닝 팁**
- `primary_metric`을 `saves`↔`comments`로 바꾸면 같은 주제도 훅·CTA가 통째로 달라집니다.
- `audience.pains`가 구체적일수록 카피가 날카로워집니다.
- `intensity`: 신뢰 우선이면 `honest`, 바이럴 우선이면 `aggressive`(단 항상 사실 기반).

---

## 4. 실사용 워크플로우

### 방식 A — 수동 검토 (`auto_approve: false`, 초기 권장)
```bash
branding plan generate --captions      # ① 주간 계획 + 캡션 일괄 생성 (참여 엔진 가동)
branding queue list                    # ② DRAFT 목록
branding queue show 1                  #    상세: 훅 5종(기법+점수)·참여 예측 점수·개선 코멘트
branding queue approve 1               # ③ 승인
branding queue reject 2 -r "훅이 약함"  #    또는 거절
branding post now 1                    # ④ 즉시 발행 (또는 스케줄러가 예약 발행)
```

### 방식 B — 단건 즉석 생성 (아이디어 테스트)
```bash
branding post generate -t "번아웃 직전에 깨달은 것" -p instagram --pillar startup_reality
branding post generate -t "같은 주제" --no-optimize    # 최적화 루프 on/off 품질 비교
```

### 방식 C — 완전 자동 (`auto_approve: true`)
생성물이 곧바로 `APPROVED` → 스케줄러가 예약 시각에 자동 발행. 사람 개입 0.

---

## 5. 무인 운영 (스케줄러)

```bash
branding serve run          # 데몬 실행 (Ctrl+C 종료)
branding serve publish-once # 스케줄러 없이 예약 지난 승인글 1회만 발행
```

`serve run`이 등록하는 잡:

| 잡 | 주기 | 하는 일 |
|----|------|---------|
| publish-poll | 5분 | 예약 시각 지난 승인 게시물 발행 |
| weekly-plan | 매주 일 18시 | 다음 주 콘텐츠 자동 생성 |
| token-refresh | 매일 3시 | 만료 임박 토큰 갱신 |
| insights-sync | 매일 4시 | 발행 성과 수집 |
| review-reminder | 매일 (설정 시각) | 검토 대기 알림 (수동 모드) |

> 실서버 상주: `nohup branding serve run &` 또는 systemd/pm2. 주기·시각은 `.env`에서 조정(`PUBLISH_POLL_MINUTES`, `WEEKLY_PLAN_CRON_*`, `TOKEN_REFRESH_HOUR`, `INSIGHTS_SYNC_HOUR`).

---

## 5-1. 운영 대시보드 (웹 UI)

CLI 대신 브라우저에서 검토·승인과 성장 분석을 보려면:

```bash
pip install -e '.[web]'      # fastapi + uvicorn
branding web run             # http://127.0.0.1:8000
```

탭: **개요**(큐 카운트·팔로워·성장), **검토 큐**(게시물 클릭→상세→승인/거절),
**성장 분석**(브레이크아웃·성장 귀인), **승리 공식**(역설계된 재현 공식).
DFY 운영자가 여러 고객 계정을 검토·리포트할 때 유용합니다.

## 6. 학습 루프 (참여율 개선의 핵심)

```bash
branding insights sync    # 발행글 실제 성과(저장·댓글·공유·도달) 수집
branding insights top     # 참여율 상위 콘텐츠 확인
```

수집된 상위 성과 주제·훅은 **다음 `plan generate`에 자동 재주입**되어, 먹힌 각도를 엔진이 점점 더 잘 뽑습니다. 이것이 이 시스템의 자기개선 고리입니다.

### 추천 운영 사이클
```
[주 1회] plan generate --captions      → 주간 콘텐츠 일괄 생성
[매일]   queue list → show → approve    → 검토·승인
[상시]   serve run                      → 예약 발행 자동
[주 1회] insights sync → top            → 성과 확인 후 config 튜닝
```
익숙해지면 `auto_approve: true` + `serve run` 상주로 완전 무인 전환.

---

## 7. 명령어 레퍼런스

| 명령 | 설명 |
|------|------|
| `branding brand show` | 브랜드/니치 설정 확인 |
| `branding plan generate [--week YYYY-MM-DD] [--captions]` | 주간 계획(+캡션) 생성 |
| `branding plan show` | 최근 계획 확인 |
| `branding post generate -t <주제> [-p] [--pillar] [-m] [--optimize/--no-optimize]` | 단건 캡션 생성 |
| `branding post now <id>` | 즉시 발행 |
| `branding queue list [-s draft\|approved\|published\|all]` | 큐 목록 |
| `branding queue show <id>` | 상세 (훅·참여점수 포함) |
| `branding queue approve <id>` / `reject <id> [-r 사유]` | 승인 / 거절 |
| `branding token set -p <platform> -t <token>` / `show` / `refresh [--force]` | 토큰 관리 |
| `branding insights sync` / `top [-w 주] [-n 개수]` | 성과 수집 / 상위 성과 |
| `branding serve run` / `publish-once` | 스케줄러 / 1회 발행 |

- 플랫폼: `instagram`, `threads`
- 콘텐츠 기둥(pillar): `startup_reality`, `automation_tips`, `business_growth`, `mindset`
- 미디어(`-m`): `text`, `image`, `carousel`, `reel`, `story`

---

## 8. 트러블슈팅

| 증상 | 원인 / 해결 |
|------|-------------|
| `ANTHROPIC_API_KEY 없음` | `.env`에 키 입력 |
| Threads는 되는데 IG 발행 안 됨 | IG는 공개 이미지 URL 필요 → 이미지 생성·호스팅 미구현. 현재 실발행은 Threads 중심 |
| 발행 FAILED | `queue show <id>`로 상태·에러 확인, 토큰/유저ID 점검 후 `post now <id>` 재시도 |
| 토큰 만료 | `branding token refresh --force` (앱 자격증명 필요), 또는 새 토큰 `token set` |
| 품질이 아쉬움 | `audience.pains` 구체화 + `min_hook_score` 상향 + `levers` 조정 |
| 테스트 | `pytest -q` (전 구간 오프라인 모킹) |
