"""Calibration helpers for the Page 05 dashboard."""

from clc.Calibrate_PSS_PWR import PWR


REQUIRED_METADATA = (
    "date",
    "longitude",
    "latitude",
    "Tamb",
    "Humid",
    "restfreq",
)


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

    nd_lcp, nd_rcp, atcor, elevation, azimuth, pwv = PWR(
        spectrum["date"],
        spectrum["longitude"],
        spectrum["latitude"],
        spectrum["Tamb"],
        spectrum["Humid"],
        frequency,
    )

    return {
        "frequency": frequency,
        "pwv": pwv,
        "elevation": elevation,
        "azimuth": azimuth,
        "atcor": atcor,
        "nd_lcp": nd_lcp,
        "nd_rcp": nd_rcp,
        "optical_depth": None,
    }
