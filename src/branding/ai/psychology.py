"""행동심리 · 카피라이팅 지식 베이스.

참여율(저장/댓글/공유/팔로우)을 끌어올리는 언어 기법을 구조화해,
프롬프트에 '활성화된 레버'만 골라 주입한다. 브랜드 config가 어떤 레버를
켤지 결정하므로, 니치/톤이 바뀌어도 코드 변경 없이 조정 가능하다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lever:
    id: str
    name_ko: str
    how_ko: str          # 적용 방법
    example_ko: str      # 짧은 예시


# --- 행동심리 레버 라이브러리 ---
LEVERS: dict[str, Lever] = {
    "curiosity_gap": Lever(
        "curiosity_gap", "호기심 갭",
        "답을 바로 주지 말고 '알아야 할 이유'를 먼저 열어 정보 공백을 만든다. 첫 줄에서 궁금증을 유발하고 본문에서 해소한다.",
        "'매출이 3배 뛴 건 이걸 멈추고 나서였습니다.' — 무엇을 멈췄는지는 본문에서.",
    ),
    "open_loop": Lever(
        "open_loop", "오픈 루프",
        "끝까지 읽게 만드는 미완결 서사를 건다. '3가지 중 마지막이 핵심'처럼 뒤를 예고한다.",
        "'세 번째 실수가 가장 뼈아팠습니다.' → 순서대로 풀되 마지막을 강조.",
    ),
    "loss_aversion": Lever(
        "loss_aversion", "손실 회피",
        "얻는 것보다 '잃고 있는 것/놓치는 비용'을 부각한다. 사람은 이득보다 손실에 2배 민감하다.",
        "'이 습관 하나가 매달 20시간을 조용히 훔쳐가고 있습니다.'",
    ),
    "social_proof": Lever(
        "social_proof", "사회적 증거",
        "구체적 수치·사례·'다들 이렇게 한다'로 안전함을 준다. 단, 사실만.",
        "'같은 방식으로 바꾼 뒤 첫 100명 고객을 광고 없이 모았습니다.'",
    ),
    "specificity": Lever(
        "specificity", "구체성",
        "추상어 대신 숫자·고유명사·장면을 쓴다. 구체성은 신뢰와 저장률을 동시에 올린다.",
        "'생산성이 올랐다' 대신 '월요일 오전 4시간을 통째로 되찾았다'.",
    ),
    "pattern_interrupt": Lever(
        "pattern_interrupt", "패턴 인터럽트",
        "예상을 깨는 첫 문장으로 스크롤을 멈춘다. 통념을 뒤집거나 의외의 고백으로 시작한다.",
        "'열심히 일할수록 사업이 망가지고 있었습니다.'",
    ),
    "identity_belonging": Lever(
        "identity_belonging", "정체성·소속감",
        "'우리 같은 사람들'의 정체성을 호명해 공유·팔로우를 부른다.",
        "'혼자 다 하려는 1인 창업가라면 이 이야기가 당신 겁니다.'",
    ),
    "contrarian": Lever(
        "contrarian", "역발상",
        "널리 믿는 조언을 근거와 함께 반박한다. 댓글·논쟁을 유발한다(사실 기반 한정).",
        "'\"일단 실행하라\"는 조언이 저를 6개월 늦췄습니다.'",
    ),
    "future_pacing": Lever(
        "future_pacing", "미래 투영",
        "독자가 원하는 결과를 이미 이룬 장면을 생생히 그려 욕망을 자극한다.",
        "'상상해보세요. 알림을 꺼도 매출이 들어오는 아침을.'",
    ),
    "cost_of_inaction": Lever(
        "cost_of_inaction", "방치 비용",
        "'지금 안 바꾸면 1년 뒤'의 대가를 구체화해 행동을 촉구한다.",
        "'이 결정을 미룬 1년, 저는 같은 실수를 12번 반복했습니다.'",
    ),
    "authority": Lever(
        "authority", "권위·경험",
        "직접 겪은 데이터·실전 경험으로 말할 자격을 증명한다. 잘난 척이 아니라 증거로.",
        "'3개 제품을 말아먹고 나서야 알게 된 것.'",
    ),
}

# --- 훅(첫 문장) 분류법 ---
HOOK_TYPES: dict[str, str] = {
    "number_hook": "숫자 훅 — '3가지 실수', '단 1가지 습관'처럼 목록/수치로 기대를 건다.",
    "question_hook": "질문 훅 — 독자의 고통을 정확히 찌르는 질문으로 시작한다.",
    "contrarian_hook": "역발상 훅 — 통념을 뒤집는 선언으로 스크롤을 멈춘다.",
    "mistake_hook": "실수 고백 훅 — '제가 틀렸습니다' 식의 취약성으로 신뢰와 궁금증을 만든다.",
    "result_hook": "결과 훅 — 구체적 성과를 먼저 던지고 '어떻게'를 예고한다.",
    "story_hook": "스토리 훅 — 특정 순간/장면으로 몰입시켜 서사를 연다.",
    "callout_hook": "지목 훅 — '~하는 당신에게'로 타깃을 직접 호명한다.",
}

# --- 핵심 지표 → CTA 전략 매핑 ---
METRIC_CTA: dict[str, str] = {
    "saves": "나중에 다시 보게 만드는 '저장' 유도. 예: '두고두고 보게 될 겁니다. 저장해 두세요.' 체크리스트/단계형 정보로 레퍼런스 가치를 높인다.",
    "comments": "의견·경험을 부르는 '댓글' 유도. 예: '당신은 어느 쪽인가요? 댓글로 알려주세요.' 답하기 쉬운 양자택일/경험 질문을 던진다.",
    "shares": "'이거 너 얘기야'식 공유 유도. 예: '이런 사람 떠오르면 공유해 주세요.' 강한 공감·정체성 문장을 심는다.",
    "follows": "다음 편을 기대하게 만드는 '팔로우' 유도. 예: '이런 이야기를 매주 풉니다. 팔로우해 두세요.' 시리즈성·기대감을 건다.",
}

INTENSITY_GUIDE: dict[str, str] = {
    "honest": "정직한 설득. 과장·낚시 금지. 구체성과 명료함으로만 설득한다. 신뢰 최우선.",
    "assertive_factual": "적극적 후킹. 강한 호기심 갭·감정 트리거·논쟁적 각도 허용하되, 모든 주장은 반드시 사실에 근거한다. 클릭베이트성 과장·허위 희소성은 금지.",
    "aggressive": "공격적 바이럴. 강한 도발·역발상·감정 극대화를 우선하되, 여전히 거짓 사실·허위 수치는 금지한다.",
}


def render_levers(lever_ids: list[str]) -> str:
    """활성 레버를 프롬프트용 텍스트로 렌더링."""
    lines = []
    for lid in lever_ids:
        lever = LEVERS.get(lid)
        if lever:
            lines.append(f"- **{lever.name_ko}**: {lever.how_ko}\n  예: {lever.example_ko}")
    return "\n".join(lines) if lines else "- (지정된 레버 없음 — 구체성과 명료함을 기본으로)"


def render_hook_types(hook_type_ids: list[str] | None = None) -> str:
    ids = hook_type_ids or list(HOOK_TYPES.keys())
    return "\n".join(f"- {HOOK_TYPES[h]}" for h in ids if h in HOOK_TYPES)


def cta_strategy(primary_metric: str) -> str:
    return METRIC_CTA.get(primary_metric, METRIC_CTA["saves"])


def intensity_guide(intensity: str) -> str:
    return INTENSITY_GUIDE.get(intensity, INTENSITY_GUIDE["assertive_factual"])
