#!/usr/bin/env python3
"""Holds the various plate classes."""
from __future__ import annotations
from coordinate import Coordinate
from typing import List, Optional, Type, Dict, ClassVar
from abc import ABC, abstractmethod
from well import Well
from pydantic import BaseModel, conint, confloat, validator, ConfigDict, \
                     field_validator, ValidationInfo, Field


class NotAPlateTypeError(Exception):
    """Raised when an invalid plate type is specified."""

    def __init__(self, plate) -> None:
        """Initialize error."""
        super().__init__(
            f"Invalid plate type {plate!r}. "
            f"Valid types: {PlateFactory.registered()}")


class SmartDefaultModel(BaseModel):
    """Base model that uses defaults for explicit `None` values."""

    @field_validator("*", mode="before")
    def _replace_none_with_default(cls, value, info: ValidationInfo):
        field = cls.model_fields[info.field_name]
        return value if value is not None else field.get_default()


class PlateParams(SmartDefaultModel):
    """A data validation class to hold Plate related variables.

    TODO Implement validators that set good defaults when None is set
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)


    plate_type: str
    well_template: Well
    num_row: conint(ge=1)   = Field(1, alias="row")
    num_col: conint(ge=1)   = Field(1, alias="col")
    spacing_row: confloat(ge=0) = Field(0, alias="spacing_row")
    spacing_col: confloat(ge=0) = Field(0, alias="spacing_col")

    @validator("plate_type")
    def validate_plate_type(cls, v, values):
        """Ensure the plate_type string can be mapped to a Plate type."""
        if v not in PlateFactory.registered():
            raise NotAPlateTypeError(v)
        return v


class Plate(ABC):
    """Generate and manage wells to pipette into."""

    num_row: int
    num_col: int
    spacing_row: float
    spacing_col: float
    curr: int
    wells: List[Well]

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize by creating all wells on the plate."""
        self.start_coor = plate_params.well_template.coor
        self.well_template = plate_params.well_template
        self.num_row = plate_params.num_row
        self.num_col = plate_params.num_col
        self.spacing_row = plate_params.spacing_row
        self.spacing_col = plate_params.spacing_col
        self.wells = self._gen_wells(self.start_coor,
                                     self.well_template,
                                     self.num_row,
                                     self.num_col,
                                     self.spacing_row,
                                     self.spacing_col)
        self.curr = 0

    @abstractmethod
    def _gen_wells(self,
                   start_coor: Coordinate,
                   well: Well,
                   num_row: int, num_col: int,
                   spacing_row: float, spacing_col: float) -> List[Well]:
        """Generate all the coordinates for the plate."""
        pass

    @abstractmethod
    def get_coor(self, row: int, col: int) -> Optional[Coordinate]:
        """Return a coordinate at a specific row and column.

        Zero indexed. If error, return nothing.
        """
        pass

    @abstractmethod
    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into a well."""
        pass

    @abstractmethod
    def next(self) -> Coordinate:
        """Return the next coordinate.

        Restart if the last has been returned.
        """
        pass


class PlateFactory:
    """Dedicated factory for plate creation and management."""

    _registry: ClassVar[Dict[str, Type[Plate]]] = {}

    @classmethod
    def register(cls, plate_type: str) -> callable:
        """Decorate classes for registering new plate types."""
        def decorator(subclass: Type[Plate]) -> Type[Plate]:
            if not issubclass(subclass, Plate):
                raise TypeError(f"{subclass.__name__} must subclass Plate")

            key = plate_type.strip().lower()
            if key in cls._registry:
                raise ValueError(f"Plate type '{key}' already registered")

            cls._registry[key] = subclass
            return subclass
        return decorator

    @classmethod
    def create(cls, plate_params: PlateParams) -> Plate:
        """Create a plate instance with validation."""
        key = plate_params.plate_type.strip().lower()
        if not key:
            raise ValueError("Plate type cannot be empty")
        try:
            plate_class = cls._registry[key]
        except KeyError:
            available = list(cls._registry.keys())
            raise ValueError(
                f"Invalid plate type '{key}'. Registered types: {available}"
            ) from None

        return plate_class(plate_params)

    @classmethod
    def registered(cls) -> List:
        """Return a list of the keys of the registered classes."""
        return list(cls._registry.keys())


@PlateFactory.register("array")
class PlateArray(Plate):
    """Generate and manage wells to pipette into."""

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize by creating all coordinates on the plate."""
        super().__init__(plate_params)

    def _gen_wells(self,
                   start_coor: Coordinate,
                   well: Well,
                   num_row: int, num_col: int,
                   spacing_row: float, spacing_col: float) -> List[Well]:
        """Generate all the coordinates for the plate."""
        wells = []
        x_start = start_coor.x
        y_start = start_coor.y
        z_start = start_coor.z
        for row in range(num_row):
            for col in range(num_col):
                x = x_start - (col * spacing_col)
                y = y_start + (row * spacing_row)
                z = z_start
                new_well = Well(
                    Coordinate(x=x, y=y, z=z),
                    well.dip_top,
                    well.dip_btm,
                    well.dip_func,
                    diameter=well.diameter)
                wells.append(new_well)
        return wells

    def get_coor(self, row: int, col: int) -> Optional[Coordinate]:
        """Return a coordinate at a specific row and column.

        Zero indexed. If error, return nothing.
        """
        if row >= self.num_row or row < 0:
            return
        if col >= self.num_col or col < 0:
            return
        index = col + self.num_col * row
        return self.wells[index].coor

    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into a well."""
        return self.wells[self.curr].get_dip_distance(vol)

    def next(self) -> Coordinate:
        """Return the next coordinate.

        Restart if the last has been returned.
        """
        coor = self.wells[self.curr].coor
        self.curr += 1
        if self.curr >= len(self.wells):
            self.curr = 0
        return coor


@PlateFactory.register("singleton")
class PlateSingleton(PlateArray):
    """Generate and manage coordinates to pipette into."""

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize by creating all coordinates on the plate."""
        plate_params.num_row = 1
        plate_params.num_col = 1
        plate_params.spacing_row = 0
        plate_params.spacing_col = 0
        super().__init__(plate_params)

    def next(self) -> Coordinate:
        """Return the next coordinate.

        Singleton means there is only one coordinate, so return it.
        """
        return self.wells[0].coor


