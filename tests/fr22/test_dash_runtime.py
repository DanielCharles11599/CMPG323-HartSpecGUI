# test_dash_runtime.py — FR-22 actual Dash layout/callback registration when dependencies exist.
import pytest

pytest.importorskip("streamlit", reason="Dash bridge imports the app session store")
pytest.importorskip("dash", reason="Requires installed Dash 2.16.0")
from dash_apps.baseline_editor import create_app, _root_style  # noqa: E402


def test_real_dash_layout_serves_with_supported_component_properties():
    app = create_app()
    response = app.server.test_client().get("/_dash-layout")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert '"region-choice"' in text and '"sample-number"' in text
    assert '"htmlFor":"region-start"' in text
    assert _root_style("dark", 200)["--hs-root-size"] == "32px"
    assert len(app.callback_map) >= 10
