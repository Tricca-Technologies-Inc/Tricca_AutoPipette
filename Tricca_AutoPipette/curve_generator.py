#!/usr/bin/env python3
"""Holds classes that generate curves for the pipette toolhead."""
from pathlib import Path
import math
import argparse

PROTOCOL_PATH = Path(__file__).parent.parent / 'protocols/'


class Curve_Sphere:
    """Generate a curve that makes a sphere."""

    coordinates = []
    move_buf = ""

    def __init__(self,
                 x_cons=None, y_cons=None, z_cons=None,
                 radius=None, res=None):
        """Generate a curve."""
        if x_cons is None:
            self.x_cons = 150
        if y_cons is None:
            self.y_cons = 150
        if z_cons is None:
            self.z_cons = 20
        if radius is None:
            self.radius = [150, 150, 20]
        if res is None:
            self.res = 200
        delta_angle = math.pi / self.res
        delta_angle2 = 2 * math.pi / self.res
        for delta_num in range(0, self.res, 1):
            angle = delta_num * delta_angle
            angle2 = delta_num * delta_angle2
            self.coordinates.append(self.equation(angle, angle2))

    def equation(self, angle, angle2):
        """Parameterized equation."""
        x = self.x_cons + self.radius[0] * math.sin(angle) * math.cos(angle2)
        y = self.y_cons + self.radius[1] * math.sin(angle) * math.sin(angle2)
        z = self.z_cons + self.radius[2] * math.cos(angle)
        x = round(x, 3)
        y = round(y, 3)
        z = round(z, 3)
        return (x, y, z)

    def to_pipette_move(self):
        """Convert coordinates into pipette move commands."""
        for coor in self.coordinates:
            x, y, z = coor
            self.move_buf += f"move {x} {y} {z}\n"
        temp = self.move_buf
        self.move_buf = ""
        return temp


if __name__ == "__main__":
    # Setup parser and get args
    parser = argparse.ArgumentParser(
        description="Append a curve to an existing .pipette file.")
    parser.add_argument("protocol",
                        help="the name of the protocol in ../protocols")
    args = parser.parse_args()
    prot_name = args.protocol + ".pipette"
    prot_file = PROTOCOL_PATH / prot_name
    with prot_file.open('w') as prot_fobj:
        prot_fobj.write(Curve_Sphere().to_pipette_move())
