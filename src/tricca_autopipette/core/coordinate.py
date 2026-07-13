"""Holds classes related to pipette positioning."""

from __future__ import annotations

import math
from typing import Self

from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    """Represent a 3D position on the pipette bed.

    Coordinates use a Cartesian system where all values must be non-negative,
    representing physical positions on the pipette apparatus.

    Attributes:
        x: Position along the X-axis in millimeters.
        y: Position along the Y-axis in millimeters.
        z: Position along the Z-axis in millimeters (height).
    """

    model_config = {
        "frozen": False,
        "validate_assignment": True,
    }

    x: float = Field(
        ...,
        ge=0,
        description="Position along the X-axis in millimeters",
    )
    y: float = Field(
        ...,
        ge=0,
        description="Position along the Y-axis in millimeters",
    )
    z: float = Field(
        ...,
        ge=0,
        description="Position along the Z-axis (height) in millimeters",
    )

    def __repr__(self) -> str:
        """Return string representation of the coordinate.

        Returns:
            String in format "Coordinate(x=..., y=..., z=...)".
        """
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z})"

    def __str__(self) -> str:
        """Return human-readable string representation.

        Returns:
            Formatted string showing position values.
        """
        return f"({self.x:.2f}, {self.y:.2f}, {self.z:.2f})"

    def __eq__(self, other: object) -> bool:
        """Check equality with another coordinate.

        Args:
            other: Object to compare with.

        Returns:
            True if coordinates are equal, False otherwise.

        Example:
            >>> coord1 = Coordinate(x=1.0, y=2.0, z=3.0)
            >>> coord2 = Coordinate(x=1.0, y=2.0, z=3.0)
            >>> coord1 == coord2
            True
        """
        if not isinstance(other, Coordinate):
            return NotImplemented
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __hash__(self) -> int:
        """Return hash of the coordinate.

        Returns:
            Hash value based on x, y, z coordinates.
        """
        return hash((self.x, self.y, self.z))

    def generate_offset(
        self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0
    ) -> Self:
        """Generate a new coordinate offset from this position.

        Creates a new Coordinate instance by applying the specified offsets
        to the current position. The original coordinate is not modified.

        Args:
        dx: Offset along the X-axis in millimeters (default: 0.0).
        dy: Offset along the Y-axis in millimeters (default: 0.0).
        dz: Offset along the Z-axis in millimeters (default: 0.0).

        Returns:
        New Coordinate instance at the offset position.

        Raises:
        ValueError: If the resulting coordinate has negative values.

        Example:
        >>> coord = Coordinate(x=10.0, y=20.0, z=5.0)
        >>> new_coord = coord.generate_offset(dx=5.0, dz=2.0)
        >>> print(new_coord)
        (15.00, 20.00, 7.00)
        """
        new_x = self.x + dx
        new_y = self.y + dy
        new_z = self.z + dz

        if new_x < 0 or new_y < 0 or new_z < 0:
            raise ValueError(
                f"Resulting coordinate ({new_x}, {new_y}, {new_z}) "
                "has negative values"
            )

        return self.__class__(x=new_x, y=new_y, z=new_z)

    def distance_to(self, other: Coordinate) -> float:
        """Calculate Euclidean distance to another coordinate.

        Args:
            other: The target coordinate to measure distance to.

        Returns:
            Euclidean distance in millimeters.

        Example:
            >>> coord1 = Coordinate(x=0.0, y=0.0, z=0.0)
            >>> coord2 = Coordinate(x=3.0, y=4.0, z=0.0)
            >>> coord1.distance_to(coord2)
            5.0
        """
        return math.sqrt(
            (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2
        )

    def distance_xy(self, other: Coordinate) -> float:
        """Calculate horizontal (XY plane) distance to another coordinate.

        Useful for determining travel distance while ignoring height differences.

        Args:
            other: The target coordinate to measure distance to.

        Returns:
            Horizontal distance in millimeters.

        Example:
            >>> coord1 = Coordinate(x=0.0, y=0.0, z=10.0)
            >>> coord2 = Coordinate(x=3.0, y=4.0, z=20.0)
            >>> coord1.distance_xy(coord2)
            5.0
        """
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def is_above(self, other: Coordinate, tolerance: float = 0.01) -> bool:
        """Check if this coordinate is above another coordinate.

        Compares only the Z-axis positions with optional tolerance for
        floating-point comparisons.

        Args:
            other: The coordinate to compare against.
            tolerance: Tolerance for floating-point comparison in millimeters.

        Returns:
            True if this coordinate is above the other, False otherwise.

        Example:
            >>> coord1 = Coordinate(x=10.0, y=10.0, z=15.0)
            >>> coord2 = Coordinate(x=10.0, y=10.0, z=10.0)
            >>> coord1.is_above(coord2)
            True
        """
        return self.z > other.z + tolerance

    def is_below(self, other: Coordinate, tolerance: float = 0.01) -> bool:
        """Check if this coordinate is below another coordinate.

        Compares only the Z-axis positions with optional tolerance for
        floating-point comparisons.

        Args:
            other: The coordinate to compare against.
            tolerance: Tolerance for floating-point comparison in millimeters.

        Returns:
            True if this coordinate is below the other, False otherwise.

        Example:
            >>> coord1 = Coordinate(x=10.0, y=10.0, z=10.0)
            >>> coord2 = Coordinate(x=10.0, y=10.0, z=15.0)
            >>> coord1.is_below(coord2)
            True
        """
        return self.z < other.z - tolerance

    def is_within_bounds(self, min_coord: Coordinate, max_coord: Coordinate) -> bool:
        """Check if coordinate is within specified bounds.

        Args:
            min_coord: Minimum boundary coordinate (inclusive).
            max_coord: Maximum boundary coordinate (inclusive).

        Returns:
            True if coordinate is within bounds, False otherwise.

        Example:
            >>> coord = Coordinate(x=5.0, y=5.0, z=5.0)
            >>> min_bound = Coordinate(x=0.0, y=0.0, z=0.0)
            >>> max_bound = Coordinate(x=10.0, y=10.0, z=10.0)
            >>> coord.is_within_bounds(min_bound, max_bound)
            True
        """
        return (
            min_coord.x <= self.x <= max_coord.x
            and min_coord.y <= self.y <= max_coord.y
            and min_coord.z <= self.z <= max_coord.z
        )

    def clamp(self, min_coord: Coordinate, max_coord: Coordinate) -> Self:
        """Clamp coordinate values to specified bounds.

        Args:
            min_coord: Minimum boundary coordinate.
            max_coord: Maximum boundary coordinate.

        Returns:
            New Coordinate with values clamped to bounds.

        Example:
            >>> coord = Coordinate(x=15.0, y=5.0, z=-5.0)
            >>> min_bound = Coordinate(x=0.0, y=0.0, z=0.0)
            >>> max_bound = Coordinate(x=10.0, y=10.0, z=10.0)
            >>> clamped = coord.clamp(min_bound, max_bound)
            >>> print(clamped)
            (10.00, 5.00, 0.00)
        """
        return self.__class__(
            x=max(min_coord.x, min(self.x, max_coord.x)),
            y=max(min_coord.y, min(self.y, max_coord.y)),
            z=max(min_coord.z, min(self.z, max_coord.z)),
        )

    @classmethod
    def origin(cls) -> Self:
        """Create a coordinate at the origin (0, 0, 0).

        Returns:
            Coordinate instance at position (0, 0, 0).

        Example:
            >>> origin = Coordinate.origin()
            >>> print(origin)
            (0.00, 0.00, 0.00)
        """
        return cls(x=0.0, y=0.0, z=0.0)

    def to_tuple(self) -> tuple[float, float, float]:
        """Convert coordinate to tuple format.

        Returns:
            Tuple of (x, y, z) values.

        Example:
            >>> coord = Coordinate(x=1.0, y=2.0, z=3.0)
            >>> coord.to_tuple()
            (1.0, 2.0, 3.0)
        """
        return (self.x, self.y, self.z)

    @classmethod
    def from_tuple(cls, values: tuple[float, float, float]) -> Self:
        """Create coordinate from tuple format.

        Args:
        values: Tuple of exactly (x, y, z) values.

        Returns:
        New Coordinate instance.

        Example:
        >>> coord = Coordinate.from_tuple((1.0, 2.0, 3.0))
        >>> print(coord)
        (1.00, 2.00, 3.00)
        """
        return cls(x=values[0], y=values[1], z=values[2])
