# fr21_synthetic_fits.py — FR-21: deterministic synthetic four-HDU HartSpec FITS fixture.
"""Testing only: construct real FITS files compatible with the original CLC DATE loader.

Requires Astropy on the target Python 3.11 environment. No fake FITS bytes are
used in the tests that import this fixture; generated files are still not real
observatory/reference spectra and cannot prove six-significant-figure CLI parity.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits


def write_synthetic_hartspec_fits(
    path: Path, *, pointing: int, position: str, seed: int = 0,
    baseline_offset: float = 0.0, line_scale: float = 1.0,
) -> None:
    """Write a valid, small (1024-channel) primary+3-extension FITS observation."""
    velocity = np.linspace(-20.0, 20.0, 1024)
    noise = np.random.default_rng(seed).normal(scale=0.005, size=velocity.size)
    line = np.exp(-0.5 * (velocity / 1.8) ** 2)
    lcp = 3.0 + baseline_offset + 0.04 * velocity + 0.001 * velocity**2 + line_scale * line + noise
    rcp = 3.1 + baseline_offset + 0.02 * velocity + 0.001 * velocity**2 + 0.9 * line_scale * line + noise

    header = fits.Header()
    header["RESTFREQ"] = 6668500000.0
    header["SPPOINT"] = pointing
    header["DATE"] = "2026-08-12T12:00:00"
    header["OBJECT"] = "W3(OH)"
    header["LONGITUD"] = 27.68
    header["LATITUDE"] = -25.89
    header["TAMBIENT"] = 20.0
    header["HUMIDITY"] = 50.0
    header["FOCUS"] = 0.0
    header["EQUINOX"] = 2000.0
    header["SPBW"] = 1.0
    header["SPCHAN"] = velocity.size
    header["SPTIME"] = 60.0
    header["SPFS"] = 0.0
    header["SPVLSR"] = 0.0
    primary = fits.PrimaryHDU(header=header)

    beam = fits.ImageHDU(data=np.array([0.0]))
    beam.header["HPBW"] = 0.23
    spectrum = fits.BinTableHDU.from_columns([
        fits.Column(name="Vlsr", array=velocity, format="D", unit="km/s"),
        fits.Column(name="Polstate1", array=lcp, format="D", unit="K"),
        fits.Column(name="Polstate4", array=rcp, format="D", unit="K"),
    ])
    spectrum.header["POSITION"] = position
    spectrum.header["CENTFREQ"] = 6668500000.0

    diode = fits.BinTableHDU.from_columns([
        fits.Column(name="Count1", array=np.array([10.0]), format="D"),
        fits.Column(name="Count2", array=np.array([11.0]), format="D"),
        fits.Column(name="MJD", array=np.array([60534.0]), format="D"),
    ])
    for key, value in {"TCAL1": 0.0, "TSYS1": 48.0, "TSYSERR1": 0.1,
                       "TSYS2": 47.0, "TSYSERR2": 0.1, "HZPERK1": 1.0,
                       "HZKERR1": 0.1, "HZPERK2": 1.0, "HZKERR2": 0.1}.items():
        diode.header[key] = value
    fits.HDUList([primary, beam, spectrum, diode]).writeto(path, overwrite=False)
