#!/usr/bin/env python3
from Coordinate import Coordinate


class TipBox:
    def __init__(self, start_coordinate, row_count=12, col_count=8, row_spacing=9, col_spacing=9):
        self.coordinates = self._generate_tip_coordinates(start_coordinate, row_count, col_count, row_spacing, col_spacing)
        self.current_tip = 0

    def _generate_tip_coordinates(self, start_coordinate, row_count, col_count, row_spacing, col_spacing):
        coordinates_list = []
        x_start = start_coordinate.x
        y_start = start_coordinate.y
        z_start = start_coordinate.z

        for row in range(row_count):
            for col in range(col_count):
                x = x_start - (col * col_spacing)
                y = y_start + (row * row_spacing)
                z = z_start

                # Add the tip coordinates
                coordinates_list.append(Coordinate(x, y, z, start_coordinate.speed))

        return coordinates_list

    def next_tip(self):
        if self.current_tip < len(self.coordinates):
            tip_coordinate = self.coordinates[self.current_tip]
            self.current_tip += 1
            return tip_coordinate

        elif self.current_tip == len(self.coordinates):
            self.reset()

        else:
            self.reset()
            raise ValueError("No more tips available")

    def reset(self):
        """Reset the tip box to start picking tips from the beginning."""
        self.current_tip = 0
