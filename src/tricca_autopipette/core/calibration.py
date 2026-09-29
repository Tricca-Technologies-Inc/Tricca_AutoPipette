"""Gravimetric syringe calibration session (issue #26).

A pure record of one calibration in progress: which target volumes to
dispense, the plunger travel each dispense actually commanded, and the mass
the operator weighed for it. `AutoPipetteService` owns one of these at a time
and drives the motion; this module holds no I/O.

The stored curve pairs each *measured* volume with the *commanded* travel,
never with the requested volume -- the requested volume is only what the old
curve thought that travel would deliver, which is exactly what is being
corrected.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

#: Fractions of usable capacity dispensed when the operator names no targets.
DEFAULT_TARGET_FRACTIONS = (0.1, 0.3, 0.5, 0.7, 0.9)

#: The liquid a pipette's base curve is measured with (ISO 8655's method).
CALIBRATION_LIQUID = "water"

CalibrationStep = Literal["dispense", "record", "preview", "commit"]


def default_targets(usable_ul: float) -> list[float]:
    """Spread target volumes across a syringe's usable range.

    Args:
        usable_ul: Usable syringe capacity in μL.

    Returns:
        One target per `DEFAULT_TARGET_FRACTIONS` entry, in μL.

    Example:
        >>> default_targets(98.0)
        [9.8, 29.4, 49.0, 68.6, 88.2]
    """
    return [round(usable_ul * f, 6) for f in DEFAULT_TARGET_FRACTIONS]


def mass_to_volume_ul(mass_g: float, density_g_ml: float) -> float:
    """Convert a weighed mass to the volume it occupies.

    Args:
        mass_g: Measured mass in grams.
        density_g_ml: Liquid density in g/mL.

    Returns:
        Volume in μL (``mass_g / density_g_ml`` mL, times 1000).

    Example:
        >>> round(mass_to_volume_ul(0.0493, 0.998), 6)
        49.398798
    """
    return mass_g / density_g_ml * 1000.0


@dataclass
class CalibrationPoint:
    """One dispense of a calibration session.

    Attributes:
        target_ul: Volume the old curve was asked to deliver.
        travel_mm: Plunger travel the dispense actually commanded.
        mass_g: Weighed mass, or None until recorded.
        volume_ul: Measured volume derived from ``mass_g``, or None.
    """

    target_ul: float
    travel_mm: float
    mass_g: float | None = None
    volume_ul: float | None = None


@dataclass
class CalibrationSession:
    """A calibration in progress, advanced strictly in order.

    Attributes:
        config_category: Category of the file the curve is written to:
            ``pipettes``, or ``system`` if the system file defines the
            pipette block (`JsonConfigManager.setting_source`).
        config_file: That file's name.
        key_prefix: Key path of the pipette block inside it (``""`` or
            ``"pipette."``).
        source: Location water is aspirated from.
        dest: Location dispensed into (the vessel on the balance).
        density_g_ml: Water's density, from its liquid profile.
        targets_ul: Target volumes, dispensed in this order.
        points: One entry per dispense done so far.
        previewed: Whether the fit has been shown since the last record.
    """

    config_category: str
    config_file: str
    key_prefix: str
    source: str
    dest: str
    density_g_ml: float
    targets_ul: list[float]
    points: list[CalibrationPoint] = field(default_factory=list[CalibrationPoint])
    previewed: bool = False

    @property
    def step(self) -> CalibrationStep:
        """The one call the session accepts next (besides abort/status)."""
        if self.points and self.points[-1].mass_g is None:
            return "record"
        if len(self.points) < len(self.targets_ul):
            return "dispense"
        return "commit" if self.previewed else "preview"

    @property
    def index(self) -> int:
        """Zero-based index of the point being dispensed or recorded."""
        return len(self.points) - 1 if self.step == "record" else len(self.points)

    def measured(self) -> tuple[list[float], list[float]]:
        """Return the recorded ``(volumes_ul, travel_mm)`` pairs.

        Returns:
            Parallel lists, in dispense order.
        """
        done = [p for p in self.points if p.volume_ul is not None]
        return [p.volume_ul for p in done if p.volume_ul is not None], [
            p.travel_mm for p in done
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for a `CommandResult`'s ``data``.

        Returns:
            The session's fields plus ``step`` and ``index``.
        """
        return {**asdict(self), "step": self.step, "index": self.index}
