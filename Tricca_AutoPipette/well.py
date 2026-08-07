#!/usr/bin/env python3
"""Holds the Well class and the related DipStrategies."""
from __future__ import annotations
import math
from coordinate import Coordinate
from typing import Optional, Callable
from pydantic import BaseModel, confloat, model_validator


class DipStrategies:
    """A variety of functions to define how to dip into a well.

    Add new strategies to DIP_DIST_FUNCS dictionary.
    """

    @staticmethod
    def simple(well: Well, volume: float) -> float:
        """Return the dip distance without modification."""
        return well.dip_top

    @staticmethod
    def cylinder(well: Well, volume: float) -> float:
        """Return the dip distance of a liquid in a cylinder."""
        # Make sure dip_btm is defined and return just the top if not
        if well.dip_btm is None or well.diameter is None:
            raise ValueError(
                "Cylinder strategy requires diameter and dip_btm")
        # Calculate the change in height from taking out liquid
        radius = well.diameter / 2000  # Convert mm to meters
        height_change = (volume * 1e-9) / (math.pi * radius**2)  # m
        well.dip_curr += height_change * 1000  # Convert back to mm
        # Make sure to never dip further than dip_btm
        if well.dip_curr > well.dip_btm:
            well.dip_curr = well.dip_btm
        return well.dip_curr

    @staticmethod
    def FStube(well: Well, volume: float) -> float:
        """Return the dip distance of a liquid in the cone section of a 0.5mL screw cap tube."""
        # Make sure dip_btm is defined and return just the top if not
        if well.dip_btm is None or well.dip_vol is None:
            raise ValueError(
                "FStube strategy requires dip_btm and dip_vol")
        # Calculate the current height of liquid in the tube
        height_current = 2.61+0.0836*well.dip_vol+1e-4*(well.dip_vol**2)-1.83e-6*(well.dip_vol**3)
        # Calculate and update the new volume in the tube
        well.dip_vol = well.dip_vol - volume
        if well.dip_vol < 0:
            well.dip_vol = 0
        # Calculate the new height of the liquid in the vial
        height_new = 2.61+0.0836*well.dip_vol+1e-4*(well.dip_vol**2)-1.83e-6*(well.dip_vol**3)
        # Find the change in height of the liquid
        height_change = height_current - height_new # all already in mm
        well.dip_curr += height_change
        # Make sure to never dip further than dip_btm
        if well.dip_curr > well.dip_btm:
            well.dip_curr = well.dip_btm
        return well.dip_curr, well.dip_vol


class WellParams(BaseModel):
    """A data validation class to hold Well related variables."""

    coor: Coordinate
    dip_top: confloat(gt=0)
    dip_btm: Optional[confloat(gt=0)] = None
    max_vol: Optional[confloat(gt=0)] = None
    dip_func: Optional[Callable[[Well, float], float]] = \
        DipStrategies.simple
    well_diameter: Optional[confloat(gt=0)] = None

    @model_validator(mode="after")
    def check_dependencies(self):
        """Make sure that all related variables are related properly."""
        if self.dip_func is not DipStrategies.simple:
            if self.well_diameter is None:
                raise ValueError(
                    f"Strategy: {Well.STRAT_TO_NAME[self.dip_func]} "
                    "is not valid without defining well_diameter.")
            if self.dip_btm is None:
                raise ValueError(
                    f"Strategy: {Well.STRAT_TO_NAME[self.dip_func]} "
                    "is not valid without defining dip_btm.")
        return self


class Well:
    """A vessel to hold chemicals."""

    STRATEGIES: list[str] = ["simple", "cylinder","FStube"]
    NAME_TO_STRAT: dict[str, Callable[[Well, float], float]] = {
        "simple": DipStrategies.simple,
        "cylinder": DipStrategies.cylinder,
        "FStube": DipStrategies.FStube,
    }
    STRAT_TO_NAME: dict[Callable[[Well, float], float], str] = {
        DipStrategies.simple: "simple",
        DipStrategies.cylinder: "cylinder",
        DipStrategies.FStube: "FStube",
    }

    def __init__(self,
                 coor: Coordinate,
                 dip_top: float,
                 dip_btm: Optional[float] = None,
                 max_vol: Optional[float] = None,
                 dip_func:
                     Optional[Callable[[Well, float], float]] = None,
                 diameter: Optional[float] = None):
        """Initialize a well."""
        self.coor = coor
        self.dip_top = dip_top
        self.dip_btm = dip_btm
        #initialize the starting volume
        self.dip_vol = max_vol
        # Always start at the top of the well
        self.dip_curr = dip_top
        self.dip_func = dip_func
        self.diameter = diameter

        if (dip_func == DipStrategies.cylinder
           and (diameter is None or dip_btm is None)):
            raise ValueError(
                "diameter and dip_btm required for cylinder strategy")

    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into a well."""
        if self.dip_func:
            return self.dip_func(self, vol)
        return self.dip_top
