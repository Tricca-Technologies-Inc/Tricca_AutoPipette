"""Holds classes related to pipette positioning."""


class Coordinate:
    """Associate 3 numbers with a place on the pipette bed."""

    def __init__(self, x: float, y: float, z: float):
        """Initialize coordinate object."""
        self.x = x
        self.y = y
        self.z = z
        # TODO Find a way to completely isolate dip_distance to a plate
        # TODO Raise error if pipetting to/from a location, not a plate
        self.dip_distance = 0

    def __repr__(self):
        """Representation in string format."""
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z})"
