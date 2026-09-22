"""Tests for the Page 05 calibration helpers."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

import hartspec_gui.utils.calibration_logic as calibration_logic  # noqa: E402


class TestObservationMjd:
    def test_converts_fits_observation_date_to_mjd(self):
        result = calibration_logic.get_observation_mjd("2013-04-25T00:27:32")

        assert result == pytest.approx(56407.01912037037)

    def test_rejects_missing_observation_date(self):
        with pytest.raises(ValueError, match="No observation date"):
            calibration_logic.get_observation_mjd(None)


class TestPssWindow:
    def test_returns_fifteen_day_window_around_observation(self):
        result = calibration_logic.get_pss_window(
            "2013-04-25T00:27:32",
            days=15,
        )

        assert result["observation_mjd"] == pytest.approx(56407.01912037037)
        assert result["start_mjd"] == pytest.approx(56392.01912037037)
        assert result["end_mjd"] == pytest.approx(56422.01912037037)
        assert result["days"] == 15


class TestPssHistory:
    def test_loads_lcp_and_rcp_series_for_supported_frequency(
        self,
        monkeypatch,
        tmp_path,
    ):
        lcp_path = tmp_path / "lcp.txt"
        rcp_path = tmp_path / "rcp.txt"

        lcp_path.write_text(
            "MJD FREQ PSS ERROR\n"
            "56400.0 6668.5 10.5 0.2\n"
            "56401.0 6668.5 11.5 0.3\n"
        )
        rcp_path.write_text(
            "MJD FREQ PSS ERROR\n"
            "56400.0 6668.5 9.5 0.4\n"
            "56401.0 6668.5 10.0 0.5\n"
        )

        monkeypatch.setitem(
            calibration_logic.PSS_HISTORY_FILES,
            "66685",
            ("lcp.txt", "rcp.txt"),
        )

        def resolve_pss_file(filename):
            return tmp_path / filename

        monkeypatch.setattr(
            calibration_logic,
            "_resolve_pss_file",
            resolve_pss_file,
        )

        result = calibration_logic.get_pss_history(6668518000.0)

        assert result["frequency"] == "66685"
        assert result["lcp"]["mjd"] == [56400.0, 56401.0]
        assert result["lcp"]["pss"] == [10.5, 11.5]
        assert result["lcp"]["error"] == [0.2, 0.3]
        assert result["rcp"]["mjd"] == [56400.0, 56401.0]
        assert result["rcp"]["pss"] == [9.5, 10.0]
        assert result["rcp"]["error"] == [0.4, 0.5]
        assert result["source_files"] == {
            "lcp": "lcp.txt",
            "rcp": "rcp.txt",
        }

    def test_rejects_unsupported_frequency(self):
        with pytest.raises(ValueError, match="No historical PSS dataset"):
            calibration_logic.get_pss_history(9999999999.0)


class TestPssWindowAverages:
    def test_averages_only_values_inside_pss_window(self):
        history = {
            "lcp": {
                "mjd": [99.0, 100.0, 110.0, 120.0, 121.0],
                "pss": [1.0, 10.0, 20.0, 30.0, 40.0],
            },
            "rcp": {
                "mjd": [99.0, 100.0, 110.0, 120.0, 121.0],
                "pss": [2.0, 8.0, 16.0, 24.0, 32.0],
            },
        }
        window = {
            "start_mjd": 100.0,
            "end_mjd": 120.0,
        }

        result = calibration_logic.get_pss_window_averages(history, window)

        assert result["lcp"] == pytest.approx(20.0)
        assert result["rcp"] == pytest.approx(16.0)

    def test_returns_none_when_window_contains_no_values(self):
        history = {
            "lcp": {
                "mjd": [1.0, 2.0],
                "pss": [10.0, 20.0],
            },
            "rcp": {
                "mjd": [1.0, 2.0],
                "pss": [8.0, 12.0],
            },
        }
        window = {
            "start_mjd": 10.0,
            "end_mjd": 20.0,
        }

        result = calibration_logic.get_pss_window_averages(history, window)

        assert result["lcp"] is None
        assert result["rcp"] is None


class TestAtmosphericCalibration:
    def test_requires_calibration_metadata(self):
        spectrum = {
            "date": "2013-04-25T00:27:32",
            "longitude": 27.6854,
        }

        with pytest.raises(ValueError, match="missing calibration metadata"):
            calibration_logic.get_atmospheric_calibration(spectrum)

    def test_returns_existing_pwr_outputs_without_changing_science(
        self,
        monkeypatch,
    ):
        spectrum = {
            "date": "2013-04-25T00:27:32",
            "longitude": 27.6854,
            "latitude": -25.8897,
            "Tamb": 20.0,
            "Humid": 40.0,
            "restfreq": 6668518000.0,
        }

        captured = {}

        def fake_pwr(
            date,
            longitude,
            latitude,
            tamb,
            humid,
            frequency,
            return_optical_depth=False,
        ):
            captured["args"] = (
                date,
                longitude,
                latitude,
                tamb,
                humid,
                frequency,
            )
            captured["return_optical_depth"] = return_optical_depth
            return 1.1, 2.2, 1.03, 61.2, 180.0, 13.9, 0.027

        monkeypatch.setattr(calibration_logic, "PWR", fake_pwr)

        result = calibration_logic.get_atmospheric_calibration(spectrum)

        assert captured["return_optical_depth"] is True
        assert captured["args"] == (
            "2013-04-25T00:27:32",
            27.6854,
            -25.8897,
            20.0,
            40.0,
            "66685",
        )

        assert result["frequency"] == "66685"
        assert result["nd_lcp"] == pytest.approx(1.1)
        assert result["nd_rcp"] == pytest.approx(2.2)
        assert result["atcor"] == pytest.approx(1.03)
        assert result["elevation"] == pytest.approx(61.2)
        assert result["azimuth"] == pytest.approx(180.0)
        assert result["pwv"] == pytest.approx(13.9)
        assert result["optical_depth"] == pytest.approx(0.027)


REFERENCE_CALIBRATION_FITS = [
    Path("tests/data/calibration/2006d182_16h05m42s_Spec_sharmila_G328.24-0.55.fits"),
    Path("tests/data/calibration/2007d007_04h32m42s_Spec_sharmila_G328.24-0.55.fits"),
    Path("tests/data/calibration/2007d353_07h43m52s_Spec_sharmila_G328.24-0.55.fits"),
]


@pytest.mark.parametrize("fits_path", REFERENCE_CALIBRATION_FITS)
def test_reference_fits_matches_direct_clc_calibration(fits_path):
    """Regression check: Page 05 calibration must match direct CLC output."""
    from astropy.io import fits

    def header_value(hdul, key):
        for hdu in hdul:
            if key in hdu.header:
                return hdu.header[key]
        raise KeyError(f"{key} not found in {fits_path}")

    with fits.open(fits_path, memmap=True) as hdul:
        spectrum = {
            "date": header_value(hdul, "DATE"),
            "longitude": float(header_value(hdul, "LONGITUD")),
            "latitude": float(header_value(hdul, "LATITUDE")),
            "Tamb": float(header_value(hdul, "TAMBIENT")),
            "Humid": float(header_value(hdul, "HUMIDITY")),
            "restfreq": float(header_value(hdul, "RESTFREQ")),
        }

    gui_result = calibration_logic.get_atmospheric_calibration(spectrum)

    direct_result = calibration_logic.PWR(
        spectrum["date"],
        spectrum["longitude"],
        spectrum["latitude"],
        spectrum["Tamb"],
        spectrum["Humid"],
        gui_result["frequency"],
        return_optical_depth=True,
    )

    expected = {
        "nd_lcp": direct_result[0],
        "nd_rcp": direct_result[1],
        "atcor": direct_result[2],
        "elevation": direct_result[3],
        "azimuth": direct_result[4],
        "pwv": direct_result[5],
        "optical_depth": direct_result[6],
    }

    for key, expected_value in expected.items():
        assert gui_result[key] == pytest.approx(
            expected_value,
            rel=1e-10,
            abs=1e-10,
        )
