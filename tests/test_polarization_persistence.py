# test_polarization_persistence.py — FR-09: real session/checkpoint/bridge disk integration.
"""Real project persistence and sidebar code; Streamlit is a test-only API double.

These tests write/read immutable JSON and baseline sidecars in tmp_path. They do
not mock the session/checkpoint/bridge methods. The polarization CLC reference
and Streamlit facade are supplied by the existing panel test fixture.
"""
from __future__ import annotations

import copy
import sys

import numpy as np
import pytest

from test_polarization_panel import (  # noqa: F401 -- pytest registers imported fixtures
    PREFIX, ROOT, STAGE, load_module, panel_context, saved,
)
from utils import checkpoint_store
from utils.polarization_logic import SETTINGS_KEY


class Navigation(BaseException):
    """Interrupt a test script at the same point as Streamlit's page navigation."""


def _navigate(path):
    """Stop before the old page can recreate runtime state after Load/Reset."""
    raise Navigation(path)


@pytest.fixture
def persistence_context(panel_context, monkeypatch, tmp_path):  # noqa: F811 — imported pytest fixture
    """Attach real disk-backed services to the panel's isolated UI facade."""
    c = panel_context
    st = c.st
    st.query_params = {}
    st.switch_page = _navigate
    st.rerun = lambda: None
    st.sidebar = st
    st.expander = lambda *args, **kwargs: st
    st.empty = lambda: st
    st.success = lambda text: st.messages['success'].append(text)
    st.selectbox = lambda label, options, **kwargs: st.session_state.setdefault(kwargs['key'], options[0])
    session = load_module('_fr09_real_session', ROOT / 'hartspec_gui/utils/session_store.py')
    monkeypatch.setattr(c.package, 'session_store', session, raising=False)
    monkeypatch.setitem(sys.modules, 'utils.session_store', session)
    monkeypatch.setattr(session, 'SESSIONS_DIR', tmp_path / 'sessions')
    bridge = load_module('_fr09_real_bridge', ROOT / 'hartspec_gui/utils/baseline_editor_bridge.py')
    monkeypatch.setattr(c.package, 'baseline_editor_bridge', bridge, raising=False)
    monkeypatch.setitem(sys.modules, 'utils.baseline_editor_bridge', bridge)
    sidebar = load_module('_fr09_real_sidebar', ROOT / 'hartspec_gui/utils/sidebar.py')
    monkeypatch.setattr(c.package, 'sidebar', sidebar, raising=False)
    monkeypatch.setitem(sys.modules, 'utils.sidebar', sidebar)
    session.init_session_state()
    state = st.session_state
    state['pipeline_data'] = {
        '01_source_browser': {'source_name': 'test-only', 'selected_files': ['test-only.fits']},
        'file_loader': {'complete': True},
        '03_bandpass_correction': {
            'mode': 'Position Switch', 'corrected_fingerprint': bridge.spectrum_fingerprint(c.spectrum),
        },
    }
    state['completed_stages'] = set(state['pipeline_data'])
    state['bandpass_corrected_spectrum'] = copy.deepcopy(c.spectrum)
    state['loaded_spectra'] = [copy.deepcopy(c.spectrum)]
    state['loaded_spectrum'] = {'date': '2007-01-01T00:00:00', 'restfreq': 6668518000.}
    rows = [{'block': 1, 'start': -9.0, 'end': -7.0}]
    bridge_data = bridge.initialize_bridge(
        state['session_id'], c.spectrum, 'light', 'Position Switch', state['checkpoint_token'],
    )
    bridge_data.update(
        blocks=rows, selected_orders={'LCP': 3, 'RCP': 3}, complete=True,
        fit_result={'provider': 'clc', 'blocks': rows, 'panels': []},
        flattened_spectrum={key: value.tolist() for key, value in c.spectrum.items()},
    )
    bridge.write_bridge(state['session_id'], bridge_data)
    session.sync_baseline_state()
    assert '04_baseline_editor' in state['completed_stages']
    state['pipeline_data'][STAGE] = {'complete': True, 'atmospheric': {'atcor': 1.1}, 'pss': {'frequency': '66685'}}
    state['pipeline_data']['07_spectral_fitting'] = {'fit_type': 'fixture-only', 'unchanged': True}
    state['pipeline_data']['08_export_and_session'] = {'complete': True}
    state['completed_stages'].update((STAGE, '07_spectral_fitting', '08_export_and_session'))
    state['calibrated_spectrum'] = copy.deepcopy(c.spectrum)
    state['latest_fit'] = {'unchanged': True}
    state['export_cache'] = b'unchanged export fixture'
    initial = session.checkpoint_session('FR-09 test fixture')
    assert initial and initial.is_file()

    def on_change(message):
        """Use the same public audit/checkpoint calls as the real Page 05 hook."""
        session.log_event(message)
        session.checkpoint_session('Polarization display settings recorded')

    def render():
        """Refresh the real baseline bridge and then display its current arrays."""
        session.begin_page(5)
        st.figures.clear()
        st.messages.clear()
        return c.panel.render_polarization_panel(
            state.get('baseline_corrected_spectrum'), source_key='baseline', source_label='Baseline test fixture',
            intensity_unit='K', on_change=on_change,
        )

    def latest():
        """Read the actual on-disk revision, including integrity verification."""
        return checkpoint_store.latest(session.SESSIONS_DIR, state['checkpoint_token'])

    c.session, c.bridge, c.sidebar = session, bridge, sidebar
    c.render_live, c.latest, c.tmp_path = render, latest, tmp_path
    return c


