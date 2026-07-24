# Breakout Growth Intelligence (BGI) — 설계 문서

> **목적**: "성과 지표를 보여주기"에서 멈추지 않고, **팔로워 대비 압도적으로 뜬 게시물(브레이크아웃)이 왜 떴고, 그것이 어떻게 계정 성장으로 이어졌는지**를 자동 역설계하고, 그 '승리 공식'을 다음 콘텐츠에 재주입한다. 시중 도구에 거의 없는 차별점.

이 문서는 설계 스펙이며, 단계별로 구현한다. (본 커밋 시점 구현 범위는 **§9 P1**.)

---

## 1. 개념 & 시장 갭

대부분의 소셜 분석 도구는 지표(도달·좋아요·저장)를 **나열**한다. BGI는 다르다:

```
성과 수집(기존) → ① 브레이크아웃 탐지 → ② 성장 귀인 → ③ AI 역설계(왜 떴나)
                                                          ↓
      ⑤ 엔진 자동 반영 ← ④ '승리 공식' 라이브러리 ←───────┘
```

핵심: **팔로워 대비 정규화된 이상치**를 찾고, 그 확산·성장 메커니즘을 구조로 분해해 재현 가능한 공식으로 축적한다.

## 2. 브레이크아웃 "정의" (측정 가능하게)

감이 아니라 수치로 정의한다. 팔로워 대비 정규화가 핵심.

**정규화 지표 (게시 시점 팔로워 기준)**
- `reach_rate = reach / followers_at_post` — 팔로워 밖 확산 정도
- `share_rate = shares / reach`
- `save_rate = saved / reach`
- `follow_rate = follows_from_post / reach` (IG는 직접, Threads는 근사)
- `interaction_rate = total_interactions / reach`

**이상치 점수 (로버스트 z-score)**
```
median, MAD = 최근 N개(동일 플랫폼/포맷) 게시물의 지표 분포
z = (metric - median) / (1.4826 * MAD)
breakout = z >= Z_THRESHOLD   # 기본 2.5~3.0
```
- 성장 직결 지표(`share_rate`, `follow_rate`, `reach_rate`)에 **가중** → 단순 좋아요 이상치보다 "오디언스 확장" 신호를 우선.
- `breakout_score` = 가중 z-score들의 결합 점수(0~100 정규화).

## 3. 아키텍처 (기존 코드에 부착)

| Phase | 내용 | 신규/확장 |
|-------|------|-----------|
| **P1** ✅ 데이터 기반 | 계정 스냅샷 + 포스트 지표 확장(profile_visits/follows/total_interactions) | `account_metrics` 테이블, `PostMetric` 확장, `InsightsService.sync_account` |
| **P2** ✅ 탐지 | 이상치 점수·브레이크아웃 판정 (로버스트 z-score, MAD→std 폴백) | `analysis/breakout.py`, `analysis/service.py`, `insights breakouts` |
| **P3** ✅ 역설계 | AI 구조 분해 → 승리 공식 저장 | `ai/deconstruct.py`, `breakout_patterns` 테이블, `insights deconstruct`/`patterns` |
| **P4** ✅ 귀인 | 팔로워 순증가를 게시물 propensity로 분배 | `analysis/attribution.py`, `insights attribution` |
| **P5** ✅ 반영 (폐루프 완성) | 승리 공식을 plan/caption 프롬프트에 재주입 | `content_service`가 `BreakoutPatternRepository.top`을 planner/caption에 주입 |
| **P6**(확장) | 외부/경쟁사 바이럴 반자동 분해 | 운영자 URL·샘플 투입 → AI 분해 |

## 4. 데이터 모델

### account_metrics (P1)
```
id, platform, fetched_at,
followers_count, reach, profile_views, views,
raw_json
```
매일 스냅샷 → 팔로워/도달 시계열 확보(귀인의 기반).

### post_metrics 확장 (P1)
기존 likes/comments/shares/saved/reach/views + 추가:
```
profile_visits, follows, total_interactions
```

