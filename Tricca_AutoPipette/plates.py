#!/usr/bin/env python3
"""Holds the various plate classes."""
from coordinate import Coordinate
from typing import List, Optional, Callable
from abc import ABC, abstractmethod
import math


class Well:
    """A vessel to hold chemicals."""

    class DipStrategies:
        """A variety of functions to define how to dip into a well.

        Add new strategies to DIP_DIST_FUNCS dictionary.
        """

        @staticmethod
        def simple(well: 'Well', vol: float) -> float:
            """Return the dip distance without modification."""
            return well.dip_curr

        @staticmethod
        def cylinder(well: 'Well', vol: float) -> float:
            """Return the dip distance of a liquid in a cylinder."""
            # Make sure dip_btm is defined and return just the top if not
            if well.dip_btm is None:
                raise ValueError("dip_btm must be set for cylinder strategy")
            # Calculate the change in height from taking out liquid
            well.dip_curr = well.dip_curr - \
                (vol / (math.pi * (well.diameter / 2.0)**2))
            # Make sure the dip distance never becomes lower than the dip_btm
            if well.dip_curr < well.dip_btm:
                well.dip_curr = well.dip_btm
            return well.dip_curr

    DIP_FUNCS = {"simple": DipStrategies.simple,
                 "cylinder": DipStrategies.cylinder,
                 # Reverse the mapping as well so we can save in config
                 DipStrategies.simple: "simple",
                 DipStrategies.cylinder: "cylinder"}

    def __init__(self,
                 coor: Coordinate,
                 dip_top: float, dip_btm: Optional[float] = None,
                 dip_dist_func:
                     Optional[Callable[['Well', float], float]] = None,
                 diameter: Optional[float] = None):
        """Initialize a well."""
        self.coor = coor
        self.dip_top = dip_top
        self.dip_btm = dip_btm
        # Always start at the top of the well
        self.dip_curr = dip_top
        self.dip_dist_func = dip_dist_func
        self.diameter = diameter
        if (dip_dist_func == Well.DipStrategies.cylinder
           and (diameter is None or dip_btm is None)):
            raise ValueError(
                "diameter and dip_btm required for cylinder strategy")

    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into a well."""
        if self.dip_dist_func:
            return self.dip_dist_func(self, vol)
        return self.dip_top


class Plate(ABC):
    """Generate and manage wells to pipette into."""

    start_coor: Coordinate
    num_row: int
    num_col: int
    spacing_row: float
    spacing_col: float
    curr: int
    wells: List[Well]

    def __init__(self,
                 start_coor: Coordinate,
                 well: Well,
                 num_row: int, num_col: int,
                 spacing_row: float, spacing_col: float):
        """Initialize by creating all wells on the plate."""
        self.start_coor = start_coor
        self.num_row = num_row
        self.num_col = num_col
        self.spacing_row = spacing_row
        self.spacing_col = spacing_col
        self.wells = self._gen_wells(start_coor, well,
                                     num_row, num_col,
                                     spacing_row, spacing_col)
        self.curr = 0

    def __repr__(self) -> str:
        """Representation in string form."""
        return "plate"

    @abstractmethod
    def _gen_wells(self,
                   start_coor: Coordinate,
                   well: Well,
                   num_row: int, num_col: int,
                   spacing_row: float, spacing_col: float) -> List[Well]:
        """Generate all the coordinates for the plate."""
        pass

    @abstractmethod
    def get_coor(self, row: int, col: int) -> Optional[Coordinate]:
        """Return a coordinate at a specific row and column.

        Zero indexed. If error, return nothing.
        """
        pass

    @abstractmethod
    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into a well."""
        pass

    @abstractmethod
    def next(self) -> Coordinate:
        """Return the next coordinate.

        Restart if the last has been returned.
        """
        pass


