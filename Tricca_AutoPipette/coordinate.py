"""Holds classes related to pipette positioning."""

from __future__ import annotations

from pydantic import BaseModel, Field, confloat


class Coordinate(BaseModel):
    """Associate 3 numbers with a place on the pipette bed."""

    x: confloat(ge=0) = Field(..., description="Postion in the X-axis")
    y: confloat(ge=0) = Field(..., description="Postion in the Y-axis")
    z: confloat(ge=0) = Field(..., description="Postion in the Z-axis")

    def __repr__(self) -> str:
        """Representation in string format.

        Returns:
        A fomatted string containing coordinate information.
        """
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z})"

    def generate_offset(self, dx: float, dy: float, dz: float) -> Coordinate:
        """Generate a coordinate that is offset in the passed in direction.

        Returns:
        A Coordinate object with the specified offset.
        """
        return Coordinate(x=self.x + dx, y=self.y + dy, z=self.z + dz)
