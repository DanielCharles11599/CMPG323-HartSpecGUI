# test_dash_visual_merge.py — FR-22: restored editor controls coexist with startup readiness.
"""Exercise extracted real functions; native Dash wiring is tested in test_dash_runtime.

Extraction avoids replacing sys.modules['streamlit'] or leaking a mock Dash app
into other suites. These tests do not claim to be native browser acceptance.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils.accessibility import (
    accessible_theme, normalize_font_scale, region_options, selected_region_index, validate_view_range,
)

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
EDITOR = APP / "dash_apps/baseline_editor.py"


def extracted(*names, **environment):
    """Compile named functions from the real source without launching a Dash app."""
    source = ast.parse(EDITOR.read_text(encoding="utf-8-sig"))
    nodes = []
    for name in names:
        node = next(node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name == name)
        node.decorator_list = []
        nodes.append(node)
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = dict(environment)
    exec(compile(module, str(EDITOR), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 125, 150, 175, 200])
def test_editor_root_carries_theme_scale_and_single_ring(theme, scale):
    """Use the actual theme constants and actual root-style function."""
    tree = ast.parse((APP / "utils/styles.py").read_text(encoding="utf-8-sig"))
    constants = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            if getattr(target, "id", "") in ("ACCENT", "THEMES", "STATUS_BADGES"):
                constants.append(ast.Assign(targets=[target], value=node.value))
    module = ast.fix_missing_locations(ast.Module(body=constants, type_ignores=[]))
    values = {}
    exec(compile(module, "styles_constants", "exec"), values)
    values = {key: values[key] for key in ("THEMES", "STATUS_BADGES")}
    functions = extracted(
        "_theme_tokens", "_root_style", styles=SimpleNamespace(**values),
        accessible_theme=accessible_theme, normalize_font_scale=normalize_font_scale,
    )
    root = functions["_root_style"](theme, scale)
    assert root["--hs-root-size"] == f"{16 * scale / 100:g}px"
    assert root["--hs-font-scale"] == str(scale / 100)
    expected = accessible_theme(values["THEMES"][theme])
    for key in ("focus-ring", "control-border", "text-on-accent"):
        assert root[f"--hs-{key}"] == expected[key]


@pytest.mark.parametrize("trigger,expected", [("view-reset", None), ("view-apply", [-2.5, 3.2])])
def test_view_callback_changes_only_display_limits(trigger, expected):
    """A display-only view has no bridge/store dependency."""
    noop = object()
    functions = extracted("change_view", ctx=SimpleNamespace(triggered_id=trigger),
                          validate_view_range=validate_view_range, no_update=noop)
    assert functions["change_view"](1, 0, -2.5, 3.2) == (expected, "")


@pytest.mark.parametrize("limits", [(3, 3), (4, 2), (None, 3), (float("nan"), 3)])
def test_invalid_view_keeps_previous_limits(limits):
    noop = object()
    functions = extracted("change_view", ctx=SimpleNamespace(triggered_id="view-apply"),
                          validate_view_range=validate_view_range, no_update=noop)
    result, error = functions["change_view"](1, 0, *limits)
    assert result is noop
    assert error


@pytest.mark.parametrize(
    "event,selected_rows,choice,expected",
    [
        ("block-table.data", [], None, None),
        ("block-table.selected_rows", [1], None, 1),
        ("region-choice.value", [], 1, 1),
    ],
)
def test_region_selection_syncs_table_and_keyboard_choice(event, selected_rows, choice, expected):
    rows = [{"block": 1, "start": -4.3, "end": -2.7}, {"block": 2, "start": 1.2, "end": 2.9}]
    functions = extracted(
        "_region_index", "_region_selection",
        region_options=region_options,
        selected_region_index=selected_region_index, Any=object,
    )
    options, value, checked = functions["_region_selection"](
        rows, choice, selected_rows, None, {event}
    )
    assert [item["value"] for item in options] == [0, 1]
    assert value == expected
    assert checked == ([expected] if expected is not None else [])


@pytest.mark.parametrize("selection", [None, -1, 2])
def test_invalid_region_choice_does_not_populate_another_row(selection):
    noop = object()
    functions = extracted("_region_index", "populate_region_inputs",
                          selected_region_index=selected_region_index, no_update=noop, Any=object)
    values = functions["populate_region_inputs"](selection, [{"block": 1, "start": -1.2, "end": 2.3}])
    assert values == (noop, noop)


def test_region_choice_preserves_exact_boundaries():
    functions = extracted("_region_index", "populate_region_inputs",
                          selected_region_index=selected_region_index, no_update=object(), Any=object)
    rows = [{"block": 1, "start": -1.2, "end": 2.3}]
    assert functions["populate_region_inputs"](0, rows) == (-1.2, 2.3)


def test_restored_controls_preserve_readiness_retry():
    probes = []
    responses = iter([False, False, True])
    clock = SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda seconds: None)
    functions = extracted("_wait_for_server", time=clock, threading=SimpleNamespace(Thread=object),
                          _dash_responding=lambda port: probes.append(port) or next(responses))
    functions["_wait_for_server"](8050, SimpleNamespace(is_alive=lambda: True))
    assert probes == [8050, 8050, 8050]


def test_readiness_still_reports_a_stopped_server():
    functions = extracted("_wait_for_server", time=SimpleNamespace(monotonic=lambda: 0.0),
                          threading=SimpleNamespace(Thread=object), _dash_responding=lambda port: False)
    with pytest.raises(RuntimeError, match="stopped while starting"):
        functions["_wait_for_server"](8050, SimpleNamespace(is_alive=lambda: False))


def test_page_retains_ipv4_and_startup_error_feedback():
    page = (APP / "pages/04_Baseline_Editor.py").read_text(encoding="utf-8-sig")
    assert 'f"http://127.0.0.1:{port}"' in page
    assert 'except (OSError, RuntimeError) as exc:' in page
    assert 'The embedded Baseline Editor could not start:' in page
    assert 'font_scale=styles.get_font_scale()' in page
    assert 'scrolling=True' in page