class PlateArray(Plate):
    """Generate and manage wells to pipette into."""

    def __init__(self,
                 start_coor: Coordinate,
                 well: Well,
                 num_row: int, num_col: int,
                 spacing_row: float, spacing_col: float):
        """Initialize by creating all coordinates on the plate."""
        super().__init__(start_coor, well,
                         num_row, num_col,
                         spacing_row, spacing_col)

    def __repr__(self) -> str:
        """Representation in string form."""
        return "platearray"

    def _gen_wells(self,
                   start_coor: Coordinate,
                   well: Well,
                   num_row: int, num_col: int,
                   spacing_row: float, spacing_col: float) -> List[Well]:
        """Generate all the coordinates for the plate."""
        if num_row is None:
            num_row = 1
        if num_col is None:
            num_col = 1
        if spacing_row is None:
            spacing_row = 0
        if spacing_col is None:
            spacing_col = 0
        wells = []
        x_start = start_coor.x
        y_start = start_coor.y
        z_start = start_coor.z
        for row in range(num_row):
            for col in range(num_col):
                x = x_start - (col * spacing_col)
                y = y_start + (row * spacing_row)
                z = z_start
                new_well = Well(
                    Coordinate(x, y, z),
                    well.dip_top,
                    well.dip_btm,
                    well.dip_dist_func,
                    diameter=well.diameter)
                wells.append(new_well)
        return wells

    def get_coor(self, row: int, col: int) -> Optional[Coordinate]:
        """Return a coordinate at a specific row and column.

        Zero indexed. If error, return nothing.
        """
        if row >= self.num_row or row < 0:
            return
        if col >= self.num_col or col < 0:
            return
        index = col + self.num_col * row
        return self.wells[index].coor

    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into a well."""
        return self.wells[self.curr].get_dip_distance(vol)

    def next(self) -> Coordinate:
        """Return the next coordinate.

        Restart if the last has been returned.
        """
        if self.curr >= len(self.wells):
            self.curr = 0
        coor = self.wells[self.curr].coor
        self.curr += 1
        return coor


class PlateSingleton(PlateArray):
    """Generate and manage coordinates to pipette into."""

    def __init__(self,
                 start_coor: Coordinate,
                 well: Well,
                 num_row: int, num_col: int,
                 spacing_row: float, spacing_col: float):
        """Initialize by creating all coordinates on the plate."""
        super().__init__(start_coor, well, 1, 1, 0, 0)

    def __repr__(self) -> str:
        """Representation in string form."""
        return "platesingleton"

    def next(self) -> Coordinate:
        """Return the next coordinate.

        Singleton means there is only one coordinate, so return it.
        """
        return self.wells[0].coor


class TipBox(PlateArray):
    """A plate that contains the tips used in pipetting."""

    def __init__(self,
                 start_coor: Coordinate,
                 well: Well = None,
                 num_row: int = None, num_col: int = None,
                 spacing_row: float = None, spacing_col: float = None):
        """Initialize by creating all coordinates on the plate."""
        if num_row is None:
            num_row = 12
        if num_col is None:
            num_col = 8
        if spacing_row is None:
            spacing_row = 9
        if spacing_col is None:
            spacing_col = 9
        if well is None:
            well = Well(start_coor, 0, 0, Well.DipStrategies.simple, 7)
        super().__init__(start_coor,
                         well,
                         num_row, num_col,
                         spacing_row, spacing_col)

    def __repr__(self) -> str:
        """Representation in string form."""
        return "tipbox"

    def append_box(self, tipbox: 'TipBox'):
        """Append the coordinates of another TipBox."""
        self.wells = self.wells + tipbox.wells

    def get_dip_distance(self, vol: float = 0.0) -> float:
        """Return the distance to dip and grab a tip."""
        return super().get_dip_distance(vol)


class Garbage(PlateSingleton):
    """A garbage to hold used pipette tips."""

    def __init__(self,
                 start_coor: Coordinate,
                 well: Well = None,
                 num_row: int = None, num_col: int = None,
                 spacing_row: float = None, spacing_col: float = None):
        """Initialize by creating by calling super method."""
        # Can never have variation in how far it dips
        if well is None:
            well = Well(start_coor, 0, 0, Well.DipStrategies.simple, 7)
        super().__init__(start_coor, well, 1, 1, 0, 0)

    def __repr__(self) -> str:
        """Representation in string form."""
        return "garbage"

    def get_dip_distance(self, vol: float = 0.0) -> float:
        """Return the distance to dip and grab a tip."""
        return super().get_dip_distance(vol)


class PlateTypes:
    """A data class that holds meta-data on all the plate types."""

    # A full list of every Plate type
    TYPES = {
        "array": PlateArray,
        "singleton": PlateSingleton,
        "tipbox": TipBox,
        "garbage": Garbage
        }