def _smooth(c, window=11):
    """Commit a toggle and a window through the real registered widget callbacks."""
    c.render_live()
    c.st.interact(f'{PREFIX}_smooth', True)
    c.render_live()
    c.st.interact(f'{PREFIX}_window', window)
    c.render_live()


def _rebuild_bandpass(c):
    """Simulate the handoff of an unchanged successful Page 03 replay, not a FITS load."""
    c.st.session_state['bandpass_corrected_spectrum'] = copy.deepcopy(c.spectrum)
    c.st.session_state['loaded_spectra'] = [copy.deepcopy(c.spectrum)]
    c.st.session_state['loaded_spectrum'] = {'date': '2007-01-01T00:00:00', 'restfreq': 6668518000.}
    c.session.sync_baseline_state()
    assert 'checkpoint_pending_bridge' not in c.st.session_state


def test_real_checkpoint_contains_controls_and_no_display_arrays(persistence_context):
    c = persistence_context
    _smooth(c)
    disk = c.latest()
    view = disk.payload['pipeline_data'][STAGE][SETTINGS_KEY]
    assert view == saved(c)
    assert view['smoothing_enabled'] and view['window_length'] == 11
    assert not set(('Vlsr', 'LCP', 'RCP', 'mean', 'I')).intersection(view)
    assert disk.bridge is not None
    assert disk.path.with_name(disk.path.stem + '.baseline_editor.json').is_file()
    assert len([e for e in disk.payload['audit_log'] if 'FR-09 view changed' in e['message']]) == 2


def test_actual_checkpoint_deduplication_on_identical_reruns(persistence_context):
    c = persistence_context
    _smooth(c)
    before = c.latest()
    file_bytes, mtime = before.path.read_bytes(), before.path.stat().st_mtime_ns
    audit = copy.deepcopy(c.st.session_state['audit_log'])
    for _ in range(5):
        c.render_live()
        c.session.checkpoint_session('Calibration parameters recorded')
    assert c.latest().path == before.path
    assert c.latest().path.read_bytes() == file_bytes
    assert c.latest().path.stat().st_mtime_ns == mtime
    assert c.st.session_state['audit_log'] == audit


