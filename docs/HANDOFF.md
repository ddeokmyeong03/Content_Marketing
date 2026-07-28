# 진행 상황 · 인수인계 (HANDOFF)

> 세션이 바뀌어도 이어서 작업할 수 있도록 **현재 상태·결정사항·미해결 이슈**를 기록한다.
> 프로젝트 규칙·아키텍처는 루트 `CLAUDE.md`, 기능 설계는 `docs/` 참조.
> **최종 갱신**: 댓글 응대 자동화 커밋(`4ce396b`) 시점

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

### 문서
- [x] `USAGE.md`(설치·자격증명 발급·워크플로우·트러블슈팅)
- [x] `GROWTH_ANALYSIS.md`(BGI 설계 P1~P6)
- [x] `BUSINESS.md`(DFY 전략·Beachhead·가격)
- [x] `PITCH.md`(서비스 정의·광고 이미지 프롬프트·랜딩페이지 프롬프트)

**테스트 87건, 전부 오프라인(네트워크 모킹).** `pytest -q`

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
4. **이미지 파이프라인 미구현** — Instagram 발행의 마지막 블로커(`content.image_urls`가 빔)
   - 실험 결과: Higgsfield(nano_banana)로 생성은 되고 **공개 CDN URL이 자동으로 나옴**(호스팅 해결됨)
   - 단 **한글 텍스트 렌더링 품질 미검증**(사용자 확인 필요). 유료 모델(GPT Image 2, Recraft)은 무료 플랜에서 차단
   - **권장 방향**: 텍스트 카드는 HTML/CSS → 헤드리스 크로미엄 PNG 렌더(한글 완벽·브랜드 일관),
     일러스트/배경만 AI. 렌더한 PNG는 업로드해 공개 URL 확보
5. **캐러셀 슬라이드 구조 없음** — 현재 `caption + image_brief`뿐. 슬라이드별 레이아웃·글자수·강조를
   통제하려면 데이터 모델 확장 필요(이미지 파이프라인의 전제)
6. **타깃 발굴 미구현** — 사용자 요청이었으나 보류.
   해시태그 검색·business_discovery(읽기 전용, 공식 지원)로 **브랜드 적합 계정·게시물을 찾아
   일일 실행 체크리스트 생성** → 실제 팔로우·좋아요는 사람이 실행 (ToS 준수)

### 🟡 알아둘 것
7. **이 컨테이너에서는 Meta/Anthropic 실 API 호출 불가** — egress 프록시가 차단(403). 실검증은 사용자 로컬에서
8. **커밋 서명 경고는 오탐** — 세션에 `allowedSignersFile`이 없어 로컬 검증이 불가할 뿐,
   커밋은 `noreply@anthropic.com`으로 정상 서명·푸시됨. 재-amend해도 동일하므로 무시할 것

---

## 4. 다음 작업 후보 (우선순위 제안)

1. **이미지 파이프라인** — 텍스트카드 템플릿 렌더러 + 캐러셀 슬라이드 모델 (IG 발행 완성)
2. **타깃 발굴 + 일일 체크리스트** — 도달 확대의 남은 조각
3. **실계정 라이브 검증** — 토큰 해결 후 Threads 발행 → 며칠 뒤 `insights sync` → BGI 폐루프 실동작 확인
4. **SaaS 전환 준비** — 멀티테넌트(계정별 DB/설정), 인증, 잡 큐 교체

---

## 5. 새 세션 시작 시 붙여넣을 프롬프트 (예시)

```
Content_Marketing 리포의 claude/automation-implementation-details-hlhzof 브랜치에서
이어서 작업합니다. 루트 CLAUDE.md와 docs/HANDOFF.md를 먼저 읽고 현재 상태를 파악해 주세요.

이번에 할 일: [예: HANDOFF 4번의 '이미지 파이프라인'을 진행]
```
