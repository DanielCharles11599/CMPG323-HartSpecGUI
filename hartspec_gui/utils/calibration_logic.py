"""Calibration helpers for the Page 05 dashboard."""

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
    """Locate one PSS file using the project's configured data path."""
    configured_path = os.environ.get("PSS_DATA_PATH")

    if configured_path:
        candidate = Path(configured_path).expanduser() / filename
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(
            f"PSS file {filename} was not found in configured PSS_DATA_PATH "
            f"({configured_path})."
        )

    default_candidate = Path("./data/pss") / filename
    if default_candidate.is_file():
        return default_candidate

    bundled_candidate = Path(__file__).resolve().parents[2] / "clc" / filename
    if bundled_candidate.is_file():
        return bundled_candidate

    raise FileNotFoundError(
        f"PSS file {filename} was not found in data/pss or the bundled CLC data."
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


def apply_calibration_to_spectrum(baseline_spectrum, atmospheric_result, pss_lcp_mean, pss_rcp_mean):
    """Apply atmospheric (ATcor) and PSS flux calibration to a baseline-
    flattened spectrum, producing the Vlsr/LCP/RCP arrays that
    07_Spectral_Fitting.py and 08_Export_and_Session.py already look for
    under st.session_state["calibrated_spectrum"] as their *first* choice
    of spectrum to fit/export.

    Before this function existed, nothing in the pipeline ever wrote that
    key: 05_Calibration_Dashboard.py computed PWV/ATcor/PSS as display
    metrics only and never applied them to any spectrum array. Spectral
    fitting was silently running on the baseline-flattened (Page 4), not
    calibrated, spectrum -- a real scientific gap, not just a plumbing one.

    TODO: confirm against design. clc/Calibrate_PSS_PWR.py's own internal
    application of atcor/PSS to a full spectrum (as opposed to the scalar
    summary values PWR() returns) was not available to confirm against, so
    this uses the two standard radio-astronomy conventions rather than
    inventing a new one:
      - ATcor as a straight multiplicative atmospheric-attenuation
        correction: T_true = T_observed * atcor.
      - PSS converting antenna temperature to flux density by
        multiplication, per this project's own Technical Specifications
        glossary ("PSS: Point Source Sensitivity ... flux density
        calibration factor (Jy/K)"): Flux[Jy] = T_ant[K] * PSS[Jy/K].
    If either convention is wrong for this instrument (e.g. division
    instead of multiplication, or a different order of operations), this
    is the one function to correct -- nothing else in the pipeline needs
    to change, since Page 05 only ever calls this function, never
    reimplements the arithmetic itself.

    Raises:
        ValueError: if the baseline spectrum is missing required arrays, or
            atcor/PSS values needed to calibrate it are unavailable.
    """
    missing = [key for key in ("Vlsr", "LCP", "RCP") if key not in (baseline_spectrum or {})]
    if missing:
        raise ValueError(f"Baseline spectrum is missing required field(s): {', '.join(missing)}.")

    atcor = (atmospheric_result or {}).get("atcor")
    if atcor is None:
        raise ValueError("Atmospheric calibration result has no ATcor value to apply.")
    if pss_lcp_mean is None or pss_rcp_mean is None:
        raise ValueError("PSS window means for both LCP and RCP are required to calibrate a spectrum.")

    vlsr = np.asarray(baseline_spectrum["Vlsr"], dtype=float)
    lcp = np.asarray(baseline_spectrum["LCP"], dtype=float)
    rcp = np.asarray(baseline_spectrum["RCP"], dtype=float)

    return {
        "Vlsr": vlsr.tolist(),
        "LCP": (lcp * float(atcor) * float(pss_lcp_mean)).tolist(),
        "RCP": (rcp * float(atcor) * float(pss_rcp_mean)).tolist(),
    }