def test_real_manual_save_load_restores_view_after_unchanged_replay(persistence_context):
    c = persistence_context
    _smooth(c, 13)
    original = copy.deepcopy(saved(c))
    path = c.session.save_session()
    before = path.read_bytes()
    c.st.interact(f'{PREFIX}_window', 9)
    c.session.load_session(path, navigate=False)
    assert saved(c) == original
    assert f'{PREFIX}_window' not in c.st.session_state
    assert 'calibrated_spectrum' not in c.st.session_state
    assert 'latest_fit' not in c.st.session_state
    assert 'baseline_corrected_spectrum' not in c.st.session_state
    assert 'checkpoint_pending_bridge' in c.st.session_state
    _rebuild_bandpass(c)
    c.render_live()
    assert saved(c) == original
    assert c.st.session_state[f'{PREFIX}_window'] == 13
    assert c.st.session_state[f'{PREFIX}_smooth'] is True
    assert path.read_bytes() == before


def test_real_recovery_uses_frozen_snapshot_and_isolates_old_dash(persistence_context):
    c = persistence_context
    _smooth(c, 9)
    previous = c.latest()
    state = c.st.session_state
    old_id, old_token = state['session_id'], state['checkpoint_token']
    saved_bridge = copy.deepcopy(previous.bridge)
    c.session.recover_checkpoint(previous.path, navigate=False)
    assert state['session_id'] != old_id and state['checkpoint_token'] != old_token
    assert saved(c)['window_length'] == 9
    old_bridge = c.bridge.read_bridge(old_id)
    old_bridge['flattened_spectrum']['LCP'][0] += 42
    c.bridge.write_bridge(old_id, old_bridge)
    _rebuild_bandpass(c)
    np.testing.assert_array_equal(
        state['baseline_corrected_spectrum']['LCP'], saved_bridge['flattened_spectrum']['LCP'],
    )
    c.render_live()
    assert saved(c)['smoothing_enabled'] is True
    assert saved(c)['window_length'] == 9


def test_real_reset_clears_fr09_controls_without_deleting_saves(persistence_context):
    c = persistence_context
    _smooth(c)
    path = c.session.save_session()
    files = {p: p.read_bytes() for p in c.session.SESSIONS_DIR.rglob('*.json')}
    state = c.st.session_state
    state.update(theme='dark', authentication_fixture='keep')
    old_id = state['session_id']
    c.session.reset_session(navigate=False)
    assert state['session_id'] != old_id
    assert not state['pipeline_data'] and not state['completed_stages']
    assert not any(key.startswith(PREFIX) for key in state)
    assert state['theme'] == 'dark' and state['authentication_fixture'] == 'keep'
    assert path.is_file()
    assert all(p.read_bytes() == data for p, data in files.items())


def test_real_disk_baseline_edit_invalidates_fr09_and_downstream(persistence_context):
    c = persistence_context
    _smooth(c)
    old_view = copy.deepcopy(saved(c))
    state = c.st.session_state

    def edit(bridge):
        bridge['flattened_spectrum']['LCP'][0] += 0.125
        c.bridge.append_event(bridge, 'Test-only baseline result changed')

    c.bridge.update_bridge(state['session_id'], edit)
    c.session.begin_page(5)
    assert STAGE not in state['pipeline_data']
    assert not set((STAGE, '07_spectral_fitting', '08_export_and_session')).intersection(state['completed_stages'])
    for key in ('calibrated_spectrum', 'latest_fit', 'export_cache'):
        assert key not in state
    c.render_live()
    assert not saved(c)['smoothing_enabled']
    assert saved(c)['source_fingerprint'] != old_view['source_fingerprint']
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY] == saved(c)


def test_real_incomplete_baseline_cannot_restore_an_old_overlay(persistence_context):
    c = persistence_context
    _smooth(c)

    def edit(bridge):
        bridge.update(blocks=[], fit_result=None, flattened_spectrum=None, complete=False)

    c.bridge.update_bridge(c.st.session_state['session_id'], edit)
    assert not c.render_live()
    assert '04_baseline_editor' not in c.st.session_state['completed_stages']
    assert STAGE not in c.st.session_state['pipeline_data']
    assert not c.st.figures


