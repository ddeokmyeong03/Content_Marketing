# 진행 상황 · 인수인계 (HANDOFF)

> 세션이 바뀌어도 이어서 작업할 수 있도록 **현재 상태·결정사항·미해결 이슈**를 기록한다.
> 프로젝트 규칙·아키텍처는 루트 `CLAUDE.md`, 기능 설계는 `docs/` 참조.
> **최종 갱신**: 운영 내구성 3종(발행 재시도 · BGI 콜드스타트 · IG 폴링/캐러셀) 시점

---

## 1. 지금까지 완료된 것

### 기반 자동화
- [x] Publisher — Threads(텍스트) / Instagram(단일·카루셀) 발행, 상태 전이·로그
- [x] Scheduler — 6개 잡: `publish-poll` `weekly-plan` `token-refresh` `insights-sync` `comment-cycle` `review-reminder`
- [x] 토큰 자동 갱신(롱리브드 60일), 알림(콘솔/Slack 웹훅)
- [x] 초기 버그 수정: 잘못된 모델 ID, 타임존 불일치, `recent_topics` 미연결, `auto_approve` 미반영

### 참여 엔진 (제품의 본질)
- [x] `brand/config.yaml`에 니치·청중(고통/욕망/반론)·심리레버·목표지표·설득강도 추가
- [x] `ai/psychology.py` — 행동심리 레버 11종 + 훅 분류법 + 지표별 CTA 전략
- [x] 프롬프트 재설계(다이렉트 리스폰스 카피라이터 역할)
- [x] 훅 N개 생성 + 자기예측 점수 → 최적 채택
- [x] 루브릭 자기평가 → `min_hook_score` 미달 시 1회 개선 재생성

### BGI (Breakout Growth Intelligence) — P1~P6 전부 완료
- [x] P1 데이터 기반: `account_metrics` 스냅샷 + 게시물 성장 지표(profile_visits/follows/total_interactions)
- [x] P2 탐지: 팔로워 정규화 이상치, 로버스트 z-score(MAD→std 폴백)
- [x] P3 역설계: 브레이크아웃 → 훅유형·심리레버·확산가설·**재현 공식**
- [x] P4 귀인: 팔로워 순증가를 게시물에 분배("이 글이 N명 데려옴")
- [x] P5 재주입: 승리 공식을 기획·캡션 프롬프트에 자동 주입 → **폐루프 완성**
- [x] P6 외부 바이럴 반자동 분해 (`insights external`)

### 계정 활성화 (도달 개선)
- [x] 댓글 수집(IG `/comments`, Threads `/replies`) + AI 브랜드톤 답글 초안 + 스팸 자동 무시
- [x] 답글 발행(IG `/{comment-id}/replies`, Threads `reply_to_id`)
- [x] 골든아워 알림(발행 직후 N분 집중 응대 안내)

### 운영 UI
- [x] FastAPI 대시보드: 개요 / 검토 큐 / 댓글 응대 / 성장 분석 / 승리 공식 / 설정·실행
- [x] 웹에서 API 키 등록(`settings_store`, `.env`보다 우선) — SaaS 전환 시 재사용 가능한 액션 계층
- [x] 백그라운드 잡 + 진행률 폴링, 팔로워 추이 차트(자체 SVG)
- [x] 연결 진단(`branding doctor run --fix`) — 토큰·ID 검증 및 올바른 숫자 ID 자동 탐색·저장

### 운영 내구성 (라이브 검증 대비)
- [x] **발행 재시도 2겹** — `GraphHTTP` 요청 단위 지수 백오프 + `next_retry_at` 예약으로
      잡 주기 단위 재시도. 일시 오류(레이트 리밋·5xx·네트워크)와 영구 오류(토큰·권한)를
      `MetaAPIError.retryable`로 구분. 이전에는 **순간 장애 하나로 예약 게시물이 영구히 죽었음**