### breakout_patterns (P3)
```
id, post_id, detected_at, breakout_score,
hook_type, psychology_levers(json), format, topic_angle,
structure_notes, emotional_trigger, spread_hypothesis,
replicable_formula, confidence, metrics_snapshot(json)
```

## 5. AI 역설계 출력 스키마 (P3)

브레이크아웃 게시물 + 지표 → Claude tool_use로 구조 분해:
- `hook_type`, `psychology_levers[]`, `format`, `topic_angle`
- `structure_notes` — 서사 구조
- `emotional_trigger` — 핵심 감정 레버
- `spread_hypothesis` — "왜 공유/저장/팔로우로 이어졌나" 가설
- `replicable_formula` — 재현 템플릿(다음 콘텐츠에 주입 가능한 형태)
- `confidence` (0-100)
- (서브) 댓글 분석 — 어떤 댓글/답글 패턴이 상호작용을 증폭했나

## 6. 성장 귀인 (P4)

- `account_metrics`의 팔로워 델타를 일자별로 계산
- 브레이크아웃 게시물 발행일 ±window와 팔로워 급증 구간 상관
- IG: 게시물 `follows` 지표로 직접 귀인 / Threads: 팔로워 델타 근사 귀인
- 산출: "이 게시물이 유입에 기여한 추정 팔로워 수"

## 7. 엔진 반영 (P5, 폐루프 완성)

- 승리 공식 라이브러리 → `plan`/`caption` 프롬프트에 "이 계정에서 검증된 공식" 블록으로 주입
- 브레이크아웃과 상관 높은 **기둥·레버 가중치 조정 제안** → DFY에선 운영자 승인 후 반영(자동 반영은 auto 모드 옵션)

## 8. API 실현성 & 한계 (솔직히)

- **본 계정(전문계정)**: IG 미디어 인사이트(reach, saved, shares, total_interactions, profile_visits, follows) + 계정 인사이트(follower_count, reach, profile_views) 확보 가능 → **P1~P5 완전 자동화 가능**.
- **Threads**: 게시물(views, likes, replies, reposts, quotes) + 계정(followers_count, views). 게시물발 팔로우 직접 지표 없음 → 팔로워 델타로 근사.
- **외부/경쟁사**: 공식 API로 타인의 도달·저장 인사이트 불가. 공개 좋아요/댓글 수만 가시. 스크래핑은 ToS 리스크 → **P6은 운영자가 바이럴 예시(텍스트/스크린샷/URL)를 투입하면 AI가 구조만 분해하는 반자동**으로 설계(완전 자동 아님).

## 9. P1 구현 범위 (이번 단계)

**데이터 기반**만 구축한다. 탐지/역설계(P2·P3)는 이 데이터 위에서 다음 단계.

1. `account_metrics` 테이블 + `AccountMetricsRepository`(스냅샷 저장/시계열 조회)
2. `PostMetric`에 `profile_visits`, `follows`, `total_interactions` 추가 + DB 마이그레이션(ALTER)
3. `InsightsService`:
   - 게시물 인사이트에 위 3개 지표 추가 수집(IG)
   - `sync_account()`: 계정 팔로워·도달·프로필뷰 스냅샷 수집
4. 스케줄러 `insights-sync` 잡에서 계정 스냅샷도 함께 수집
5. CLI: `branding insights account`(현재 스냅샷·성장 추이), `insights sync`가 계정도 수집
6. 테스트: 계정 스냅샷 저장/추이, 확장 지표 라운드트립, 계정 인사이트 파싱

**P1 완료 시 얻는 것**: 브레이크아웃 탐지·귀인에 필요한 시계열 데이터가 매일 쌓이기 시작 → P2 이후를 즉시 올릴 수 있는 토대.

## 10. DFY 상품화 연계

BGI는 그 자체로 **프리미엄 "성장 리포트"** 상품:
> "당신 계정에서 터진 게시물이 왜 터졌고, 그 공식을 다음 콘텐츠에 어떻게 심는가"를 월간 리포트 + 자동 반영.

→ 가치 기반 가격의 명분 강화 + 계정별 승리공식 축적 = **데이터 해자·이탈 방지**. (BUSINESS.md §11 참조)
