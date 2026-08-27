# test_baseline_editor_logic.py — regression tests for FR-05/06/07 page-state logic.

from utils.baseline_editor_logic import (
    auto_select_orders,
    comparison_panels,
    normalize_blocks,
    selected_data_to_block,
    stage_payload,
)


def test_selected_data_rounds_drag_range_to_point_one_kms() -> None:
    selected = {"range": {"x": [-12.36, -9.76]}}
    block = selected_data_to_block(selected, block_number=1)
    assert block is not None
    assert block.start == -12.4
    assert block.end == -9.8


def test_invalid_start_end_is_flagged() -> None:
    normalized, errors = normalize_blocks([{"block": 1, "start": 4.1, "end": 4.1, "delete": "×"}])
    assert normalized == []
    assert errors == ["Block 1: start must be less than end."]


def test_comparison_grid_is_orders_three_to_five_for_both_polarizations() -> None:
    identities = [(panel.order, panel.polarization) for panel in comparison_panels()]
    assert identities == [
        (3, "LCP"),
        (4, "LCP"),
        (5, "LCP"),
        (3, "RCP"),
        (4, "RCP"),
        (5, "RCP"),
    ]


def test_auto_selection_minimizes_chi_squared_per_polarization() -> None:
    fit_result = {
        "provider": "clc",
        "panels": [
            {"order": 3, "polarization": "LCP", "chi_squared": 2.0},
            {"order": 4, "polarization": "LCP", "chi_squared": 1.1},
            {"order": 5, "polarization": "LCP", "chi_squared": 1.5},
            {"order": 3, "polarization": "RCP", "chi_squared": 0.8},
            {"order": 4, "polarization": "RCP", "chi_squared": 1.3},
            {"order": 5, "polarization": "RCP", "chi_squared": 1.6},
        ],
    }
    assert auto_select_orders(fit_result) == {"LCP": 4, "RCP": 3}


def test_stage_only_completes_with_both_selected_orders_and_clc_fit() -> None:
    fit_result = {
        "provider": "clc",
        "panels": [
            {"order": 3, "polarization": "LCP", "chi_squared": 1.0},
            {"order": 3, "polarization": "RCP", "chi_squared": 1.0},
        ],
    }
    payload = stage_payload(
        [{"block": 1, "start": -12.4, "end": -9.8}],
        "Manual",
        {"LCP": 3, "RCP": 3},
        fit_result,
    )
    assert payload["complete"] is True


def test_auto_selection_fallback_uses_absolute_score_like_stats_manager_chi_s() -> None:
    fit_result = {
        "provider": "clc",
        "panels": [
            {"order": 3, "polarization": "LCP", "chi_squared": -0.10},
            {"order": 4, "polarization": "LCP", "chi_squared": 0.03},
            {"order": 5, "polarization": "LCP", "chi_squared": -0.05},
            {"order": 3, "polarization": "RCP", "chi_squared": -0.02},
            {"order": 4, "polarization": "RCP", "chi_squared": 0.07},
            {"order": 5, "polarization": "RCP", "chi_squared": -0.04},
        ],
    }
    assert auto_select_orders(fit_result) == {"LCP": 4, "RCP": 3}
