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


class TestPssFileResolution:
    def test_configured_pss_path_is_preferred(self, monkeypatch, tmp_path):
        filename = "custom_pss.txt"
        configured_file = tmp_path / filename
        configured_file.write_text("test")

        monkeypatch.setenv("PSS_DATA_PATH", str(tmp_path))

        resolved = calibration_logic._resolve_pss_file(filename)

        assert resolved == configured_file

    def test_missing_configured_file_falls_back_to_bundled_clc(
        self,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setenv("PSS_DATA_PATH", str(tmp_path))

        resolved = calibration_logic._resolve_pss_file(
            "PSS_6668_Hydra_LCP.txt"
        )

        assert resolved.is_file()
        assert resolved.name == "PSS_6668_Hydra_LCP.txt"
        assert resolved.parent.name == "clc"


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


class TestPssTrailingStatistics:
    def test_uses_only_previous_thirty_days(self):
        history = {
            "lcp": {
                "mjd": [69.0, 70.0, 80.0, 90.0, 100.0, 101.0],
                "pss": [99.0, 10.0, 20.0, 30.0, 40.0, 99.0],
            },
            "rcp": {
                "mjd": [69.0, 70.0, 80.0, 90.0, 100.0, 101.0],
                "pss": [99.0, 8.0, 16.0, 24.0, 32.0, 99.0],
            },
        }

        result = calibration_logic.get_pss_trailing_statistics(
            history,
            observation_mjd=100.0,
            days=30,
        )

        assert result["start_mjd"] == pytest.approx(70.0)
        assert result["end_mjd"] == pytest.approx(100.0)
        assert result["lcp"]["count"] == 4
        assert result["lcp"]["mean"] == pytest.approx(25.0)
        assert result["lcp"]["std"] == pytest.approx(12.9099444874)
        assert result["rcp"]["count"] == 4
        assert result["rcp"]["mean"] == pytest.approx(20.0)
        assert result["rcp"]["std"] == pytest.approx(10.3279555899)

    def test_single_measurement_has_no_standard_deviation(self):
        history = {
            "lcp": {
                "mjd": [95.0],
                "pss": [10.0],
            },
            "rcp": {
                "mjd": [95.0],
                "pss": [8.0],
            },
        }

        result = calibration_logic.get_pss_trailing_statistics(
            history,
            observation_mjd=100.0,
            days=30,
        )

        assert result["lcp"]["mean"] == pytest.approx(10.0)
        assert result["lcp"]["std"] is None
        assert result["rcp"]["mean"] == pytest.approx(8.0)
        assert result["rcp"]["std"] is None


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


class TestPage05PolarizationExport:
    def test_exports_exact_lcp_and_rcp_samples_in_plot_order(self):
        import csv
        from io import StringIO

        spectrum = {
            "Vlsr": [-1.5, 0.0, 1.5],
            "LCP": [2.0, 4.5, 6.0],
            "RCP": [7.0, 8.5, 9.0],
        }
        original = {key: list(value) for key, value in spectrum.items()}

        for polarization, expected in (
            ("LCP", [2.0, 4.5, 6.0]),
            ("RCP", [7.0, 8.5, 9.0]),
        ):
            csv_bytes = calibration_logic.polarization_trace_csv(
                spectrum, polarization, "Jy"
            )
            rows = list(csv.reader(StringIO(csv_bytes.decode("utf-8"))))
            assert rows[0] == ["Vlsr_km_s", f"{polarization}_Jy"]
            assert [float(row[0]) for row in rows[1:]] == spectrum["Vlsr"]
            assert [float(row[1]) for row in rows[1:]] == expected
            assert len(rows) == len(spectrum["Vlsr"]) + 1

        assert spectrum == original

    def test_export_preserves_baseline_units(self):
        spectrum = {"Vlsr": [0.0], "LCP": [1.25], "RCP": [2.25]}
        result = calibration_logic.polarization_trace_csv(
            spectrum, "LCP", "K"
        )
        assert result.decode("utf-8") == "Vlsr_km_s,LCP_K\n0,1.25\n"

    def test_export_rejects_invalid_polarization_or_units(self):
        spectrum = {"Vlsr": [0.0], "LCP": [1.0], "RCP": [2.0]}
        with pytest.raises(ValueError, match="LCP or RCP"):
            calibration_logic.polarization_trace_csv(
                spectrum, "Mean", "Jy"
            )
        with pytest.raises(ValueError, match="K or Jy"):
            calibration_logic.polarization_trace_csv(
                spectrum, "LCP", "unknown"
            )

    def test_export_rejects_unaligned_arrays(self):
        spectrum = {
            "Vlsr": [0.0, 1.0],
            "LCP": [1.0],
            "RCP": [2.0, 3.0],
        }
        with pytest.raises(ValueError, match="same channel count"):
            calibration_logic.polarization_trace_csv(
                spectrum, "LCP", "Jy"
            )


class TestSelectedPairCalibrationMetadata:
    @staticmethod
    def _spectrum(date, frequency=6668518000.0):
        return {
            "date": date,
            "longitude": 27.0,
            "latitude": -25.0,
            "Tamb": 20.0,
            "Humid": 40.0,
            "restfreq": frequency,
        }

    def test_uses_selected_pair_instead_of_first_loaded_file(self):
        first = self._spectrum("2011-01-01T00:00:00")
        selected = self._spectrum("2012-05-05T03:00:00")
        partner = self._spectrum("2012-05-05T03:02:00")

        state = {
            "loaded_spectrum": first,
            "loaded_spectra": [first, selected, partner],
            "pipeline_data": {
                "file_loader": {
                    "eligible_files": ["first.fits", "selected.fits", "partner.fits"],
                },
                "03_bandpass_correction": {
                    "filename1": "selected.fits",
                    "filename2": "partner.fits",
                },
            },
        }

        assert calibration_logic.metadata_for_selected_pair(state) is selected
        assert state["loaded_spectrum"] is first

    def test_rejects_missing_selected_file(self):
        first = self._spectrum("2011-01-01T00:00:00")
        second = self._spectrum("2011-01-01T00:02:00")
        state = {
            "loaded_spectrum": first,
            "loaded_spectra": [first, second],
            "pipeline_data": {
                "file_loader": {"eligible_files": ["a.fits", "b.fits"]},
                "03_bandpass_correction": {
                    "filename1": "missing.fits",
                    "filename2": "b.fits",
                },
            },
        }

        with pytest.raises(ValueError, match="missing from Page 02"):
            calibration_logic.metadata_for_selected_pair(state)

    def test_rejects_mismatched_pair_frequency(self):
        first = self._spectrum("2011-01-01T00:00:00")
        second = self._spectrum(
            "2011-01-01T00:02:00", frequency=22235000000.0
        )
        state = {
            "loaded_spectrum": first,
            "loaded_spectra": [first, second],
            "pipeline_data": {
                "file_loader": {"eligible_files": ["a.fits", "b.fits"]},
                "03_bandpass_correction": {
                    "filename1": "a.fits",
                    "filename2": "b.fits",
                },
            },
        }

        with pytest.raises(ValueError, match="mismatched rest frequencies"):
            calibration_logic.metadata_for_selected_pair(state)

    def test_legacy_single_spectrum_remains_compatible(self):
        spectrum = self._spectrum("2011-01-01T00:00:00")
        state = {
            "loaded_spectrum": spectrum,
            "loaded_spectra": [spectrum],
            "pipeline_data": {},
        }
        assert calibration_logic.metadata_for_selected_pair(state) is spectrum


class TestPssCalendarMonthAverages:
    def test_uses_calendar_month_not_adjacent_dates(self):
        start = calibration_logic.get_observation_mjd(
            "2024-02-01T00:00:00"
        )
        end = calibration_logic.get_observation_mjd(
            "2024-03-01T00:00:00"
        )
        history = {
            "lcp": {
                "mjd": [start - 1, start, start + 10, end - 0.5, end],
                "pss": [99, 2, 4, 6, 100],
            },
            "rcp": {
                "mjd": [start, start + 10, end],
                "pss": [3, 7, 77],
            },
        }
        result = calibration_logic.get_pss_calendar_month_averages(
            history, "2024-02-12T10:00:00"
        )
        assert result["month_label"] == "February 2024"
        assert result["start_mjd"] == pytest.approx(start)
        assert result["end_mjd_exclusive"] == pytest.approx(end)
        assert result["lcp"] == pytest.approx(4.0)
        assert result["rcp"] == pytest.approx(5.0)

    def test_december_rolls_over_into_next_year(self):
        start = calibration_logic.get_observation_mjd(
            "2025-12-01T00:00:00"
        )
        end = calibration_logic.get_observation_mjd(
            "2026-01-01T00:00:00"
        )
        history = {
            "lcp": {"mjd": [start, end], "pss": [5, 70]},
            "rcp": {"mjd": [start, end], "pss": [4, 90]},
        }
        result = calibration_logic.get_pss_calendar_month_averages(
            history, "2025-12-31T23:59:00"
        )
        assert result["end_mjd_exclusive"] == pytest.approx(end)
        assert result["lcp"] == pytest.approx(5.0)
        assert result["rcp"] == pytest.approx(4.0)

    def test_missing_monthly_samples_gives_none(self):
        history = {
            "lcp": {"mjd": [100.0], "pss": [1]},
            "rcp": {"mjd": [100.0], "pss": [2]},
        }
        result = calibration_logic.get_pss_calendar_month_averages(
            history, "2024-06-15T00:00:00"
        )
        assert result["lcp"] is None
        assert result["rcp"] is None
