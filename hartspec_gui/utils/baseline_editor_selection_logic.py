# baseline_editor_selection_logic.py — FR-05: pure helpers for editable flat-baseline regions.
#
# PM feedback revision: selected ranges identify flat, line-free channels used to
# estimate the polynomial baseline. They are NOT exclusion masks and are NOT
# removed from the output spectrum. The fitted baseline is evaluated/subtracted
# across the complete velocity axis so spectral features remain downstream.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

VELOCITY_PRECISION_KMS = 0.1
SELECTION_SEMANTICS = "flat_baseline_fit_regions_v2"


@dataclass(frozen=True)
class VelocityRegion:
    """One editable, inclusive velocity range used as baseline-fit input."""

    start: float
    end: float

    def as_row(self, index: int) -> dict[str, float | int]:
        """Return the JSON-safe row shape expected by a Dash DataTable."""
        return {
            "block": index,
            "start": self.start,
            "end": self.end,
        }


class RegionValidationError(ValueError):
    """Raised when an edit would create an invalid baseline region."""


def quantize_velocity(value: Any, precision: float = VELOCITY_PRECISION_KMS) -> float:
    """Round one velocity to the editor's required precision.

    Python's binary floating-point representation can produce values such as
    ``4.1000000000000005``. The decimal-place rounding after quantisation keeps
    table values stable for JSON/session replay.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise RegionValidationError(f"Velocity value {value!r} is not numeric.") from exc

    if not np.isfinite(numeric):
        raise RegionValidationError("Velocity values must be finite numbers.")
    if precision <= 0:
        raise ValueError("precision must be positive")

    decimals = max(0, int(round(-np.log10(precision))))
    return round(round(numeric / precision) * precision, decimals)


def spectrum_velocity_bounds(vlsr: Sequence[float]) -> tuple[float, float]:
    """Return finite minimum/maximum bounds for the current Page 3 spectrum."""
    values = np.asarray(vlsr, dtype=float).reshape(-1)
    if values.size == 0:
        raise RegionValidationError("The spectrum contains no velocity channels.")
    if not np.all(np.isfinite(values)):
        raise RegionValidationError("The velocity axis contains NaN or infinite values.")
    return float(values.min()), float(values.max())


def validate_region(
    start: Any,
    end: Any,
    lower_bound: float,
    upper_bound: float,
    precision: float = VELOCITY_PRECISION_KMS,
) -> VelocityRegion:
    """Validate and quantise one proposed flat-region edit.

    The edit is rejected instead of silently clamped. This avoids a user typing
    a value outside the plotted range and unknowingly fitting a different region.
    Existing table rows should remain unchanged when this function raises.
    """
    start_value = quantize_velocity(start, precision)
    end_value = quantize_velocity(end, precision)
    lower = float(min(lower_bound, upper_bound))
    upper = float(max(lower_bound, upper_bound))

    if start_value >= end_value:
        raise RegionValidationError("Start velocity must be smaller than end velocity.")
    if start_value < lower or end_value > upper:
        raise RegionValidationError(
            f"Region must stay within the displayed velocity range "
            f"[{lower:.1f}, {upper:.1f}] km/s."
        )

    return VelocityRegion(start=start_value, end=end_value)


def _row_values(row: Mapping[str, Any]) -> tuple[Any, Any]:
    """Read start/end values from current or legacy bridge/table field names."""
    start = row.get("start", row.get("v_min", row.get("Start (km/s)")))
    end = row.get("end", row.get("v_max", row.get("End (km/s)")))
    return start, end


def validate_region_rows(
    rows: Iterable[Mapping[str, Any]] | None,
    lower_bound: float,
    upper_bound: float,
    precision: float = VELOCITY_PRECISION_KMS,
) -> list[VelocityRegion]:
    """Validate an editable table without mutating the submitted row objects."""
    validated: list[VelocityRegion] = []
    for index, row in enumerate(rows or [], start=1):
        start, end = _row_values(row)
        try:
            validated.append(
                validate_region(start, end, lower_bound, upper_bound, precision)
            )
        except RegionValidationError as exc:
            raise RegionValidationError(f"Region {index}: {exc}") from exc
    return validated


def regions_to_rows(regions: Sequence[VelocityRegion]) -> list[dict[str, float | int]]:
    """Convert canonical regions to sequentially numbered DataTable rows."""
    return [region.as_row(index) for index, region in enumerate(regions, start=1)]


def add_region(
    existing_rows: Iterable[Mapping[str, Any]] | None,
    start: Any,
    end: Any,
    lower_bound: float,
    upper_bound: float,
) -> list[dict[str, float | int]]:
    """Append a valid region and return a new table value.

    Validation happens before the new row is added, so an invalid proposal never
    destroys or partially modifies existing selections.
    """
    existing = validate_region_rows(existing_rows, lower_bound, upper_bound)
    proposed = validate_region(start, end, lower_bound, upper_bound)
    return regions_to_rows([*existing, proposed])


def update_region(
    existing_rows: Iterable[Mapping[str, Any]] | None,
    row_index: int,
    start: Any,
    end: Any,
    lower_bound: float,
    upper_bound: float,
) -> list[dict[str, float | int]]:
    """Replace one editable table row after full validation."""
    existing = validate_region_rows(existing_rows, lower_bound, upper_bound)
    if row_index < 0 or row_index >= len(existing):
        raise RegionValidationError("Select a valid table row before updating it.")

    replacement = validate_region(start, end, lower_bound, upper_bound)
    updated = list(existing)
    updated[row_index] = replacement
    return regions_to_rows(updated)


def delete_region(
    existing_rows: Iterable[Mapping[str, Any]] | None,
    row_index: int,
    lower_bound: float,
    upper_bound: float,
) -> list[dict[str, float | int]]:
    """Delete one table row and renumber the remaining regions."""
    existing = validate_region_rows(existing_rows, lower_bound, upper_bound)
    if row_index < 0 or row_index >= len(existing):
        raise RegionValidationError("Select a valid table row before deleting it.")
    remaining = [region for index, region in enumerate(existing) if index != row_index]
    return regions_to_rows(remaining)


def region_from_plotly_selection(
    selected_data: Mapping[str, Any] | None,
    lower_bound: float,
    upper_bound: float,
) -> VelocityRegion | None:
    """Translate an optional Plotly box selection into a 0.1 km/s region.

    Numeric start/end entry is the primary PM-requested interaction. This helper
    preserves drag selection only as an optional convenience and accepts the
    common ``selectedData['range']['x']`` shape used by Plotly/Dash.
    """
    if not selected_data:
        return None
    try:
        x_values = selected_data["range"]["x"]
        start, end = sorted((float(x_values[0]), float(x_values[1])))
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return validate_region(start, end, lower_bound, upper_bound)


def build_flat_fit_mask(
    vlsr: Sequence[float],
    regions: Sequence[VelocityRegion] | Iterable[Mapping[str, Any]],
) -> np.ndarray:
    """Return True only for selected flat channels used by the baseline fit.

    This is the deliberate reversal requested by the project managers. Legacy
    implementations often treated selected ranges as channels to mask/exclude.
    Here, selected ranges are the *included* fit samples.
    """
    velocity = np.asarray(vlsr, dtype=float).reshape(-1)
    lower, upper = spectrum_velocity_bounds(velocity)

    region_list = list(regions)
    if region_list and isinstance(region_list[0], VelocityRegion):
        canonical = list(region_list)  # type: ignore[list-item]
    else:
        canonical = validate_region_rows(region_list, lower, upper)  # type: ignore[arg-type]

    mask = np.zeros(velocity.shape, dtype=bool)
    for region in canonical:
        mask |= (velocity >= region.start) & (velocity <= region.end)
    return mask


def build_unselected_feature_mask(
    vlsr: Sequence[float],
    regions: Sequence[VelocityRegion] | Iterable[Mapping[str, Any]],
) -> np.ndarray:
    """Return channels outside flat regions, typically containing spectral features."""
    return ~build_flat_fit_mask(vlsr, regions)


def ensure_fit_has_enough_points(
    fit_mask: Sequence[bool],
    polynomial_order: int,
) -> None:
    """Reject a fit that has too few selected channels for its polynomial order."""
    mask = np.asarray(fit_mask, dtype=bool).reshape(-1)
    required = int(polynomial_order) + 1
    selected = int(mask.sum())
    if selected < required:
        raise RegionValidationError(
            f"Polynomial order {polynomial_order} requires at least {required} selected "
            f"baseline channels; only {selected} are currently selected."
        )


def subtract_baseline_preserving_all_channels(
    spectrum: Sequence[float],
    evaluated_baseline: Sequence[float],
) -> np.ndarray:
    """Subtract a precomputed baseline without dropping or masking any channels.

    The scientific baseline coefficients must still come from the existing CLC
    integration. This helper only enforces the PM-requested output shape: every
    input channel, including unselected spikes/emission, remains present.
    """
    values = np.asarray(spectrum, dtype=float).reshape(-1)
    baseline = np.asarray(evaluated_baseline, dtype=float).reshape(-1)
    if values.shape != baseline.shape:
        raise ValueError(
            "The evaluated baseline must have one value for every spectrum channel."
        )
    return values - baseline


def selection_metadata() -> dict[str, Any]:
    """Return JSON-safe semantics stored with the Page 4 session payload."""
    return {
        "selection_semantics": SELECTION_SEMANTICS,
        "selected_regions_are_masked": False,
        "fit_uses_selected_flat_regions": True,
        "output_preserves_full_velocity_axis": True,
        "velocity_precision_kms": VELOCITY_PRECISION_KMS,
    }