- [x] **BGI 콜드스타트** — 표본 8개 미만이면 잠정 판정 모드(중앙값 대비 배수) + 신뢰도 표기,
      3개 미만이면 판정 보류. `insights breakouts`가 "정식 판정까지 N개 더 필요"를 알림.
      `BreakoutService.coverage()` / `GET /api/breakouts/coverage`로 진단
- [x] **IG 컨테이너 폴링** — 고정 5초 대기를 `status_code=FINISHED` 폴링으로 교체
      (캐러셀은 자식 컨테이너까지 전부). 타임아웃은 재시도 대상으로 처리
- [x] **캐러셀 슬라이드 모델** — `CarouselSlide`(index/role/headline/body/emphasis/
      image_brief/image_url)로 슬라이드별 문구·순서·강조를 데이터로 통제. 일부만 렌더링된
      경우 빠진 슬라이드 번호를 알리고 반쪽 발행을 막음

### 캐러셀 카드 파이프라인 (IG 발행의 마지막 조각)
- [x] **슬라이드 문구 생성(1a)** — 캐러셀이면 `caption_gen`이 `slides[]`를 함께 생성
      (역할·헤드라인·보조문구·강조). 글자수 한도를 config에서 프롬프트로 주입해
      '카드에 실제로 들어가는 분량'을 통제. 없는 강조 문자열은 파싱에서 제거
- [x] **텍스트 카드 렌더러(1b)** — `render/card.py`(HTML 생성, 순수 함수) +
      `render/png.py`(헤드리스 크로미엄) + `render/service.py`(오케스트레이션).
      한글 렌더링 실물 확인 완료. 긴 문구는 폰트 크기 자동 축소, 저대비 팔레트에서도
      보이도록 강조에 밑줄. `branding render check/sample/slides`
- [x] **업로드(1c)** — 렌더 PNG → 공개 URL. `Uploader` 추상화 + `dir`(정적서버)·`s3`(S3호환:
      AWS/R2/B2/MinIO) 구현. 미렌더 슬라이드는 업로드 전에 번호로 알림. **IG 발행 블로커 해소**
- [x] **검토 큐 슬라이드 표시(1d)** — 대시보드 상세에 슬라이드 문구·강조·렌더 미리보기
      (클릭 시 원본)·상태(미렌더/렌더됨/업로드됨)와 발행 가능 여부 표시

**캐러셀 전체 흐름이 연결됨**: `plan generate --captions`(문구) → `render slides`(PNG) →
`upload slides`(공개 URL) → `queue approve` → `post now`. 실제로 끝까지 이어지는 것을 확인함.

### 보안 (DFY 고객 수용 전 필수 조건)
- [x] **자격증명 저장 암호화** — `settings_store`·`token_store` 값을 Fernet으로 암호화.
      키는 `BRANDING_SECRET_KEY` 또는 `{DATA_DIR}/.secret_key`(0600, 자동 생성).
      기존 평문 DB는 그대로 읽히고 `secrets migrate` 로 일괄 전환.
      **막는 것**: DB 유출·백업 노출·실수 커밋 / **못 막는 것**: 호스트 장악
- [x] **대시보드 인증** — `WEB_AUTH_PASSWORD` 설정 시 전 엔드포인트 HTTP Basic.
      미설정 시 루프백 바인딩만 허용하고 `--host 0.0.0.0` 은 거부 →
      **인증 없는 콘솔이 공개되는 경로 자체를 없앰**
- [x] `.secret_key` 를 `.gitignore` 에 추가

### 타깃 발굴 (도달 확대)
- [x] 해시태그 검색(`ig_hashtag_search` → `top_media`) + `business_discovery` — 공식 읽기 전용
- [x] 우선순위 점수(순수계산) — 게시물은 **코호트 상대 평가**(해시태그마다 반응 규모가
      달라 절대값 비교는 무의미) + 최근성 + 과밀 페널티(댓글 수백 개면 내 댓글이 묻힘),
      계정은 팔로워 구간 적합도 + 참여율
