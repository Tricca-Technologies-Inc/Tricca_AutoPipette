"""Holds classes related to pipette positioning."""

from __future__ import annotations

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

    def generate_offset(
        self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0
    ) -> Coordinate:
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
        return Coordinate(x=self.x + dx, y=self.y + dy, z=self.z + dz)

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
        return (
            (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2
        ) ** 0.5

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
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5

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

    def copy(self) -> Coordinate:
        """Create a deep copy of this coordinate.

        Returns:
            New Coordinate instance with the same position values.

        Example:
            >>> original = Coordinate(x=10.0, y=20.0, z=5.0)
            >>> duplicate = original.copy()
            >>> duplicate.x = 15.0
            >>> original.x
            10.0
        """
        return Coordinate(x=self.x, y=self.y, z=self.z)

    @classmethod
    def origin(cls) -> Coordinate:
        """Create a coordinate at the origin (0, 0, 0).

        Returns:
            Coordinate instance at position (0, 0, 0).

        Example:
            >>> origin = Coordinate.origin()
            >>> print(origin)
            (0.00, 0.00, 0.00)
        """
        return cls(x=0.0, y=0.0, z=0.0)