def test_real_view_edits_preserve_science_fit_and_export_bytes(persistence_context):
    c = persistence_context
    state = c.st.session_state
    before = copy.deepcopy(state)
    bridge_before = c.bridge.read_bridge(state['session_id'])
    _smooth(c)
    c.st.interact(f'{PREFIX}_smooth', False)
    c.render_live()
    for key in ('bandpass_corrected_spectrum', 'baseline_corrected_spectrum', 'calibrated_spectrum'):
        for array in ('Vlsr', 'LCP', 'RCP'):
            np.testing.assert_array_equal(state[key][array], before[key][array])
    for key in ('latest_fit', 'export_cache', 'completed_stages'):
        assert state[key] == before[key]
    for key in ('07_spectral_fitting', '08_export_and_session'):
        assert state['pipeline_data'][key] == before['pipeline_data'][key]
    assert c.bridge.read_bridge(state['session_id']) == bridge_before


def test_real_disk_write_failure_keeps_controls_and_exposes_warning(persistence_context, monkeypatch):
    c = persistence_context
    c.render_live()
    previous = c.latest()

    def denied(*args, **kwargs):
        raise PermissionError('test-only read-only filesystem')

    with monkeypatch.context() as denied_patch:
        denied_patch.setattr(checkpoint_store, '_atomic_create', denied)
        c.st.interact(f'{PREFIX}_smooth', True)
        assert saved(c)['smoothing_enabled']
        assert 'test-only read-only filesystem' in c.st.session_state['checkpoint_error']
        assert c.latest().revision == previous.revision
        assert not c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY]['smoothing_enabled']
    assert c.session.checkpoint_session('Checkpoint retry')
    assert 'checkpoint_error' not in c.st.session_state
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY]['smoothing_enabled']


def test_real_failed_load_preserves_current_fr09_state(persistence_context):
    c = persistence_context
    _smooth(c)
    invalid = c.tmp_path / 'invalid.json'
    invalid.write_text('{"not_a_session":true}')
    before = copy.deepcopy(c.st.session_state)
    with pytest.raises(ValueError):
        c.session.load_session(invalid, navigate=False)
    assert saved(c) == before['pipeline_data'][STAGE][SETTINGS_KEY]
    assert c.st.session_state['session_id'] == before['session_id']


def test_real_sidebar_save_button_serializes_the_current_view(persistence_context):
    c = persistence_context
    _smooth(c, 9)
    c.st.button = lambda *args, **kwargs: kwargs.get('key') == 'session_save'
    c.sidebar.render_sidebar(5)
    saves = c.session.list_sessions()
    assert len(saves) == 1
    view = checkpoint_store.read_record(saves[0]).payload['pipeline_data'][STAGE][SETTINGS_KEY]
    assert view == saved(c)


@pytest.mark.parametrize('action', ['load', 'recover', 'reset'])
def test_real_sidebar_restore_actions_interrupt_old_page(persistence_context, action):
    c = persistence_context
    _smooth(c, 9)
    path = c.session.save_session()
    button = {'load': 'session_load_confirm', 'recover': 'session_checkpoint_recover', 'reset': 'session_reset'}[action]
    c.st.session_state['session_load_choice'] = path
    c.st.button = lambda *args, **kwargs: kwargs.get('key') == button
    with pytest.raises(Navigation) as exc:
        c.sidebar.render_sidebar(5)
    assert str(exc.value) == ('pages/01_Source_Browser.py' if action == 'reset' else 'pages/02_File_Loader.py')
    if action == 'reset':
        assert STAGE not in c.st.session_state['pipeline_data']
    else:
        assert saved(c)['smoothing_enabled'] and saved(c)['window_length'] == 9
    assert 'calibrated_spectrum' not in c.st.session_state


def test_late_widget_callback_cannot_edit_a_loaded_session(persistence_context):
    c = persistence_context
    _smooth(c)
    widget = c.st.widgets[f'{PREFIX}_smooth']
    path = c.session.save_session()
    c.session.load_session(path, navigate=False)
    before = copy.deepcopy(saved(c))
    c.st.session_state[f'{PREFIX}_smooth'] = False
    widget['on_change'](*widget['args'])
    assert saved(c) == before


