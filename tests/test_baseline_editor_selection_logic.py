# test_baseline_editor_selection_logic.py — regression tests for Page 4 region semantics.

import numpy as np
import pytest

from hartspec_gui.utils.baseline_editor_selection_logic import (
    RegionValidationError,
    VelocityRegion,
    add_region,
    build_flat_fit_mask,
    build_unselected_feature_mask,
    delete_region,
    quantize_velocity,
    region_from_plotly_selection,
    subtract_baseline_preserving_all_channels,
    update_region,
    validate_region,
)


def test_velocity_values_are_quantized_to_point_one_kms():
    assert quantize_velocity(4.149) == 4.1
    assert quantize_velocity(4.151) == 4.2


def test_invalid_edit_does_not_replace_existing_rows():
    existing = [{"block": 1, "start": -12.4, "end": -9.8}]
    with pytest.raises(RegionValidationError, match="smaller than"):
        update_region(existing, 0, 2.0, 2.0, -20.0, 20.0)
    assert existing == [{"block": 1, "start": -12.4, "end": -9.8}]


def test_numeric_add_update_and_delete_are_supported():
    rows = add_region([], -12.43, -9.76, -20.0, 20.0)
    assert rows == [{"block": 1, "start": -12.4, "end": -9.8}]

    rows = update_region(rows, 0, -12.0, -9.5, -20.0, 20.0)
    assert rows == [{"block": 1, "start": -12.0, "end": -9.5}]

    rows = delete_region(rows, 0, -20.0, 20.0)
    assert rows == []


def test_selected_flat_regions_are_included_in_fit_mask_not_excluded():
    vlsr = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    regions = [VelocityRegion(-1.0, 1.0)]

    fit_mask = build_flat_fit_mask(vlsr, regions)
    feature_mask = build_unselected_feature_mask(vlsr, regions)

    assert fit_mask.tolist() == [False, True, True, True, False]
    assert feature_mask.tolist() == [True, False, False, False, True]


def test_plotly_drag_is_optional_and_uses_same_validation():
    selected = {"range": {"x": [7.64, 4.06]}}
    region = region_from_plotly_selection(selected, -20.0, 20.0)
    assert region == VelocityRegion(4.1, 7.6)
    assert region_from_plotly_selection(None, -20.0, 20.0) is None


def test_full_velocity_axis_is_preserved_after_subtraction():
    spectrum = np.array([10.0, 50.0, 11.0])  # centre channel represents a spike
    baseline = np.array([10.0, 10.0, 10.0])
    flattened = subtract_baseline_preserving_all_channels(spectrum, baseline)

    assert flattened.shape == spectrum.shape
    assert flattened.tolist() == [0.0, 40.0, 1.0]


def test_region_outside_current_velocity_range_is_rejected():
    with pytest.raises(RegionValidationError, match="displayed velocity range"):
        validate_region(-21.0, -19.0, -20.0, 20.0)
