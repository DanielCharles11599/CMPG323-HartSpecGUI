from __future__ import annotations

from typing import Any, Mapping
from pathlib import Path

import numpy as np
import streamlit as st

from utils import fits_ingest

SpectrumDict = dict[str, Any]
THIS_STAGE_KEY = "03_bandpass_correction"
MODE_OPTIONS = ["Frequency Switch", "Position Switch"]
_REQUIRED_SPECTRUM_KEYS = ("Vlsr", "LCP", "RCP")


def _validate_spectrum(spec: SpectrumDict, number: int) -> None:
    missing = [key for key in _REQUIRED_SPECTRUM_KEYS if key not in spec]
    if missing:
        raise ValueError(
            f"Spectrum {number} is missing required field(s): {', '.join(missing)}."
        )

    try:
        vlsr = np.asarray(spec["Vlsr"])
        lcp = np.asarray(spec["LCP"])
        rcp = np.asarray(spec["RCP"])
    except Exception as exc:
        raise ValueError(f"Spectrum {number} contains invalid spectrum arrays: {exc}") from exc

    if not (len(vlsr) == len(lcp) == len(rcp)):
        raise ValueError(
            f"Spectrum {number} has inconsistent array lengths: "
            f"Vlsr={len(vlsr)}, LCP={len(lcp)}, RCP={len(rcp)}."
        )


def _validate_pair_lengths(spec1: SpectrumDict, spec2: SpectrumDict) -> None:
    for key in ("LCP", "RCP"):
        length1 = len(np.asarray(spec1[key]))
        length2 = len(np.asarray(spec2[key]))
        if length1 != length2:
            raise ValueError(
                f"The two spectra have different {key} channel counts "
                f"({length1} vs {length2}) and cannot be bandpass corrected as a pair."
            )


def _target_filenames() -> list[str]:
    selection = st.session_state.get("pipeline_data", {}).get("01_source_browser", {})
    selected = selection.get("selected_files") or []
    if selected:
        return [str(value) for value in selected]
    return [str(value) for value in st.session_state.get("file_loader_target_filenames", [])]


def get_loaded_entries() -> list[dict[str, Any]]:
    """Return successfully loaded FITS files in Page 01/02 order.

    The CLC workflow treats each observation directory independently.  When
    an ``observation_list.txt`` exists beside the FITS files, its filename
    order is used; otherwise the Page 01 selection order is retained.
    """
    cached_results = {
        filename: st.session_state.get(f"file_loader_ingest_result::{filename}")
        for filename in _target_filenames()
    }

    entries: list[dict[str, Any]] = []
    for filename, result in cached_results.items():
        if result is None or not getattr(result, "ok", False):
            continue
        spectrum = getattr(result, "spectrum", None)
        if spectrum is None:
            continue

        try:
            pointing = int(spectrum.get("pointing"))
        except (TypeError, ValueError):
            pointing = None

        position = str(spectrum.get("position", "")).strip().upper()
        path = getattr(result, "path", None)
        observation_dir = str(path.parent) if path is not None else ""
        entries.append(
            {
                "filename": filename,
                "spectrum": spectrum,
                "pointing": pointing,
                "position": position,
                "observation_dir": observation_dir,
            }
        )

    if not entries:
        for index, spectrum in enumerate(st.session_state.get("loaded_spectra", [])):
            try:
                pointing = int(spectrum.get("pointing"))
            except (TypeError, ValueError):
                pointing = None
            entries.append(
                {
                    "filename": f"Loaded spectrum {index + 1}",
                    "spectrum": spectrum,
                    "pointing": pointing,
                    "position": str(spectrum.get("position", "")).strip().upper(),
                    "observation_dir": "",
                }
            )

    return entries


def _observation_list_order(observation_dir: str) -> dict[str, int]:
    """Read CLC's observation_list.txt when it is available."""
    if not observation_dir:
        return {}
    list_path = Path(observation_dir) / "observation_list.txt"
    if not list_path.is_file():
        return {}

    order: dict[str, int] = {}
    try:
        for index, line in enumerate(list_path.read_text(encoding="utf-8", errors="replace").splitlines()):
            parts = line.split()
            if parts:
                order[Path(parts[0]).name] = index
    except OSError:
        return {}
    return order


