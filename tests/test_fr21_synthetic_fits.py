# test_fr21_synthetic_fits.py — FR-21: real FITS I/O and campaign splitting using generated fixtures.
"""Requires the pinned Astropy/Streamlit stack, skipped when unavailable.

This tests FITS file format, ingestion, pair/scan recognition and CLC-derived
baseline math on synthetic arrays, *not* the astronomical correctness of a
complete observation or CLI parity on real data.
"""

from __future__ import annotations

import pytest

pytest.importorskip("astropy.io.fits")
pytest.importorskip("streamlit")

# These imports must follow importorskip so missing scientific packages skip the module.
from fr21_synthetic_fits import write_synthetic_hartspec_fits  # noqa: E402
from utils import batch_observations, batch_queue, baseline_polynomial_adapter, fits_ingest  # noqa: E402


@pytest.fixture
def campaign(tmp_path):
    archive = tmp_path / "fits"
    archive.mkdir()
    names = []
    for pair in (1, 2):
        for role, position in (("on", "ON"), ("off", "OFF")):
            name = f"pair{pair}_{role}.fits"
            write_synthetic_hartspec_fits(archive / name, pointing=0, position=position,
                                          seed=pair, baseline_offset=1.2 if role == "on" else 0,
                                          line_scale=1.0 if role == "on" else 0.2)
            names.append(name)
    for scan in (1, 2):
        for role, position in (("n", "HPN"), ("s", "HPS"), ("e", "HPE"), ("w", "HPW"),
                               ("c", "ON"), ("ref", "OFF")):
            name = f"scan{scan}_{role}.fits"
            write_synthetic_hartspec_fits(archive / name, pointing=1, position=position, seed=scan)
            names.append(name)
    selection = {"source_name": "W3(OH)", "frequency_mhz": 6668.5, "archive_root": str(archive),
                 "selected_files": names, "fits_file_paths": [str(archive / name) for name in names],
                 "observation_blocks": {"20260812_0.txt": names}}
    return archive, selection


def test_real_four_hdu_synthetic_fits_loads_and_preflights(campaign):
    archive, selection = campaign
    for name in selection["selected_files"]:
        assert fits_ingest.verify_fits_file(archive / name).ok, name
        ingested = fits_ingest.ingest_fits_file(archive / name)
        assert ingested.ok, (name, ingested.load_errors)
        assert ingested.convention == "date"
        assert len(ingested.spectrum["Vlsr"]) == 1024
    manifest = batch_queue.prepare_batch(selection, source_session_id="synthetic",
                                         verifier=fits_ingest.verify_fits_file)
    assert manifest["jobs"][0]["status"] == "pending"
    inspected = batch_observations.inspect_observation_job(manifest["jobs"][0])
    assert len(inspected["pairs"]) == 2
    assert len(inspected["scans"]) == 2
    assert inspected["pairs"][0]["files"] == ["pair1_on.fits", "pair1_off.fits"]
    assert all(pair["mode"] == "Position Switch" for pair in inspected["pairs"])


def test_synthetic_fits_run_actual_bandpass_and_clc_baseline_adapter(campaign):
    archive, selection = campaign
    from utils import bandpass_correction_logic as bp
    items = [fits_ingest.ingest_fits_file(archive / name) for name in selection["selected_files"][:2]]
    entries = [{"filename": item.filename, "spectrum": item.spectrum, "pointing": 0,
                "position": item.spectrum["position"], "observation_dir": "20260812_0.txt"}
               for item in items]
    pair = bp.get_full_integration_pairs(entries)[0]
    result = bp.build_bandpass_result("Position Switch", pair)
    spec = result["corrected"]
    assert len(spec["Vlsr"]) == 1024
    comparison = baseline_polynomial_adapter.fit_polynomial_comparison(
        spec, [{"start": -15.0, "end": -5.0}, {"start": 5.0, "end": 15.0}])
    assert len(comparison["panels"]) == 6
    assert all(panel["chi_squared"] == panel["chi_squared"] for panel in comparison["panels"])


def test_corrupt_synthetic_fits_is_invalidated_without_touching_other_jobs(campaign, tmp_path):
    archive, selection = campaign
    names = selection["selected_files"]
    selection["observation_blocks"] = {"20260812_0.txt": names[:8],
                                       "20260812_1.txt": names[8:]}
    manifest = batch_queue.prepare_batch(selection, source_session_id="synthetic",
                                         verifier=fits_ingest.verify_fits_file)
    batch_queue.create_batch(tmp_path / "sessions", manifest)
    damaged = archive / names[0]
    damaged.write_bytes(damaged.read_bytes()[:100])
    bad = batch_queue.revalidate_job_inputs(manifest["jobs"][0])
    assert bad
    current = batch_queue.invalidate_changed_job(tmp_path / "sessions", manifest["batch_id"],
                                                 manifest["jobs"][0]["job_id"], expected_revision=1)
    assert current["jobs"][0]["status"] == "invalid"
    assert current["jobs"][1]["status"] == "pending"
