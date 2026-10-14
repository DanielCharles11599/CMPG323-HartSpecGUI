"""Calibration helpers for the Page 05 dashboard."""

import csv
from io import StringIO
import os
from pathlib import Path

import numpy as np
from astropy.time import Time

from clc.Calibrate_PSS_PWR import PWR


REQUIRED_METADATA = (
    "date",
    "longitude",
    "latitude",
    "Tamb",
    "Humid",
    "restfreq",
)


PSS_HISTORY_FILES = {
    "22235": ("PSS_22235_Jupiter_LCP.txt", "PSS_22235_Jupiter_RCP.txt"),
    "20970": ("PSS_22235_Jupiter_LCP.txt", "PSS_22235_Jupiter_RCP.txt"),
    "20346": ("PSS_22235_Jupiter_LCP.txt", "PSS_22235_Jupiter_RCP.txt"),
    "23121": ("PSS_22235_Jupiter_LCP.txt", "PSS_22235_Jupiter_RCP.txt"),
    "23694": ("PSS_22235_Jupiter_LCP.txt", "PSS_22235_Jupiter_RCP.txt"),
    "23722": ("PSS_22235_Jupiter_LCP.txt", "PSS_22235_Jupiter_RCP.txt"),
    "12178": ("PSS_12178_3C123_LCP.txt", "PSS_12178_3C123_RCP.txt"),
    "12229": ("PSS_12178_3C123_LCP.txt", "PSS_12178_3C123_RCP.txt"),
    "66685": ("PSS_6668_Hydra_LCP.txt", "PSS_6668_Hydra_RCP.txt"),
    "61811": ("PSS_6668_Hydra_LCP.txt", "PSS_6668_Hydra_RCP.txt"),
    "61810": ("PSS_6668_Hydra_LCP.txt", "PSS_6668_Hydra_RCP.txt"),
    "6708.": ("PSS_6668_Hydra_LCP.txt", "PSS_6668_Hydra_RCP.txt"),
}


def _resolve_pss_file(filename):
    """Locate one PSS file using configured, local, then bundled data paths."""
    configured_path = os.environ.get("PSS_DATA_PATH")

    if configured_path:
        candidate = Path(configured_path).expanduser() / filename
        if candidate.is_file():
            return candidate

    default_candidate = Path("./data/pss") / filename
    if default_candidate.is_file():
        return default_candidate

    bundled_candidate = Path(__file__).resolve().parents[2] / "clc" / filename
    if bundled_candidate.is_file():
        return bundled_candidate

    searched_locations = []
    if configured_path:
        searched_locations.append(str(Path(configured_path).expanduser()))
    searched_locations.extend(
        [
            "./data/pss",
            str(Path(__file__).resolve().parents[2] / "clc"),
        ]
    )

    raise FileNotFoundError(
        f"PSS file {filename} was not found in any available PSS data location: "
        + ", ".join(searched_locations)
    )


def _load_pss_series(path):
    """Read the historical MJD, PSS and uncertainty columns from one PSS file."""
    data = np.loadtxt(path, dtype="str")

    if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 4:
        raise ValueError(f"PSS file {path.name} does not have the expected four-column format.")

    return {
        "mjd": data[1:, 0].astype(float).tolist(),
        "pss": data[1:, 2].astype(float).tolist(),
        "error": data[1:, 3].astype(float).tolist(),
    }


def get_observation_mjd(observation_date):
    """Convert a loaded FITS observation date to Modified Julian Date."""
    if observation_date is None:
        raise ValueError("No observation date is available for PSS calibration.")

    try:
        return float(Time(observation_date, format="isot").mjd)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Observation date {observation_date!r} could not be converted to MJD."
        ) from exc


def get_pss_window(observation_date, days=15):
    """Return the observation MJD and the requested PSS time window."""
    observation_mjd = get_observation_mjd(observation_date)

    return {
        "observation_mjd": observation_mjd,
        "start_mjd": observation_mjd - days,
        "end_mjd": observation_mjd + days,
        "days": days,
    }


def get_pss_history(frequency):
    """Load the historical LCP and RCP PSS series for a supported frequency."""
    frequency = str(frequency)[:5]
    filenames = PSS_HISTORY_FILES.get(frequency)

    if filenames is None:
        raise ValueError(
            f"No historical PSS dataset is configured for frequency {frequency}."
        )

    lcp_path = _resolve_pss_file(filenames[0])
    rcp_path = _resolve_pss_file(filenames[1])

    return {
        "frequency": frequency,
        "lcp": _load_pss_series(lcp_path),
        "rcp": _load_pss_series(rcp_path),
        "source_files": {
            "lcp": lcp_path.name,
            "rcp": rcp_path.name,
        },
    }