def test_real_rebuild_gate_preserves_fr09_until_inputs_are_revalidated(persistence_context):
    c = persistence_context
    _smooth(c, 13)
    c.session.load_session(c.session.save_session(), navigate=False)
    with pytest.raises(Navigation, match='02_File_Loader'):
        c.session.begin_page(5)
    assert saved(c)['window_length'] == 13
    c.st.session_state['loaded_spectra'] = [copy.deepcopy(c.spectrum)]
    with pytest.raises(Navigation, match='03_Bandpass_Correction'):
        c.session.begin_page(5)
    assert saved(c)['window_length'] == 13


@pytest.fixture
def integrated_page_context(persistence_context, monkeypatch):
    """Real Page 05 + all four supplied services, with external astronomy boundaries stubbed.

    Only Astropy Time and the unavailable Calibrate_PSS_PWR.PWR return fixtures.
    PSS text loading, averaging, calibration application, session synchronization,
    sidebar orchestration, and disk checkpoints execute the supplied source files.
    This is NOT a scientific regression of PWR or an Astropy date-conversion test.
    """
    import runpy
    from types import ModuleType, SimpleNamespace

    c = persistence_context
    time_module = ModuleType('astropy.time')
    time_module.Time = lambda value, format: SimpleNamespace(mjd=54000.0)
    monkeypatch.setitem(sys.modules, 'astropy.time', time_module)
    pwr_module = ModuleType('clc.Calibrate_PSS_PWR')
    calls = []

    def pwr(*args, **kwargs):
        calls.append((args, kwargs))
        return 1.0, 1.0, 1.1, 60.0, 180.0, 12.0, 0.03

    pwr_module.PWR = pwr
    monkeypatch.setitem(sys.modules, 'clc.Calibrate_PSS_PWR', pwr_module)
    calibration = load_module('_fr09_real_calibration', ROOT / 'hartspec_gui/utils/calibration_logic.py')
    for name, module in (('calibration_logic', calibration), ('polarization_panel', c.panel)):
        monkeypatch.setattr(c.package, name, module, raising=False)
        monkeypatch.setitem(sys.modules, f'utils.{name}', module)
    directory = c.tmp_path / 'pss-fixtures'
    directory.mkdir()
    filenames = calibration.PSS_HISTORY_FILES['66685']
    for name, values in zip(filenames, ([2., 3., 4.], [4., 6., 8.])):
        (directory / name).write_text(
            'MJD FREQ PSS ERROR\n'
            + ''.join(f'{mjd} 6668.5 {pss} 0.1\n' for mjd, pss in zip([53990., 54000., 54010.], values))
        )
    monkeypatch.setenv('PSS_DATA_PATH', str(directory))
    metadata = {
        'date': 'test-only-date-at-time-boundary', 'restfreq': 6668518000.,
        'longitude': 27., 'latitude': -25., 'Tamb': 20., 'Humid': 40.,
    }
    c.st.session_state['loaded_spectrum'] = copy.deepcopy(metadata)

    def run():
        c.st.figures.clear()
        c.st.messages.clear()
        return runpy.run_path(str(ROOT / 'hartspec_gui/pages/05_Calibration_Dashboard.py'))

    c.run_page, c.calibration, c.pwr_calls, c.metadata = run, calibration, calls, metadata
    return c


def test_page05_real_helpers_apply_calibration_before_display(integrated_page_context):
    c = integrated_page_context
    c.run_page()
    state = c.st.session_state
    for key, pss in (('LCP', 3.0), ('RCP', 6.0)):
        np.testing.assert_allclose(
            state['calibrated_spectrum'][key], c.spectrum[key] * (1.1 * pss),
            rtol=1e-13, atol=1e-13,
        )
    assert saved(c)['source_key'] == 'calibrated'
    assert saved(c)['intensity_unit'] == 'Jy'
    assert c.pwr_calls == [(
        ('test-only-date-at-time-boundary', 27., -25., 20., 40., '66685'), {'return_optical_depth': True},
    )]
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY] == saved(c)


