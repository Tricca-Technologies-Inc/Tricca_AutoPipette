#!/usr/bin/env python3
from Coordinate import Coordinate


class VialHolder:
    def __init__(self, start_coordinate, row_count=7, column_count=5, row_spacing=18, column_spacing=18):
        self.coordinates = self._generate_vial_coordinates(start_coordinate, row_count, column_count, row_spacing, column_spacing)

    def _generate_vial_coordinates(self, start_coordinate, row_count, column_count, row_spacing, column_spacing):
        coordinates_list = []
        x_start = start_coordinate.x
        y_start = start_coordinate.y
        z_start = start_coordinate.z

        for row in range(row_count):
            for col in range(column_count):
                x = x_start - (col * column_spacing)
                y = y_start + (row * row_spacing)
                z = z_start

                # Add the well coordinates
                coordinates_list.append(Coordinate(x, y, z, 6300))

        return coordinates_list

    def get_coordinates(self):
        return self.coordinates
