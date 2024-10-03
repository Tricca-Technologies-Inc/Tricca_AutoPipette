#!/usr/bin/env python3
"""Holds the various plate classes."""
from Coordinate import Coordinate


class Plate:
    """Generate and manage coordinates to pipette into."""

    def __init__(self, start_coor,
                 num_row=12, num_col=8,
                 spacing_row=9, spacing_col=9):
        """Initialize by creating all coordinates on the plate."""
        self.coors = self._gen_well_plate_coors(start_coor,
                                                num_row, num_col,
                                                spacing_row, spacing_col)
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

    def next(self):
        """Return the next coordinate.

        Restart if the last has been returned.
        """
        if (self.curr < len(self.coor)):
            coor = self.coor[self.curr]
            self.curr += 1
            return coor
        else:
            self.curr = 0
            return self.coor[self.curr]


class WellPlate(Plate):
    """A plate with various wells to pipette into."""

    def __init__(self, start_coor,
                 num_row=12, num_col=8,
                 spacing_row=9, spacing_col=9):
        """Initialize by creating all coordinates on the plate."""
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col)


class TipBox(Plate):
    """A plate that contains the tips used in pipetting."""

    def __init__(self, start_coor,
                 num_row=12, num_col=8,
                 spacing_row=9, spacing_col=9):
        """Initialize by creating all coordinates on the plate."""
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col)


class VialHolder(Plate):
    """A plate that holds vials to pipette into."""

    def __init__(self, start_coor,
                 num_row=7, num_col=5,
                 spacing_row=18, spacing_col=18):
        """Initialize by creating all coordinates on the plate."""
        super().__init__(start_coor,
                         num_row, num_col,
                         spacing_row, spacing_col)
