#!/usr/bin/env python3
"""Holds the various plate classes."""
from coordinate import Coordinate


class Plate:
    """Generate and manage coordinates to pipette into."""

    def __init__(self, start_coor,
                 num_row, num_col,
                 spacing_row, spacing_col,
                 dip_distance):
        """Initialize by creating all coordinates on the plate."""
        self.coors = self._gen_well_plate_coors(start_coor,
                                                num_row, num_col,
                                                spacing_row, spacing_col)
        self.num_row = num_row
        self.num_col = num_col
        self.dip_distance = dip_distance
        self.curr = 0

    def _gen_well_plate_coors(self, start_coor,
                              num_row, num_col,
                              spacing_row, spacing_col):
        """Generate all the coordinates for the plate."""
        coors = []
        x_start = start_coor.x
        y_start = start_coor.y
        z_start = start_coor.z

        for row in range(num_row):
            for col in range(num_col):
                x = x_start - (col * spacing_col)
                y = y_start + (row * spacing_row)
                z = z_start
                coors.append(Coordinate(x, y, z))
        return coors

    def get_coors(self):
        """Return the list of every coordinate generated."""
        return self.coors

    def get_coor(self, row: int, col: int):
        """Return a coordinate at a specific row and column.

        Zero indexed. If error, return nothing.
        """
        if row >= self.num_row or row < 0:
            return
        if col >= self.num_col or col < 0:
            return
        index = col + self.num_col * row
        return self.coors[index]

    def next(self):
        """Return the next coordinate.

        Restart if the last has been returned.
        """
        if (self.curr < len(self.coors)):
            coor = self.coors[self.curr]
            self.curr += 1
            return coor
        else:
            self.curr = 1
            return self.coors[0]


class WellPlate(Plate):
    """A plate with various wells to pipette into."""

    dip_distance = 84.45

    def __init__(self, start_coor,
                 num_row=None, num_col=None,
                 spacing_row=None, spacing_col=None,
                 dip_distance=None):
        """Initialize by creating all coordinates on the plate."""
        if num_row is None:
            num_row = 12
        if num_col is None:
            num_col = 8
        if spacing_row is None:
            spacing_row = 9
        if spacing_col is None:
            spacing_col = 9
        if dip_distance is None:
            dip_distance = 84.45
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col,
                         dip_distance)

    def __repr__(_):
        """Representation in string form."""
        return "wellplate"


class TipBox(Plate):
    """A plate that contains the tips used in pipetting."""

    def __init__(self, start_coor,
                 num_row=None, num_col=None,
                 spacing_row=None, spacing_col=None,
                 dip_distance=None):
        """Initialize by creating all coordinates on the plate."""
        if num_row is None:
            num_row = 12
        if num_col is None:
            num_col = 8
        if spacing_row is None:
            spacing_row = 9
        if spacing_col is None:
            spacing_col = 9
        if dip_distance is None:
            dip_distance = 94.5
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col,
                         dip_distance)

    def __repr__(_):
        """Representation in string form."""
        return "tipbox"

    def append_box(self, tipbox):
        """Append the coordinates of another TipBox."""
        self.coors = self.coors + tipbox.coors


class VialHolder(Plate):
    """A plate that holds vials to pipette into."""

    def __init__(self, start_coor,
                 num_row=None, num_col=None,
                 spacing_row=None, spacing_col=None,
                 dip_distance=None):
        """Initialize by creating all coordinates on the plate."""
        if num_row is None:
            num_row = 7
        if num_col is None:
            num_col = 5
        if spacing_row is None:
            spacing_row = 18
        if spacing_col is None:
            spacing_col = 18
        if dip_distance is None:
            dip_distance = 115
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col,
                         dip_distance)

    def __repr__(_):
        """Representation in string form."""
        return "vialholder"


class Garbage(Plate):
    """A garbage to hold used pipette tips."""

    def __init__(self, start_coor,
                 num_row=None, num_col=None,
                 spacing_row=None, spacing_col=None,
                 dip_distance=None):
        """Initialize by creating by calling super method."""
        if num_row is None:
            num_row = 1
        if num_col is None:
            num_col = 1
        if spacing_row is None:
            spacing_row = 0
        if spacing_col is None:
            spacing_col = 0
        if dip_distance is None:
            dip_distance = 75
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col,
                         dip_distance)

    def __repr__(_):
        """Representation in string form."""
        return "garbage"


class TiltVial(Plate):
    """A tilted vial to hold the end product."""

    def __init__(self, start_coor,
                 num_row=None, num_col=None,
                 spacing_row=None, spacing_col=None,
                 dip_distance=None):
        """Initialize by creating by calling super method."""
        if num_row is None:
            num_row = 1
        if num_col is None:
            num_col = 1
        if spacing_row is None:
            spacing_row = 0
        if spacing_col is None:
            spacing_col = 0
        if dip_distance is None:
            dip_distance = 110
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col,
                         dip_distance)

    def __repr__(_):
        """Representation in string form."""
        return "tiltv"


class FalconTube(Plate):
    """A large tube to hold up to 50 mL of solution."""

    def __init__(self, start_coor,
                 num_row=None, num_col=None,
                 spacing_row=None, spacing_col=None,
                 dip_distance=None):
        """Initialize by creating by calling super method."""
        if num_row is None:
            num_row = 1
        if num_col is None:
            num_col = 1
        if spacing_row is None:
            spacing_row = 0
        if spacing_col is None:
            spacing_col = 0
        if dip_distance is None:
            dip_distance = 75
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col,
                         dip_distance)

    def __repr__(_):
        """Representation in string form."""
        return "falcontube"


class PlateTypes:
    """A data class that holds meta-data on all the plate types."""

    # A full list of every Plate type
    TYPES = {WellPlate.__repr__(None): WellPlate,
             TipBox.__repr__(None): TipBox,
             VialHolder.__repr__(None): VialHolder,
             Garbage.__repr__(None): Garbage,
             TiltVial.__repr__(None): TiltVial,
             FalconTube.__repr__(None): FalconTube}
