# test_region_editor_navigation.py — FR-05/FR-22: keyboard and selection regression tests.
"""Exercise callbacks plus Dash-version-safe keyboard wiring."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from utils.accessibility import region_options, selected_region_index
from utils.baseline_editor_selection_logic import (
    RegionValidationError, add_region, delete_region, region_from_plotly_selection,
    spectrum_velocity_bounds, update_region,
)

ROOT = Path(__file__).resolve().parents[2] / "hartspec_gui"
EDITOR = ROOT / "dash_apps/baseline_editor.py"


def _functions(*names: str, **globals_: Any) -> dict[str, Any]:
    """Compile unchanged source functions, stripping only their Dash decorators."""
    source = ast.parse(EDITOR.read_text(encoding="utf-8"))
    nodes = []
    for name in names:
        node = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == name)
        node.decorator_list = []
        nodes.append(node)
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    namespace: dict[str, Any] = {"Any": Any, **globals_}
    exec(compile(module, str(EDITOR), "exec"), namespace)
    return namespace


def _environment(triggered: set[str] | None = None, **extra: Any) -> dict[str, Any]:
    """Supply the same strict selection helpers used by Page 04."""
    return {
        "region_options": region_options,
        "selected_region_index": selected_region_index,
        "ctx": SimpleNamespace(triggered_id=next(iter(triggered or []), None),
                               triggered_prop_ids={name: name for name in triggered or []}),
        "RegionValidationError": RegionValidationError,
        "add_region": add_region,
        "delete_region": delete_region,
        "update_region": update_region,
        "region_from_plotly_selection": region_from_plotly_selection,
        "spectrum_velocity_bounds": spectrum_velocity_bounds,
        **extra,
    }


def test_native_dropdown_is_used_for_browser_managed_tab_navigation():
    """The React-Select combobox could consume Tab for choosing highlighted options."""
    source = EDITOR.read_text(encoding="utf-8")
    assert 'html.Select(' not in source
    assert 'dcc.Dropdown(' in source
    assert 'id="region-choice", options=[], value=None' in source
    assert 'Output("region-choice", "options")' in source
    assert 'Input("region-choice", "value")' in source
    # A deleted row can be replaced at the same index: refresh numeric fields
    # on data changes too, even when the selector value remains "0".
    assert 'Input("region-choice", "value"), Input("block-table", "data")' in source
    assert 'Output("block-table", "selected_rows")' in source
    script = (ROOT / "dash_apps/assets/accessibility.js").read_text(encoding="utf-8")
    assert '"region-choice": "Region to edit"' in script
    assert 'event.key !== "Tab"' in script
    assert 'event.shiftKey' in script
    assert 'event.stopImmediatePropagation()' in script
    css = (ROOT / "dash_apps/assets/baseline_editor.css").read_text(encoding="utf-8")
    assert ".hs-region-controls #region-choice .Select-control" in css


@pytest.mark.parametrize(
    "deleted,expected_index,expected_bounds",
    [
        (0, 0, (-41.9, -36.8)),   # delete first, select following region
        (1, 1, (-40.9, -39.1)),   # delete middle, select shifted following region
        (2, 1, (-41.9, -36.8)),   # delete last, select preceding region
    ],
)
def test_delete_auto_selects_actual_surviving_region(deleted, expected_index, expected_bounds):
    """A highlighted radio must match the dropdown and populated start/end fields."""
    rows = [
        {"block": 1, "start": -48.2, "end": -45.7},
        {"block": 2, "start": -41.9, "end": -36.8},
        {"block": 3, "start": -40.9, "end": -39.1},
    ]
    updated = delete_region(rows, deleted, -55, -30)
    next_row = min(deleted, len(updated) - 1)
    helpers = _functions("_region_index", "_region_selection", "populate_region_inputs",
                         **_environment())
    options, choice, selected_rows = helpers["_region_selection"](
        updated, deleted, [deleted], {"action": "delete-region", "selected_index": next_row},
        {"block-table.data", "region-edit-version.data"},
    )
    assert choice == expected_index
    assert selected_rows == [expected_index]
    assert [opt["value"] for opt in options] == [0, 1]
    assert helpers["populate_region_inputs"](choice, updated) == expected_bounds


def test_delete_only_region_clears_both_selections_and_numeric_fields():
    rows = delete_region([{"block": 1, "start": -48.2, "end": -45.7}], 0, -55, -30)
    functions = _functions("_region_index", "_region_selection", "populate_region_inputs",
                           **_environment(no_update=object()))
    options, choice, selected = functions["_region_selection"](
        rows, 0, [0], {"action": "delete-region", "selected_index": None},
        {"region-edit-version.data", "block-table.data"},
    )
    assert options == []
    assert choice is None and selected == []
    assert functions["populate_region_inputs"](choice, rows) == (None, None)


def test_native_select_click_and_keyboard_choice_synced_to_table_radio():
    rows = [{"start": -10.1, "end": -9.1}, {"start": -5.1, "end": -4.1}]
    functions = _functions("_region_index", "_region_selection", **_environment())
    _, value, radio = functions["_region_selection"](rows, 1, [0], None, {"region-choice.value"})
    assert (value, radio) == (1, [1])
    _, value, radio = functions["_region_selection"](rows, 0, [1], None, {"block-table.selected_rows"})
    assert (value, radio) == (1, [1])
    _, value, radio = functions["_region_selection"](rows, 1, [1], None, {"block-table.data"})
    assert (value, radio) == (1, [1])


@pytest.mark.parametrize("invalid", [None, "", "abc", "-1", "1.0", True, "99"])
def test_stale_or_missing_selection_can_never_delete_a_different_row(invalid):
    rows = [{"start": -10.1, "end": -9.1}, {"start": -5.1, "end": -4.1}]
    index = _functions("_region_index", **_environment())["_region_index"]
    with pytest.raises(ValueError):
        index(invalid, rows)
    assert index("1", rows) == 1


def test_invalid_region_edit_does_not_reset_active_selection():
    rows = [{"block": 1, "start": -10.0, "end": -9.0}]
    token = object()
    helpers = _functions("_region_index", "edit_flat_regions",
                         **_environment(triggered={"update-region"}, no_update=token))
    state = {"spectrum": {"Vlsr": [-20.0, 0.0, 20.0]}}
    data, error, metadata = helpers["edit_flat_regions"](
        None, 0, 1, 0, rows, 0, -8.0, -10.0, state,
    )
    assert data is token and metadata is token
    assert "smaller" in error


def test_editor_delete_callback_carries_next_selected_index():
    """Covers the real editing callback, not just pure row-renumbering helpers."""
    rows = [{"start": -10.0, "end": -9.0}, {"start": -5.0, "end": -4.0}]
    helpers = _functions("_region_index", "edit_flat_regions",
                         **_environment(triggered={"delete-region"}, no_update=object()))
    state = {"spectrum": {"Vlsr": [-20.0, 0.0, 20.0]}}
    data, error, metadata = helpers["edit_flat_regions"](None, 0, 0, 1, rows, 0, -10.0, -9.0, state)
    assert data == [{"block": 1, "start": -5.0, "end": -4.0, "delete": ""}]
    assert error == ""
    assert metadata == {"action": "delete-region", "selected_index": 0}