def get_full_integration_pairs(entries: list[dict[str, Any]] | None = None) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair SPPOINT=0 files within each observation, matching HartSpec."""
    entries = get_loaded_entries() if entries is None else entries

    by_observation: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_observation.setdefault(entry.get("observation_dir", ""), []).append(entry)

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for observation_dir, observation_entries in by_observation.items():
        order = _observation_list_order(observation_dir)
        if order:
            observation_entries = sorted(
                observation_entries,
                key=lambda entry: order.get(Path(entry["filename"]).name, 10**9),
            )

        full_integrations = [entry for entry in observation_entries if entry.get("pointing") == 0]
        for index in range(0, len(full_integrations) - 1, 2):
            first = full_integrations[index]
            second = full_integrations[index + 1]

            # HartSpec expects ON first for a position-switched pair.
            if first.get("position") == "OFF" and second.get("position") == "ON":
                first, second = second, first

            pairs.append((first, second))

    return pairs


def suggest_mode(pair: tuple[dict[str, Any], dict[str, Any]]) -> tuple[str | None, str]:
    """Suggest the CLC mode without silently forcing it."""
    second_position = str(pair[1].get("position", "")).strip().upper()
    if second_position == "ON":
        return "Frequency Switch", "second full-integration file is ON"
    if second_position == "OFF":
        return "Position Switch", "second full-integration file is OFF"
    return None, "POSITION metadata is unavailable or unrecognised"


def freq_switch_correct(spec1: SpectrumDict, spec2: SpectrumDict) -> tuple[SpectrumDict, SpectrumDict]:
    """GUI-safe reproduction of clc/Baseline.py::freq_switch()."""
    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)
    _validate_pair_lengths(spec1, spec2)

    vlsr1 = np.asarray(spec1["Vlsr"])
    vlsr2 = np.asarray(spec2["Vlsr"])
    lcp1 = np.asarray(spec1["LCP"]) - np.asarray(spec2["LCP"])
    lcp2 = np.asarray(spec2["LCP"]) - np.asarray(spec1["LCP"])
    rcp1 = np.asarray(spec1["RCP"]) - np.asarray(spec2["RCP"])
    rcp2 = np.asarray(spec2["RCP"]) - np.asarray(spec1["RCP"])

    common1 = np.isin(vlsr1, vlsr2)
    common2 = np.isin(vlsr2, vlsr1)

    new_spec1 = spec1.copy()
    new_spec2 = spec2.copy()
    new_spec1["Vlsr"] = vlsr1[common1]
    new_spec1["LCP"] = lcp1[common1]
    new_spec1["RCP"] = rcp1[common1]
    new_spec2["Vlsr"] = vlsr2[common2]
    new_spec2["LCP"] = lcp2[common2]
    new_spec2["RCP"] = rcp2[common2]
    return new_spec1, new_spec2


def pos_switch_correct(spec1: SpectrumDict, spec2: SpectrumDict) -> SpectrumDict:
    """GUI-safe reproduction of clc/Baseline.py::pos_switch()."""
    _validate_spectrum(spec1, 1)
    _validate_spectrum(spec2, 2)
    _validate_pair_lengths(spec1, spec2)

    new_spec = spec1.copy()
    new_spec["LCP"] = np.asarray(spec1["LCP"]) - np.asarray(spec2["LCP"])
    new_spec["RCP"] = np.asarray(spec1["RCP"]) - np.asarray(spec2["RCP"])
    return new_spec


def common_velocity_range(spec1: SpectrumDict, spec2: SpectrumDict) -> list[float]:
    """Return the exact shared Vlsr extent used for the FR-04 visual highlight."""
    v1 = np.asarray(spec1["Vlsr"], dtype=float).reshape(-1)
    v2 = np.asarray(spec2["Vlsr"], dtype=float).reshape(-1)
    shared = v1[np.isin(v1, v2)]
    if shared.size:
        return [float(np.min(shared)), float(np.max(shared))]
    return []


def build_bandpass_result(mode: str, pair: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    """Run FR-04 on the selected CLC-style full-integration pair."""
    if mode not in MODE_OPTIONS:
        raise ValueError(f"Unknown bandpass mode: {mode!r}. Expected one of {MODE_OPTIONS}.")

    entry1, entry2 = pair
    spec1 = entry1["spectrum"]
    spec2 = entry2["spectrum"]

    if mode == "Frequency Switch":
        corrected, _reverse = freq_switch_correct(spec1, spec2)
    else:
        corrected = pos_switch_correct(spec1, spec2)

    if np.asarray(corrected["Vlsr"]).size == 0:
        raise ValueError(
            "Bandpass correction produced no common velocity channels. "
            "The selected pair does not share the velocity grid required by the correction."
        )

    return {
        "mode": mode,
        "raw_spec1": spec1,
        "raw_spec2": spec2,
        "corrected": corrected,
        "filename1": entry1["filename"],
        "filename2": entry2["filename"],
        "common_velocity_range_kms": common_velocity_range(spec1, spec2),
    }


def stage_summary(mode: str, corrected: Mapping[str, Any]) -> dict[str, object]:
    vlsr = np.asarray(corrected["Vlsr"], dtype=float)
    return {
        "mode": mode,
        "n_channels": int(vlsr.size),
        "vlsr_range_kms": [float(vlsr.min()), float(vlsr.max())] if vlsr.size else [],
    }
