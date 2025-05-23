#!/usr/bin/env python3
"""Holds the volume converter class which converts between uL and usteps.

Also holds constants important to volume conversion.
"""
from numpy.polynomial import Polynomial


class VolumeConverter:
    """Convert motor steps into a volume in ul."""

    # Mapping between uL and uSteps
    _consts = {0.0: 0,
               25.0: 14.35,
               50.0: 22.45,
               100.0: 39.25,
               200.0: 78.50,
               300.0: 117.75,
               400.0: 157.00}
    # Polynomial to get proper uL
    _poly = Polynomial.fit(list(_consts.keys()), list(_consts.values()), 1)
    _poly = _poly.convert()
    # Number of steps to dispense
    dist_disp = 46

    def __init__(self, x: list[float] = None, y: list[float] = None):
        """Initialize the variables to estimate volume."""
        if (x is None):
            x = list(self._consts.keys())
        if (y is None):
            y = list(self._consts.values())
        self._poly = Polynomial.fit(x, y, 2)
        self._poly = self._poly.convert()

    def vol_to_steps(self, vol_ul):
        """Take a volume in microliter, return a number of steps."""
        return self._poly(vol_ul)
