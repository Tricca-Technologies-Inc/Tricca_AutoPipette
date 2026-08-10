#!/usr/bin/env python3
"""Volume converter for translating between microliters and plunger travel.

This module provides conversion between liquid volumes (microliters) and
syringe plunger positions for precise pipetting control.

.. warning::
   Everything here named "steps" is actually **millimetres**. The values
   returned by :meth:`VolumeConverter.vol_to_steps` are passed straight to
   Klipper's ``MANUAL_STEPPER ... MOVE=``, which takes millimetres (the
   ``[manual_stepper]`` ``rotation_distance`` setting is what converts mm to
   step pulses). The calibration table below is therefore a μL -> mm fit: 100 μL
   maps to 39.25 mm of travel, implying a bore of roughly 1.8 mm.

   The names are wrong, not the numbers -- the emitted G-code is correct.
   Renaming ``vol_to_steps``/``steps_to_vol`` is tracked as issue #29; it is
   deferred because both are public control-plane RPC and ``tap`` command
   surface and so need a deprecation alias.
"""

from __future__ import annotations

from typing import ClassVar

from numpy.polynomial import Polynomial


class VolumeConverter:
    """Convert between plunger travel (mm) and liquid volume.

    Uses polynomial fitting to translate between microliters (μL) and
    millimetres of plunger travel for accurate pipette volume control.
    Despite the "steps" naming throughout this class (see the module-level
    warning above), the values are millimetres, not motor microsteps.
    The converter can be initialized with default calibration data or
    custom calibration points.

    Class Attributes:
        _consts: Default calibration mapping of volumes (μL) to plunger
            travel (mm).
        _poly: Default polynomial fit for volume-to-travel conversion.

    Attributes:
        _poly: Polynomial function for converting volume to plunger travel.
    """

    # Default calibration mapping: volume (μL) -> plunger travel (mm)
    _consts: ClassVar[dict[float, float]] = {
        0.0: 0.0,
        25.0: 14.35,
        50.0: 22.45,
        100.0: 39.25,
        200.0: 78.50,
        300.0: 117.75,
        400.0: 157.00,
    }

    # Default polynomial fit (linear) from calibration data
    _poly = Polynomial.fit(
        list(_consts.keys()), list(_consts.values()), deg=1
    ).convert()

    def __init__(
        self, x: list[float] | None = None, y: list[float] | None = None
    ) -> None:
        """Initialize the volume converter with calibration data.

        Creates a polynomial fit from calibration points mapping volumes
        to plunger travel (mm). If no calibration data is provided, uses
        default values.

        Args:
            x: List of volume values in microliters (μL), or None for defaults.
            y: List of corresponding plunger-travel values (mm), or None for
                defaults.

        Note:
            Always uses linear (degree 1) polynomial fitting, for both
            default and custom calibration data — a quadratic fit was
            previously used here unconditionally regardless of the ``x``/``y``
            arguments (a bug, since it silently ignored this docstring's own
            claim of degree 1 for defaults), but degree doesn't meaningfully
            change the fit over this calibration range, so this settles on
            the simpler, originally-intended linear fit.

        Example:
            >>> # Use default calibration
            >>> converter = VolumeConverter()
            >>>
            >>> # Use custom calibration
            >>> volumes = [0.0, 50.0, 100.0, 200.0]
            >>> travel_mm = [0.0, 25.0, 50.0, 100.0]
            >>> converter = VolumeConverter(x=volumes, y=travel_mm)
        """
        if x is None:
            x = list(self._consts.keys())
        if y is None:
            y = list(self._consts.values())

        self._poly = Polynomial.fit(x, y, deg=1).convert()

    def vol_to_steps(self, vol_ul: float) -> float:
        """Convert volume in microliters to plunger travel (mm).

        Uses the fitted polynomial to calculate the plunger travel, in
        millimetres, needed to dispense the specified volume. Named
        "steps" for historical reasons (see the module-level warning) —
        the return value is millimetres, not a motor step count.

        Args:
            vol_ul: Volume to dispense in microliters (μL).

        Returns:
            Plunger travel required, in millimetres.

        Example:
            >>> converter = VolumeConverter()
            >>> travel_mm = converter.vol_to_steps(100.0)
            >>> travel_mm
            40.64175291073736
        """
        return float(self._poly(vol_ul))

    def steps_to_vol(self, steps: float) -> float:
        """Convert plunger travel (mm) to volume in microliters.

        Performs inverse calculation to determine the volume corresponding
        to a given plunger travel. Uses root-finding on the polynomial.
        Named "steps" for historical reasons (see the module-level warning)
        — the input is millimetres, not a motor step count.

        Args:
            steps: Plunger travel, in millimetres (despite the name).

        Returns:
            Corresponding volume in microliters (μL).

        Raises:
            ValueError: If no valid positive volume can be found for the given
                travel value.

        Note:
            The fitted polynomial is always linear (degree 1, see
            ``__init__``), so there is exactly one real root; root-finding is
            used anyway to keep this method correct if that ever changes.

        Example:
            >>> converter = VolumeConverter()
            >>> volume = converter.steps_to_vol(39.25)
            >>> volume
            96.39585992489044
        """
        # Create polynomial: steps - poly(vol) = 0
        roots_poly = self._poly - steps
        roots = roots_poly.roots()

        # Filter for positive real roots
        valid_roots = [r.real for r in roots if r.imag == 0 and r.real >= 0]

        if not valid_roots:
            raise ValueError(f"No valid volume found for {steps} mm of travel")

        # Return the smallest positive root (most likely solution)
        return float(min(valid_roots))

    def get_calibration_points(self) -> tuple[list[float], list[float]]:
        """Get the current calibration data points.

        Returns:
            Tuple of (volumes, plunger-travel) lists used for polynomial
            fitting, in (μL, mm).

        Example:
            >>> converter = VolumeConverter()
            >>> volumes, travel_mm = converter.get_calibration_points()
            >>> volumes
            [0.0, 25.0, 50.0, 100.0, 200.0, 300.0, 400.0]
        """
        # Extract from the default constants as representation
        volumes = list(self._consts.keys())
        steps = list(self._consts.values())
        return volumes, steps
