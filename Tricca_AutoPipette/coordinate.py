"""Holds classes related to pipette positioning."""
from __future__ import annotations
from pydantic import BaseModel, confloat, Field


class Coordinate(BaseModel):
    """Associate 3 numbers with a place on the pipette bed."""

    x: confloat(ge=0) = Field(..., description="Postion in the X-axis")
    y: confloat(ge=0) = Field(..., description="Postion in the Y-axis")
    z: confloat(ge=0) = Field(..., description="Postion in the Z-axis")

    def __repr__(self):
        """Representation in string format."""
        return f"Coordinate(x={self.x}, y={self.y}, z={self.z})"

    def generate_offset(self, dx: float, dy: float, dz: float) -> Coordinate:
        """Generate a coordinate that is offset in the passed in direction."""
        return Coordinate(
            x=self.x + dx,
            y=self.y + dy,
            z=self.z + dz
        )

