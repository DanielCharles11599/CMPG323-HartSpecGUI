"""Build small synthetic FITS files matching the HDU layout both CLC loaders
(clc/load_file.py, clc/load_file2.py) expect: primary HDU0 + three extension
HDUs. Used by tests so we don't depend on real HartRAO data being present.

Kept separate from conftest.py so it can also be run standalone to inspect
what a fixture looks like:  python tests/fixtures/make_fixtures.py /tmp/out
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits

N = 16  # channels -- small on purpose, this is a structural fixture, not real data


def _hdu2_hdu3():
    hdu2 = fits.BinTableHDU.from_columns([
        fits.Column(name="Vlsr", format="E", array=np.linspace(-20, 20, N)),
        fits.Column(name="Polstate1", format="E", array=np.random.normal(5, 1, N)),
        fits.Column(name="Polstate4", format="E", array=np.random.normal(5, 1, N)),
    ])
    hdu2.header["TUNIT2"] = "K"
    hdu2.header["POSITION"] = "ON"
    hdu2.header["CENTFREQ"] = 1420.405

    hdu3 = fits.BinTableHDU.from_columns([
        fits.Column(name="Count1", format="E", array=np.random.normal(100, 5, N)),
        fits.Column(name="Count2", format="E", array=np.random.normal(100, 5, N)),
        fits.Column(name="MJD", format="D", array=np.linspace(60000, 60000.01, N)),
    ])
    hdu3.header["TCAL1"] = 1.23
    hdu3.header["TCALSIG1"] = 0.01
    hdu3.header["TCAL2"] = 1.19
    hdu3.header["TCALSIG2"] = 0.01
    hdu3.header["HZPERK1"] = 12.5
    hdu3.header["HZKERR1"] = 0.1
    hdu3.header["HZPERK2"] = 12.4
    hdu3.header["HZKERR2"] = 0.1
    return hdu2, hdu3


def _hdu1():
    hdu1 = fits.ImageHDU(data=np.zeros((1, 1)))
    hdu1.header["HPBW"] = 0.23
    return hdu1


def _primary(date_key, date_value, include_restfreq=True):
    hdu0 = fits.PrimaryHDU()
    hdu0.header["SPPOINT"] = 0
    hdu0.header["OBJECT"] = "W3(OH)"
    hdu0.header["LONGITUD"] = 27.6853
    hdu0.header["LATITUDE"] = -25.8897
    hdu0.header["TAMBIENT"] = 22.5
    hdu0.header["HUMIDITY"] = 38
    hdu0.header["FOCUS"] = 3.1
    hdu0.header["EQUINOX"] = 2000.0
    hdu0.header["SPBW"] = 10.0
    hdu0.header["SPCHAN"] = N
    hdu0.header["SPTIME"] = 30.0
    hdu0.header["SPFS"] = 0.0
    hdu0.header["SPVLSR"] = -4.2
    if include_restfreq:
        hdu0.header["RESTFREQ"] = 1420.405
    hdu0.header[date_key] = date_value
    return hdu0


def make_good_date(path: Path) -> None:
    """A well-formed file using the DATE convention -- load_file() should succeed."""
    hdu0 = _primary("DATE", "2026-08-12")
    hdu1 = _hdu1()
    hdu2, hdu3 = _hdu2_hdu3()
    fits.HDUList([hdu0, hdu1, hdu2, hdu3]).writeto(path, overwrite=True)


def make_good_dateobs(path: Path) -> None:
    """A well-formed file using the DATE-OBS convention -- load_file() should
    KeyError on the missing DATE key, forcing fallback to load_file2().

    NOTE: load_file2.py has no TCAL1->TSYS1 derivation (unlike load_file.py),
    so a genuinely valid DATE-OBS file must carry TSYS1/TSYSERR1/TSYS2/
    TSYSERR2 directly -- TCAL1 alone is not enough for load_file2 to succeed.
    """
    hdu0 = _primary("DATE-OBS", "2026-08-12T14:03:00")
    hdu1 = _hdu1()
    hdu2, hdu3 = _hdu2_hdu3()
    hdu3.header["TSYS1"] = 1.23
    hdu3.header["TSYSERR1"] = 0.01
    hdu3.header["TSYS2"] = 1.19
    hdu3.header["TSYSERR2"] = 0.01
    fits.HDUList([hdu0, hdu1, hdu2, hdu3]).writeto(path, overwrite=True)


def make_unrecognized(path: Path) -> None:
    """Neither DATE nor DATE-OBS, and missing TCAL1 too -- both loaders should fail."""
    hdu0 = fits.PrimaryHDU()
    hdu0.header["SPPOINT"] = 0
    hdu0.header["OBJECT"] = "UNKNOWN"
    hdu1 = _hdu1()
    hdu2 = fits.BinTableHDU.from_columns([
        fits.Column(name="Vlsr", format="E", array=np.linspace(-20, 20, N)),
        fits.Column(name="Polstate1", format="E", array=np.random.normal(5, 1, N)),
        fits.Column(name="Polstate4", format="E", array=np.random.normal(5, 1, N)),
    ])
    hdu2.header["TUNIT2"] = "K"
    hdu2.header["POSITION"] = "ON"
    hdu3 = fits.BinTableHDU.from_columns([
        fits.Column(name="Count1", format="E", array=np.random.normal(100, 5, N)),
    ])
    # deliberately no TCAL1 in hdu3.header
    fits.HDUList([hdu0, hdu1, hdu2, hdu3]).writeto(path, overwrite=True)


def make_truncated(path: Path) -> None:
    """A file that's corrupt/incomplete at the byte level, not just wrong convention."""
    make_good_date(path)
    with open(path, "r+b") as f:
        f.truncate(1024)


def build_all(output_dir: Path) -> dict[str, Path]:
    """Write all fixtures into output_dir, return {name: path}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "good_date.fits": make_good_date,
        "good_dateobs.fits": make_good_dateobs,
        "unrecognized.fits": make_unrecognized,
        "truncated.fits": make_truncated,
    }
    paths = {}
    for name, builder in files.items():
        path = output_dir / name
        builder(path)
        paths[name] = path
    return paths


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./fixtures_out")
    written = build_all(target)
    for name, path in written.items():
        print(f"{name} -> {path}")
        