def test_page05_real_helpers_never_calibrate_smoothed_display_values(integrated_page_context):
    c = integrated_page_context
    c.run_page()
    before = copy.deepcopy(c.st.session_state['calibrated_spectrum'])
    c.st.interact(f'{PREFIX}_smooth', True)
    c.run_page()
    c.st.interact(f'{PREFIX}_window', 11)
    c.run_page()
    c.st.interact(f'{PREFIX}_smooth', False)
    c.run_page()
    for key in ('Vlsr', 'LCP', 'RCP'):
        np.testing.assert_array_equal(c.st.session_state['calibrated_spectrum'][key], before[key])
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY]['window_length'] == 11
    assert not saved(c)['smoothing_enabled']
    assert c.st.session_state['latest_fit'] == {'unchanged': True}
    # Existing Page 05 still calls PWR on reruns. This test does not claim a
    # full-page latency guarantee or hide that external dependency behind caching.
    assert len(c.pwr_calls) == 4


def test_page05_real_helpers_fall_back_when_atmosphere_fails(integrated_page_context, monkeypatch):
    c = integrated_page_context

    def unavailable(*args, **kwargs):
        raise RuntimeError('test-only unavailable atmospheric input')

    monkeypatch.setattr(c.calibration, 'PWR', unavailable)
    c.run_page()
    assert saved(c)['source_key'] == 'baseline'
    assert saved(c)['intensity_unit'] == 'K'
    assert STAGE not in c.st.session_state['completed_stages']
    assert 'calibrated_spectrum' not in c.st.session_state
    assert any('test-only unavailable' in text for text in c.st.messages['error'])
    c.st.interact(f'{PREFIX}_smooth', True)
    c.run_page()
    assert saved(c)['smoothing_enabled']


def test_page05_real_save_load_rebuild_preserves_smoothing(integrated_page_context):
    c = integrated_page_context
    c.run_page()
    c.st.interact(f'{PREFIX}_smooth', True)
    c.run_page()
    c.st.interact(f'{PREFIX}_window', 13)
    c.run_page()
    wanted = copy.deepcopy(saved(c))
    path = c.session.save_session()
    c.session.load_session(path, navigate=False)
    _rebuild_bandpass(c)
    c.st.session_state['loaded_spectrum'] = c.metadata
    c.run_page()
    assert saved(c) == wanted
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY] == wanted


def test_page05_real_baseline_update_rebuilds_display_and_clears_fit(integrated_page_context):
    c = integrated_page_context
    c.run_page()
    c.st.interact(f'{PREFIX}_smooth', True)
    c.run_page()
    old_fingerprint = saved(c)['source_fingerprint']

    def edit(bridge):
        bridge['flattened_spectrum']['RCP'][10] += 0.2

    c.bridge.update_bridge(c.st.session_state['session_id'], edit)
    c.run_page()
    assert not saved(c)['smoothing_enabled']
    assert saved(c)['source_fingerprint'] != old_fingerprint
    assert 'latest_fit' not in c.st.session_state
    assert '07_spectral_fitting' not in c.st.session_state['completed_stages']
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY] == saved(c)


def test_page05_real_missing_metadata_keeps_valid_baseline_view(integrated_page_context):
    c = integrated_page_context
    c.st.session_state.pop('loaded_spectrum')
    c.run_page()
    c.st.interact(f'{PREFIX}_smooth', True)
    c.run_page()
    c.st.interact(f'{PREFIX}_window', 11)
    c.run_page()
    assert saved(c)['source_key'] == 'baseline'
    assert saved(c)['smoothing_enabled'] and saved(c)['window_length'] == 11
    assert STAGE not in c.st.session_state['completed_stages']
    assert c.latest().payload['pipeline_data'][STAGE][SETTINGS_KEY] == saved(c)
