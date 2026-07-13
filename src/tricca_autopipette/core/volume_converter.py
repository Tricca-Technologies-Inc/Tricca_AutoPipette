#!/usr/bin/env python3
"""Volume converter for translating between microliters and motor steps.

This module provides conversion between liquid volumes (microliters) and
stepper motor positions (microsteps) for precise pipetting control.
"""
from __future__ import annotations

from numpy.polynomial import Polynomial


class VolumeConverter:
    """Convert between motor steps and liquid volume.

    Uses polynomial fitting to translate between microliters (µL) and
    motor microsteps (µsteps) for accurate pipette volume control.
    The converter can be initialized with default calibration data or
    custom calibration points.

    Class Attributes:
        _consts: Default calibration mapping of volumes (µL) to steps (µsteps).
        _poly: Default polynomial fit for volume-to-steps conversion.

    Attributes:
        _poly: Polynomial function for converting volume to steps.
    """

    # Default calibration mapping: volume (µL) -> motor steps (µsteps)
    _consts: dict[float, float] = {
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
        to motor steps. If no calibration data is provided, uses default
        values.

        Args:
            x: List of volume values in microliters (µL), or None for defaults.
            y: List of corresponding motor step values (µsteps), or None for defaults.

        Note:
            Uses quadratic (degree 2) polynomial fitting for custom calibration,
            versus linear (degree 1) for default calibration.

        Example:
            >>> # Use default calibration
            >>> converter = VolumeConverter()
            >>>
            >>> # Use custom calibration
            >>> volumes = [0.0, 50.0, 100.0, 200.0]
            >>> steps = [0.0, 25.0, 50.0, 100.0]
            >>> converter = VolumeConverter(x=volumes, y=steps)
        """
        if x is None:
            x = list(self._consts.keys())
        if y is None:
            y = list(self._consts.values())

        # TODO Change to degree 1?
        self._poly = Polynomial.fit(x, y, deg=2).convert()

    def vol_to_steps(self, vol_ul: float) -> float:
        """Convert volume in microliters to motor steps.

        Uses the fitted polynomial to calculate the number of motor
        microsteps needed to dispense the specified volume.

        Args:
            vol_ul: Volume to dispense in microliters (µL).

        Returns:
            Number of motor microsteps (µsteps) required.

        Example:
            >>> converter = VolumeConverter()
            >>> steps = converter.vol_to_steps(100.0)
            >>> steps
            39.25
        """
        return float(self._poly(vol_ul))

    def steps_to_vol(self, steps: float) -> float:
        """Convert motor steps to volume in microliters.

        Performs inverse calculation to determine the volume corresponding
        to a given number of motor steps. Uses root-finding on the polynomial.

        Args:
            steps: Number of motor microsteps (µsteps).

        Returns:
            Corresponding volume in microliters (µL).

        Raises:
            ValueError: If no valid positive volume can be found for the given steps.

        Note:
            For polynomials of degree > 1, this may have multiple solutions.
            Returns the positive real root closest to the expected range.

        Example:
            >>> converter = VolumeConverter()
            >>> volume = converter.steps_to_vol(39.25)
            >>> volume
            100.0
        """
        # Create polynomial: steps - poly(vol) = 0
        roots_poly = self._poly - steps
        roots = roots_poly.roots()

        # Filter for positive real roots
        valid_roots = [r.real for r in roots if r.imag == 0 and r.real >= 0]

        if not valid_roots:
            raise ValueError(f"No valid volume found for {steps} steps")

        # Return the smallest positive root (most likely solution)
        return float(min(valid_roots))

    def get_calibration_points(self) -> tuple[list[float], list[float]]:
        """Get the current calibration data points.

        Returns:
            Tuple of (volumes, steps) lists used for polynomial fitting.

        Example:
            >>> converter = VolumeConverter()
            >>> volumes, steps = converter.get_calibration_points()
            >>> volumes
            [0.0, 25.0, 50.0, 100.0, 200.0, 300.0, 400.0]
        """
        # Extract from the default constants as representation
        volumes = list(self._consts.keys())
        steps = list(self._consts.values())
        return volumes, steps
