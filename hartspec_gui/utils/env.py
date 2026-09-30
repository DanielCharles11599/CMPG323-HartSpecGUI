"""Minimal, dependency-free .env loader.

Deliberately NOT python-dotenv -- the project's pinned requirements.txt
only lists streamlit/plotly/dash/astropy/numpy/scipy/pandas/pytest/
pytest-cov. Adding python-dotenv would be a perfectly reasonable one-line
dependency, but it's a real addition to the pinned stack, so it's flagged
as a choice here rather than silently added -- swap this module out for
`from dotenv import load_dotenv` if the team would rather have the real
package (handles quoting/multiline/export-prefix edge cases this doesn't).

Format supported: `KEY=VALUE` per line, `#` starts a comment, blank lines
ignored, surrounding quotes on VALUE are stripped. No escaping, no
multiline values, no `export KEY=VALUE` shell syntax -- matches the
project's actual current need (a couple of local path overrides), not a
general-purpose parser.

Existing environment variables are never overwritten by .env -- a real
`$env:X = "..."` set in the shell always wins, matching standard dotenv
semantics. This makes CI/teammate machines safe: if FITS_ARCHIVE_PATH
is already set in the environment, .env's copy of that key is ignored.
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_env_file(start: Path, max_up: int = 5) -> Path | None:
    """Walk upward from `start` looking for a `.env` file, capped at max_up levels."""
    current = start
    for _ in range(max_up):
        candidate = current / ".env"
        if candidate.is_file():
            return candidate
        if current.parent == current:  # reached filesystem root
            break
        current = current.parent
    return None


def load_dotenv_if_present() -> Path | None:
    """Load a `.env` file into os.environ if one can be found nearby.

    Searches upward from the current working directory first (covers
    `streamlit run Home.py` from the repo root or from hartspec_gui/, and
    `pytest` from the repo root), then falls back to searching upward from
    this file's own location (covers less common invocation patterns).

    Returns the path that was loaded, or None if no .env file was found
    (not an error -- .env is optional; real env vars work fine without it).
    """
    env_path = _find_env_file(Path.cwd()) or _find_env_file(Path(__file__).resolve().parent)
    if env_path is None:
        return None

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

    return env_path
    