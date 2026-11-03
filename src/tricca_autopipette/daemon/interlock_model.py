"""Compile-time copy of Klipper's collision interlock, for protocol validation.

Issue #149 (TAP-8). A protocol uploads and prints as one file, so a line
Klipper's interlock refuses aborts the run part-way. ``validate_protocol``
feeds the G-code each line emits through :class:`InterlockModel`, which
tracks raw Z, the G90/G91 mode, each plate's position and the homed state,
and reports what Klipper would refuse under umbrella §6.2's rules I1, I2
(with each plate's tip-safe list, addendum D39), I4, I6 and the plunger's
stage-2 soft limits. Plate travel limits need no check here: tapd refuses an
out-of-range ``plate_move`` before emitting it.

Klipper stays the authority; this is advisory. It reads only the G-code tapd
emits (``G1``, ``G90``/``G91``, ``G28``, ``PLATE_MOVE``, ``PLATES_IN``) and
assumes no G-code offset, so tapd's Z is raw Z.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from tricca_autopipette.daemon.moonraker_state import AxisConfig

#: Klipper's own tolerance on Z comparisons (``plate-macros.cfg``).
_EPS = 0.001

Severity = Literal["error", "warning"]


class InterlockModel:
    r"""Klipper's interlock state, advanced by the G-code a protocol emits.

    An axis that isn't homed when validation starts is assumed homed (plates
    in, Z raised), like validation assumes the gantry is: the operator homes
    before running. The first line whose G-code depends on such an axis gets
    one ``warning``; a rule the protocol itself breaks is an ``error``. A
    refused command still updates the model, as if the author had fixed it,
    so one mistake doesn't hide the next.

    Example:
        >>> from tricca_autopipette.daemon.moonraker_state import PlateAxis
        >>> axes = AxisConfig(
        ...     plates=(PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),),
        ...     z_safe=0.0,
        ...     park_tol=0.1,
        ... )
        >>> model = InterlockModel(
        ...     axes, z=0.0, plates={"plate1": 200.0}, plunger_homed=False
        ... )
        >>> [message for _, message in model.check(["G1 Z5\n"])]
        ['Klipper will refuse this (I2): plate1 not at a tip-safe position (200 mm).']
    """

    def __init__(
        self,
        config: AxisConfig,
        *,
        z: float | None,
        plates: Mapping[str, float],
        plunger_homed: bool,
    ) -> None:
        """Seed the model from live state at the start of validation.

        Args:
            config: Klipper's plate/plunger axis config.
            z: Live raw Z, or None if Z isn't homed.
            plates: Position of each homed plate (the compile-time drawer
                model, ``LocationManager.drawer_positions``); a plate missing
                here isn't homed.
            plunger_homed: Whether the plunger is homed.
        """
        self._config = config
        self._z_safe = config.z_safe or 0.0
        self._tol = config.park_tol or 0.0
        self._z = 0.0 if z is None else z
        self._absolute = True
        self._plates = {p.name: plates.get(p.name, 0.0) for p in config.plates}
        self._assumed = {p.name for p in config.plates if p.name not in plates}
        if z is None:
            self._assumed.add("Z")
        if config.pipette is not None and not plunger_homed:
            self._assumed.add("plunger")
        self._out: list[tuple[Severity, str]] = []

    def check(self, gcode: Iterable[str]) -> list[tuple[Severity, str]]:
        """Advance the model over one protocol line's G-code.

        Args:
            gcode: The G-code lines, as emitted (comments and blanks ignored).

        Returns:
            ``(severity, message)`` per problem, in order, without repeats.
        """
        self._out = []
        for line in gcode:
            words = line.split(";", 1)[0].split()
            if words:
                self._command(words[0].upper(), words[1:])
        return list(dict.fromkeys(self._out))

    def _need(self, axis: str, rule: str) -> None:
        if axis in self._assumed:
            self._assumed.discard(axis)
            self._out.append((
                "warning",
                f"{axis} is not homed now; Klipper will refuse this ({rule}) "
                "unless it is homed before the run.",
            ))

    def _refuse(self, rule: str, reason: str) -> None:
        self._out.append(("error", f"Klipper will refuse this ({rule}): {reason}."))

    def _tip_low(self) -> str | None:
        if self._z > self._z_safe + _EPS:
            return f"Z {self._z:g} > z_safe {self._z_safe:g}"
        return None

    def _command(self, command: str, args: list[str]) -> None:
        if command == "G90":
            self._absolute = True
        elif command == "G91":
            self._absolute = False
        elif command == "G1":
            self._move({a[0].upper(): float(a[1:]) for a in args})
        elif command == "G28":
            self._home({a.upper() for a in args})
        elif command in {"PLATE_MOVE", "PLATES_IN"}:
            params = dict(a.split("=", 1) for a in args)
            moving = (
                {params["PLATE"]: float(params["POS"])}
                if command == "PLATE_MOVE"
                else dict.fromkeys(self._plates, 0.0)
            )
            self._need("Z", "I1")
            low = self._tip_low()
            if low is not None:
                self._refuse("I1", f"tip below safe height ({low})")
            for name in moving:
                self._need(name, "I1")
            self._plates.update(moving)

    def _move(self, words: dict[str, float]) -> None:
        z_target = self._z
        if "Z" in words:
            z_target = words["Z"] if self._absolute else self._z + words["Z"]
        if z_target > self._z_safe + _EPS and z_target > self._z + _EPS:
            for plate in self._config.plates:
                self._need(plate.name, "I2")
                pos = self._plates[plate.name]
                if not any(abs(pos - safe) <= self._tol for safe in plate.safe_stops):
                    self._refuse(
                        "I2", f"{plate.name} not at a tip-safe position ({pos:g} mm)"
                    )
                    break
        self._z = z_target
        pipette = self._config.pipette
        if pipette is not None and pipette.letter in words:
            self._need("plunger", "I6")
            pos = words[pipette.letter]
            low, high = pipette.position_min, pipette.position_max
            # ponytail: absolute P only; a relative P move needs P tracked.
            if (
                self._absolute
                and low is not None
                and high is not None
                and not low <= pos <= high
            ):
                self._refuse("soft limit", f"P {pos:g} outside {low:g} to {high:g}")

    def _home(self, letters: set[str]) -> None:
        if not letters:  # bare G28: gantry, every plate, the plunger
            self._z = 0.0
            self._plates = dict.fromkeys(self._plates, 0.0)
            self._assumed.clear()
            return
        if letters & {"X", "Y", "Z"}:  # Klipper parks Z at 0 after
            self._z = 0.0
            if "Z" in letters:
                self._assumed.discard("Z")
        plates = [p.name for p in self._config.plates if p.letter in letters]
        if plates:
            self._need("Z", "I4")
            low = self._tip_low()
            if low is not None:
                self._refuse(
                    "I4", f"home Z and raise the tip before homing plates ({low})"
                )
            for name in plates:
                self._plates[name] = 0.0
                self._assumed.discard(name)
        pipette = self._config.pipette
        if pipette is not None and pipette.letter in letters:
            self._assumed.discard("plunger")
