#!/usr/bin/env python3
"""Holds the various plate classes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, ClassVar

from coordinate import Coordinate
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)
from well import Well, StrategyType


class PlateError(Exception):
    """Base exception for plate-related errors."""

    pass


class InvalidPlateTypeError(PlateError):
    """Raised when an invalid plate type is specified."""

    def __init__(self, plate_type: str, valid_types: list[str]) -> None:
        """Initialize error with plate type and valid options.

        Args:
            plate_type: The invalid plate type that was requested.
            valid_types: List of valid registered plate types.
        """
        valid = ", ".join(valid_types)
        super().__init__(f"Invalid plate type '{plate_type}'. Valid types: {valid}")


class SmartDefaultModel(BaseModel):
    """Base model that uses defaults for explicit `None` values."""

    @field_validator("*", mode="before")
    @classmethod
    def _replace_none_with_default(cls, value: object, info: ValidationInfo) -> object:
        """Replace None values with field defaults.

        Args:
            value: The field value to validate.
            info: Pydantic validation context information.

        Returns:
            The original value if not None, otherwise the field's default value.
        """
        if value is not None:
            return value
        field = cls.model_fields[info.field_name]
        return field.get_default()


class PlateParams(SmartDefaultModel):
    """Data validation class for plate configuration.

    Attributes:
        plate_type: Type of plate to create (must be registered).
        well_template: Template well to use for creating all wells.
        num_row: Number of rows in the plate.
        num_col: Number of columns in the plate.
        spacing_row: Spacing between rows in mm.
        spacing_col: Spacing between columns in mm.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plate_type: str
    well_template: Well
    num_row: int = Field(1, ge=1)
    num_col: int = Field(1, ge=1)
    spacing_row: float | None = Field(0.0, ge=0)
    spacing_col: float | None = Field(0.0, ge=0)

    @field_validator("plate_type")
    @classmethod
    def validate_plate_type(cls, v: str) -> str:
        """Ensure plate is a valid registered type.

        Args:
            v: The plate type string to validate.

        Returns:
            Normalized (lowercase, stripped) plate type string.

        Raises:
            ValueError: If plate type is not registered.
        """
        normalized = v.strip().lower()
        if normalized not in PlateFactory.registered():
            raise ValueError(
                f"Invalid plate type '{v}'. "
                f"Valid types: {', '.join(PlateFactory.registered())}"
            )
        return normalized


class Plate(ABC):
    """Base class for plate types that manage wells for pipetting.

    Attributes:
        start_coor: Starting coordinate for the first well.
        well_template: Template well used to create all wells.
        num_row: Number of rows in the plate.
        num_col: Number of columns in the plate.
        spacing_row: Spacing between rows in mm.
        spacing_col: Spacing between columns in mm.
        curr: Current well index for iteration.
        wells: List of all wells in the plate.
    """

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize plate by creating all wells.

        Args:
            plate_params: Validated plate configuration parameters.
        """
        self.start_coor = plate_params.well_template.coor
        self.well_template = plate_params.well_template
        self.num_row = plate_params.num_row
        self.num_col = plate_params.num_col
        self.spacing_row = plate_params.spacing_row
        self.spacing_col = plate_params.spacing_col
        self.curr = 0

        self.wells = self._gen_wells(
            self.start_coor,
            self.well_template,
            self.num_row,
            self.num_col,
            self.spacing_row,
            self.spacing_col,
        )

    @abstractmethod
    def _gen_wells(
        self,
        start_coor: Coordinate,
        well_template: Well,
        num_row: int,
        num_col: int,
        spacing_row: float,
        spacing_col: float,
    ) -> list[Well]:
        """Generate all the wells for the plate.

        Args:
            start_coor: Starting coordinate for the first well.
            well_template: Template well to copy for each position.
            num_row: Number of rows to generate.
            num_col: Number of columns to generate.
            spacing_row: Spacing between rows in mm.
            spacing_col: Spacing between columns in mm.

        Returns:
            List of Well objects positioned according to plate layout.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement _gen_wells")

    @abstractmethod
    def get_coor(self, row: int, col: int) -> Coordinate | None:
        """Return coordinate at specific row and column.

        Args:
            row: Zero-indexed row number.
            col: Zero-indexed column number.

        Returns:
            Coordinate at the specified position, or None if out of bounds.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_coor")

    @abstractmethod
    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into current well.

        Args:
            vol: Volume of liquid being aspirated/dispensed in microliters.

        Returns:
            Dip distance in mm from the top of the well.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_dip_distance")

    @abstractmethod
    def next(self) -> Coordinate:
        """Return the next coordinate, wrapping to start if at end.

        Returns:
            Coordinate of the next well in the iteration sequence.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement next")

    @property
    def total_wells(self) -> int:
        """Return the total number of wells.

        Returns:
            Total count of wells in the plate.
        """
        return len(self.wells)

    def reset(self) -> None:
        """Reset the current well index to the beginning."""
        self.curr = 0