def get_pss_window_averages(pss_history, pss_window):
    """Return mean LCP and RCP PSS values inside the inclusive PSS window."""
    if pss_history is None or pss_window is None:
        raise ValueError("PSS history and window are required.")

    start_mjd = float(pss_window["start_mjd"])
    end_mjd = float(pss_window["end_mjd"])

    def mean_for(series):
        values = [
            float(pss)
            for mjd, pss in zip(series["mjd"], series["pss"])
            if start_mjd <= float(mjd) <= end_mjd
        ]
        return float(np.mean(values)) if values else None

    return {
        "lcp": mean_for(pss_history["lcp"]),
        "rcp": mean_for(pss_history["rcp"]),
    }


def get_pss_calendar_month_averages(pss_history, observation_date):
    """Calculate calendar-month LCP/RCP means without changing calibration."""
    if pss_history is None:
        raise ValueError("PSS history is required.")

    mjd = get_observation_mjd(observation_date)
    observed = Time(mjd, format="mjd").datetime
    year, month = observed.year, observed.month

    next_year, next_month = (
        (year + 1, 1) if month == 12 else (year, month + 1)
    )

    start = float(
        Time(f"{year:04d}-{month:02d}-01T00:00:00", format="isot").mjd
    )
    end = float(
        Time(
            f"{next_year:04d}-{next_month:02d}-01T00:00:00",
            format="isot",
        ).mjd
    )

    def calculate(series):
        values = [
            float(pss)
            for date, pss in zip(series["mjd"], series["pss"])
            if start <= float(date) < end
        ]
        return float(np.mean(values)) if values else None

    return {
        "month_label": observed.strftime("%B %Y"),
        "start_mjd": start,
        "end_mjd_exclusive": end,
        "lcp": calculate(pss_history["lcp"]),
        "rcp": calculate(pss_history["rcp"]),
    }


def get_pss_trailing_statistics(pss_history, observation_mjd, days=30):
    """Return trailing-window PSS mean, sample standard deviation and count."""
    if pss_history is None:
        raise ValueError("PSS history is required.")

    end_mjd = float(observation_mjd)
    start_mjd = end_mjd - float(days)

    def statistics_for(series):
        values = [
            float(pss)
            for mjd, pss in zip(series["mjd"], series["pss"])
            if start_mjd <= float(mjd) <= end_mjd
        ]

        if not values:
            return {
                "mean": None,
                "std": None,
                "count": 0,
            }

        return {
            "mean": float(np.mean(values)),
            "std": (
                float(np.std(values, ddof=1))
                if len(values) >= 2
                else None
            ),
            "count": len(values),
        }

    return {
        "start_mjd": start_mjd,
        "end_mjd": end_mjd,
        "days": int(days),
        "lcp": statistics_for(pss_history["lcp"]),
        "rcp": statistics_for(pss_history["rcp"]),
    }



def metadata_for_selected_pair(state):
    """Use the applied Page 03 pair, not the first loaded FITS file."""
    from collections.abc import Mapping

    pipeline = state.get("pipeline_data", {})
    stage3 = (
        pipeline.get("03_bandpass_correction")
        if isinstance(pipeline, Mapping) else None
    )
    spectra = state.get("loaded_spectra")

    if not isinstance(stage3, Mapping):
        if isinstance(spectra, (list, tuple)) and len(spectra) > 1:
            raise ValueError(
                "Select and apply a Page 03 pair before Page 05 calibration."
            )
        return state.get("loaded_spectrum")

    first_name = stage3.get("filename1")
    second_name = stage3.get("filename2")

    if not all(
        isinstance(name, str) and bool(name)
        for name in (first_name, second_name)
    ):
        if isinstance(spectra, (list, tuple)) and len(spectra) > 1:
            raise ValueError("Page 03 did not record the selected pair.")
        return state.get("loaded_spectrum")

    if first_name == second_name:
        raise ValueError("The selected pair contains the same file twice.")

    loader = pipeline.get("file_loader", {})
    filenames = (
        loader.get("eligible_files")
        if isinstance(loader, Mapping) else None
    )

    if (
        not isinstance(filenames, (list, tuple))
        or not isinstance(spectra, (list, tuple))
        or len(filenames) != len(spectra)
        or not all(isinstance(name, str) for name in filenames)
        or len(set(filenames)) != len(filenames)
    ):
        raise ValueError(
            "Page 02 files cannot be matched safely to the Page 03 pair."
        )

    try:
        first = spectra[filenames.index(first_name)]
        second = spectra[filenames.index(second_name)]
    except ValueError as exc:
        raise ValueError(
            "The selected Page 03 pair is missing from Page 02 loaded files."
        ) from exc

    if not isinstance(first, Mapping) or not isinstance(second, Mapping):
        raise ValueError("Selected pair spectra have invalid metadata.")

    if any(first.get(key) is None for key in REQUIRED_METADATA):
        raise ValueError(
            "The selected pair lacks required atmospheric/PSS metadata."
        )

    if str(first["restfreq"])[:5] != str(second.get("restfreq"))[:5]:
        raise ValueError(
            "The selected pair has mismatched rest frequencies."
        )

    return first