@PlateFactory.register("tipbox")
class TipBox(PlateArray):
    """A plate that contains the tips used in pipetting.

    Iteration order:
      start at bottom-right, move left across the row,
      then jump one row up and repeat, until top-left.
    """

    def __init__(self, plate_params: PlateParams) -> None:
        super().__init__(plate_params)

    def _idx_for_position(self, pos: int) -> int:
        """Map logical position → physical wells index
        using bottom-right → left, then up traversal.
        Supports multiple appended boxes of the same shape.
        """
        if not self.wells:
            raise IndexError("TipBox has no wells")

        block = self.num_row * self.num_col
        box_base = (pos // block) * block          # which box (if append_box used)
        off      =  pos % block                    # offset within that box

        # Offset counted from bottom-right:
        r_from_bottom = off // self.num_col        # 0,1,2... upward
        c_from_right  = off %  self.num_col        # 0,1,2... leftward

        r = (self.num_row - 1) - r_from_bottom     # convert to top-based row
        c = (self.num_col - 1) - c_from_right      # convert to left-based col

        return box_base + (c + self.num_col * r)   # row-major index in wells[]

    def next(self) -> Coordinate:
        """Return next tip coord in bottom-right → left → up order."""
        idx = self._idx_for_position(self.curr)
        coor = self.wells[idx].coor
        self.curr += 1
        if self.curr >= len(self.wells):
            self.curr = 0
        return coor

    def get_dip_distance(self, vol: float = 0.0) -> float:
        """Match the well returned by the last next()."""
        prev_pos = (self.curr - 1) % len(self.wells)
        idx = self._idx_for_position(prev_pos)
        return self.wells[idx].get_dip_distance(vol)

    def append_box(self, tipbox: 'TipBox'):
        """Append another tip box. Assumes same num_row/num_col."""
        self.wells = self.wells + tipbox.wells


@PlateFactory.register("waste_container")
class WasteContainer(PlateSingleton):
    """A plate to hold used pipette tips and other waste."""

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize by creating by calling super method."""
        # Can never have variation in how far it dips
        super().__init__(plate_params)

    def get_dip_distance(self, vol: float = 0.0) -> float:
        """Return the distance to dip and grab a tip."""
        return super().get_dip_distance(vol)