class PlateFactory:
    """Factory for creating and managing plate types.

    This factory uses a registry pattern to allow dynamic registration
    of plate types and creation of plate instances.

    Attributes:
        _registry: Class-level registry mapping plate type names to classes.
    """

    _registry: ClassVar[dict[str, type[Plate]]] = {}

    @classmethod
    def register(cls, plate_type: str) -> Callable[[type[Plate]], type[Plate]]:
        """Decorator to register new plate types.

        Args:
            plate_type: The name to register the plate type under.

        Returns:
            Decorator function that registers the plate class.

        Raises:
            TypeError: If decorated class doesn't subclass Plate.
            ValueError: If plate type is already registered.

        Example:
            >>> @PlateFactory.register("custom")
            >>> class CustomPlate(Plate):
            ...     pass
        """

        def decorator(subclass: type[Plate]) -> type[Plate]:
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
        """Create a plate instance from validated parameters.

        Args:
            plate_params: Validated plate configuration.

        Returns:
            Instance of the requested plate type.

        Raises:
            ValueError: If plate type is invalid or empty.
            InvalidPlateTypeError: If plate type is not registered.
        """
        key = plate_params.plate_type.strip().lower()
        if not key:
            raise ValueError("Plate type cannot be empty")

        plate_class = cls._registry.get(key)
        if plate_class is None:
            raise InvalidPlateTypeError(key, cls.registered())

        return plate_class(plate_params)

    @classmethod
    def registered(cls) -> list[str]:
        """Return list of registered plate type names.

        Returns:
            Sorted list of registered plate type names.
        """
        return sorted(cls._registry.keys())


@PlateFactory.register("array")
class PlateArray(Plate):
    """Standard rectangular array of wells.

    Wells are arranged in a grid pattern with configurable spacing.
    Coordinates are calculated from a starting position with wells
    arranged left-to-right, top-to-bottom.
    """

    def _gen_wells(
        self,
        start_coor: Coordinate,
        well_template: Well,
        num_row: int,
        num_col: int,
        spacing_row: float,
        spacing_col: float,
    ) -> list[Well]:
        """Generate wells in a rectangular grid pattern.

        Args:
            start_coor: Starting coordinate for the first well.
            well_template: Template well to copy for each position.
            num_row: Number of rows to generate.
            num_col: Number of columns to generate.
            spacing_row: Spacing between rows in mm.
            spacing_col: Spacing between columns in mm.

        Returns:
            List of Well objects positioned in a rectangular grid.
        """
        wells = []

        for row in range(num_row):
            for col in range(num_col):
                x = start_coor.x - (col * spacing_col)
                y = start_coor.y + (row * spacing_row)
                z = start_coor.z

                new_well = Well(
                    coor=Coordinate(x=x, y=y, z=z),
                    dip_top=well_template.dip_top,
                    dip_btm=well_template.dip_btm,
                    strategy_type=well_template.strategy_name,
                    well_diameter=well_template.well_diameter,
                )
                wells.append(new_well)

        return wells

    def get_coor(self, row: int, col: int) -> Coordinate | None:
        """Return coordinate at specific row and column.

        Args:
            row: Zero-indexed row number.
            col: Zero-indexed column number.

        Returns:
            Coordinate at the specified position, or None if out of bounds.
        """
        if not (0 <= row < self.num_row and 0 <= col < self.num_col):
            return None

        index = col + self.num_col * row
        return self.wells[index].coor

    def get_dip_distance(self, vol: float) -> float:
        """Return the distance needed to dip into current well.

        Args:
            vol: Volume of liquid being aspirated/dispensed in microliters.

        Returns:
            Dip distance in mm from the top of the well.
        """
        return self.wells[self.curr].get_dip_distance(vol)

    def next(self) -> Coordinate:
        """Return the next coordinate, wrapping to start if at end.

        Returns:
            Coordinate of the next well in row-major order.
        """
        coor = self.wells[self.curr].coor
        self.curr = (self.curr + 1) % len(self.wells)
        return coor


@PlateFactory.register("singleton")
class PlateSingleton(PlateArray):
    """Single-well plate that always returns the same coordinate.

    This plate type is useful for representing containers with a single
    access point, such as reagent bottles or bulk containers.
    """

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize with forced single well configuration.

        Args:
            plate_params: Plate configuration (dimensions will be overridden).
        """
        # Override parameters to enforce singleton behavior
        plate_params.num_row = 1
        plate_params.num_col = 1
        plate_params.spacing_row = 0.0
        plate_params.spacing_col = 0.0
        super().__init__(plate_params)

    def next(self) -> Coordinate:
        """Return the single coordinate without incrementing.

        Returns:
            Always returns the same coordinate (the only well).
        """
        return self.wells[0].coor


@PlateFactory.register("tipbox")
class TipBox(PlateArray):
    """Plate containing disposable pipette tips.

    TipBoxes can be combined to create larger tip supplies by
    appending multiple boxes together.
    """

    def append_box(self, tipbox: TipBox) -> None:
        """Append wells from another TipBox to this one.

        This allows multiple tip boxes to be treated as a single
        continuous supply of tips.

        Args:
            tipbox: Another TipBox instance to merge with this one.
        """
        self.wells.extend(tipbox.wells)

    # get_dip_distance inherited from PlateArray - no override needed


@PlateFactory.register("waste_container")
class WasteContainer(PlateSingleton):
    """Single location for disposing used tips and waste.

    A waste container has a single disposal point and doesn't track
    volume or liquid levels.
    """

    # get_dip_distance inherited from PlateArray - no override needed