def get_atmospheric_calibration(spectrum):
    """Run the existing HartSpec atmospheric calibration for one spectrum."""
    if not spectrum:
        raise ValueError("No loaded spectrum is available for calibration.")

    missing = [key for key in REQUIRED_METADATA if spectrum.get(key) is None]
    if missing:
        raise ValueError(
            "The loaded spectrum is missing calibration metadata: "
            + ", ".join(missing)
        )

    frequency = str(spectrum["restfreq"])[:5]

    nd_lcp, nd_rcp, atcor, elevation, azimuth, pwv, optical_depth = PWR(
        spectrum["date"],
        spectrum["longitude"],
        spectrum["latitude"],
        spectrum["Tamb"],
        spectrum["Humid"],
        frequency,
        return_optical_depth=True,
    )

    return {
        "frequency": frequency,
        "pwv": pwv,
        "elevation": elevation,
        "azimuth": azimuth,
        "atcor": atcor,
        "nd_lcp": nd_lcp,
        "nd_rcp": nd_rcp,
        "optical_depth": optical_depth,
    }


def apply_calibration_to_spectrum(
    spectrum, atcor, lcp_pss_jy_per_k, rcp_pss_jy_per_k, nd_lcp, nd_rcp
):
    """Convert K spectra to Jy using separate polarization calibration factors.

    The original CLC applies noise-diode and atmospheric factors before the
    respective LCP/RCP PSS factors. Pointing belongs to the next stage.
    Input arrays are not mutated. The PSS values are the specified +/-15-day
    means, not the legacy Best_PSS implementation's differing window result.
    """
    try:
        atcor, lcp_pss, rcp_pss, nd_lcp, nd_rcp = (
            float(value) for value in (
                atcor, lcp_pss_jy_per_k, rcp_pss_jy_per_k, nd_lcp, nd_rcp
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Calibration factors must be numeric.") from exc
    if any(not np.isfinite(value) or value <= 0 for value in (
        atcor, lcp_pss, rcp_pss, nd_lcp, nd_rcp
    )):
        raise ValueError("All calibration factors must be positive and finite.")
    lcp_scale = nd_lcp * atcor * lcp_pss
    rcp_scale = nd_rcp * atcor * rcp_pss

    arrays = {}
    for key in ("Vlsr", "LCP", "RCP"):
        try:
            value = np.asarray(spectrum[key], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid baseline spectrum field: {key}") from exc

        if value.ndim != 1 or value.size == 0:
            raise ValueError(f"{key} must be a nonempty 1-D array.")
        if not np.isfinite(value).all():
            raise ValueError(f"{key} contains non-finite values.")
        arrays[key] = value

    if len({value.size for value in arrays.values()}) != 1:
        raise ValueError("Baseline spectrum arrays have different lengths.")

    return {
        "Vlsr": arrays["Vlsr"].copy(),
        "LCP": arrays["LCP"] * lcp_scale,
        "RCP": arrays["RCP"] * rcp_scale,
    }


def polarization_trace_csv(spectrum, polarization, intensity_unit):
    """Export the actual unsmoothed LCP/RCP samples displayed on Page 05."""
    if polarization not in ("LCP", "RCP"):
        raise ValueError("Polarization must be LCP or RCP.")
    if intensity_unit not in ("K", "Jy"):
        raise ValueError("Intensity unit must be K or Jy.")

    from utils.polarization_logic import validated_spectrum

    arrays = validated_spectrum(spectrum)
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("Vlsr_km_s", f"{polarization}_{intensity_unit}"))
    writer.writerows(
        (format(float(velocity), ".17g"), format(float(intensity), ".17g"))
        for velocity, intensity in zip(arrays["Vlsr"], arrays[polarization])
    )
    return output.getvalue().encode("utf-8")