- [x] 일일 실행 체크리스트 + `done`/`skip` 상태 관리. 재발굴해도 **사람의 판단은 덮어쓰지 않음**
- [x] 해시태그 주간 한도(7일 고유 30개) 추적 — 소진 전에 멈추고 남은 여유를 알림
- [x] **실행은 사람이** — 팔로우·좋아요 자동화 없음(ToS 준수)

### 문서
- [x] `USAGE.md`(설치·자격증명 발급·워크플로우·트러블슈팅)
- [x] `GROWTH_ANALYSIS.md`(BGI 설계 P1~P6)
- [x] `BUSINESS.md`(DFY 전략·Beachhead·가격)
- [x] `PITCH.md`(서비스 정의·광고 이미지 프롬프트·랜딩페이지 프롬프트)

**테스트 250건, 전부 오프라인(네트워크 모킹).** `pytest -q`
(PNG 굽기 2건만 브라우저 필요 — 없으면 자동 skip되어 248 통과)

---

## 2. 확정된 전략 결정 (재논의 불필요)

| 항목 | 결정 |
|------|------|
| 진입 모델 | **DFY(대행) 우선** → 이후 SaaS 전환 |
| 플랫폼 | **Instagram + Threads** 확정 |
| 가격 | **가치 기반** (셋업 + 월 리테이너 + 선택적 성과 보너스) |
| Beachhead | **한국 1인 지식창업가**(코치·컨설턴트·온라인 강사), 팔로워 1천~2만 |
| 킬러 메시지 | "터진 게시물이 왜 터졌는지, 알고 계신가요?" |

---

## 3. 미해결 이슈 (다음 세션에서 이어서 처리)

### 🔴 즉시
1. **Threads 토큰 연결 실패** — 사용자가 실제 테스트 중 막힌 지점
   - 겪은 에러: `Object with ID 'auto._.duck' does not exist`(핸들을 ID로 입력) →
     `Invalid OAuth access token`(토큰 파싱 실패) → `Failed to decrypt`(Threads 전용 토큰 아님)
   - **해결 경로**: 로컬 PC에서 `branding doctor run --fix` 실행 (컨테이너에서는 프록시가
     Meta API를 403으로 막아 실검증 불가)
   - Meta 앱 → Use cases → **Threads** 에서 `threads_basic` + `threads_manage_replies` 권한으로 재발급 필요
2. **노출된 자격증명 폐기 필요** — 대화 중 GitHub PAT와 Meta 토큰이 평문 노출됨. 둘 다 재발급 권장
3. ~~`main` 미병합~~ → **해결됨.** `main`에 fast-forward 병합 완료(`2108179`).
   이제 `main`과 작업 브랜치가 동일하며, Codespace에서 `git pull` 하면 전체 코드가 보인다.

### 🟠 기능 공백
4. ~~이미지 파이프라인~~ → **해결됨.** 문구 생성 → 렌더 → 업로드 → 발행이 전부 연결됨.
   남은 것은 **실 저장소 검증** — `dir` 업로더는 로컬에서 검증했으나 S3/R2는
   실 자격증명으로 확인이 필요하다(이 컨테이너에서는 불가). `branding upload check` 로 점검할 것
   - 텍스트 없는 배경/일러스트가 필요하면 그 부분만 AI 이미지로 (한글이 없으니 안전)
5. ~~캐러셀 슬라이드 구조 없음~~ → **해결됨.** `CarouselSlide` 모델 + 발행 경로 연결 완료
6. ~~타깃 발굴 미구현~~ → **해결됨.** 해시태그 검색·business_discovery(공식 읽기 전용)로
   후보를 찾아 점수화하고 일일 체크리스트 생성. 실행은 사람이(ToS 준수).
   해시태그 주간 30개 한도를 추적해 소진 전에 멈춘다

