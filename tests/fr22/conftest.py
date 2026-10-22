# conftest.py — FR-22 focused checks independent of the legacy FITS fixture generator.
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "hartspec_gui"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
