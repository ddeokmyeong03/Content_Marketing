from branding.ai import psychology


def test_render_levers_includes_known_and_skips_unknown():
    text = psychology.render_levers(["curiosity_gap", "loss_aversion", "does_not_exist"])
    assert "호기심 갭" in text
    assert "손실 회피" in text
    assert "does_not_exist" not in text


def test_render_levers_empty_falls_back():
    assert "구체성" in psychology.render_levers([])


def test_cta_strategy_maps_each_metric():
    assert "저장" in psychology.cta_strategy("saves")
    assert "댓글" in psychology.cta_strategy("comments")
    assert "공유" in psychology.cta_strategy("shares")
    assert "팔로우" in psychology.cta_strategy("follows")
    # 알 수 없는 지표는 saves로 폴백
    assert psychology.cta_strategy("unknown") == psychology.cta_strategy("saves")


def test_intensity_guide_defaults_to_assertive():
    assert "사실" in psychology.intensity_guide("assertive_factual")
    assert psychology.intensity_guide("garbage") == psychology.intensity_guide("assertive_factual")


def test_render_hook_types_lists_entries():
    text = psychology.render_hook_types(["number_hook", "contrarian_hook"])
    assert "숫자 훅" in text
    assert "역발상 훅" in text