### 🟡 알아둘 것
7. **이 컨테이너에서는 Meta/Anthropic 실 API 호출 불가** — egress 프록시가 차단(403). 실검증은 사용자 로컬에서
8. **커밋 서명 경고는 오탐** — 세션에 `allowedSignersFile`이 없어 로컬 검증이 불가할 뿐,
   커밋은 `noreply@anthropic.com`으로 정상 서명·푸시됨. 재-amend해도 동일하므로 무시할 것

---

## 4. 다음 작업 후보 (우선순위 제안)

1. **실계정 라이브 검증** — 토큰 해결 후 Threads 발행 → 며칠 뒤 `insights sync` →
   BGI 폐루프 실동작 확인. **가장 비싼 가정(폐루프가 의미 있는 공식을 뽑는가)을
   가장 싸게 검증하는 단계.** 발행 재시도가 들어갔으므로 무인 운영을 걸어도 안전
2. **키 로테이션** — 마스터 키가 유출됐을 때 갈아끼우는 절차가 없다(현재는 기존 키로
   복호화 → 새 키로 재암호화를 손으로 해야 함). `secrets rotate --old-key` 추가 필요
3. **타깃 발굴 실 API 검증** — 구현은 끝났으나 실제 해시태그 검색·business_discovery를
   호출해 보지 못했다. 특히 **주간 30개 한도는 소진하면 일주일을 기다려야 하므로**
   처음에는 해시태그를 1~2개로 시작할 것
4. **`Platform.BOTH` 원자성** — IG 성공 후 Threads 실패 시 재시도하면 IG에 중복 발행
5. **SaaS 전환 준비** — 멀티테넌트(계정별 DB/설정), 인증, 잡 큐 교체

### 알아둘 것 (이번 작업에서 확인)
- **Threads 퍼블리셔는 여전히 고정 5초 대기**를 쓴다. IG처럼 폴링으로 바꾸는 것이
  맞지만, 실 API로 응답 필드(`status`)를 확인할 수 없어 보류했다. 라이브 검증 때
  같이 확인할 것
- `Platform.BOTH` 발행은 원자적이지 않다 — IG 성공 후 Threads 실패 시 전체가 FAILED가
  되고 재시도하면 IG에 중복 발행된다. 플랫폼별 발행 결과를 따로 기록하는 모델 확장 필요
- **S3/R2 업로더는 실 자격증명으로 검증하지 못했다** — 스텁 클라이언트로 호출 형태만
  확인했다. 첫 사용 전에 `branding upload check` 와 실제 1회 업로드로 확인할 것
- 업로드는 `slide.image_url`을 채울 뿐 **공개 접근 가능 여부는 확인하지 않는다**.
  버킷이 비공개면 발행 단계에서 Meta가 이미지를 못 가져와 실패한다
- **암호화는 저장 시점만 보호한다.** 실행 중에는 메모리에 평문이 있고, 키가 같은
  호스트에 있으므로 호스트가 장악되면 소용없다. 호스트 접근 통제는 별개 문제
- **HTTP Basic은 ASCII만 전달한다** — 한글 비밀번호를 쓰면 로그인이 되지 않는다.
  설정 시 경고 로그를 남기도록 해 뒀지만, Basic 인증 자체의 한계다
- 대시보드를 외부에 노출한다면 **HTTPS는 별도로 구성해야 한다**(리버스 프록시).
  Basic 인증은 평문 전송이라 HTTP로 노출하면 비밀번호가 그대로 흐른다

---

## 5. 새 세션 시작 시 붙여넣을 프롬프트 (예시)

```
Content_Marketing 리포의 claude/automation-implementation-details-hlhzof 브랜치에서
이어서 작업합니다. 루트 CLAUDE.md와 docs/HANDOFF.md를 먼저 읽고 현재 상태를 파악해 주세요.

이번에 할 일: [예: HANDOFF 4번의 '이미지 파이프라인'을 진행]
```
