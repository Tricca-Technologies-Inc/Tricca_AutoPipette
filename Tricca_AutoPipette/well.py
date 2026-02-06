#!/usr/bin/env python3
"""Holds the Well class and the related DipStrategies."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from coordinate import Coordinate


class DipStrategy(ABC):
    """Base class for dip strategies."""

    @abstractmethod
    def calculate_dip_distance(self, well: Well, volume: float) -> float:
        """Calculate the dip distance for the given well and volume."""
        raise NotImplementedError("Subclasses must implement calculate_dip_distance")

    @abstractmethod
    def validate_well_config(
        self, well_diameter: float | None, dip_btm: float | None
    ) -> None:
        """Validate that the well configuration supports this strategy."""
        raise NotImplementedError("Subclasses must implement validate_well_config")


class SimpleDipStrategy(DipStrategy):
    """Return the dip distance without modification."""

    def calculate_dip_distance(self, well: Well, volume: float) -> float:
        """Find how far to move down."""
        return well.dip_top

    def validate_well_config(
        self, well_diameter: float | None, dip_btm: float | None
    ) -> None:
        """Validate that the well configuration supports this strategy."""
        pass  # No validation needed for simple strategy


class CylinderDipStrategy(DipStrategy):
    """Calculate dip distance for a cylindrical well based on volume."""

    MM_TO_M = 1000
    LITERS_TO_CUBIC_M = 1e-9

    def calculate_dip_distance(self, well: Well, volume: float) -> float:
        """Calculate the dip distance accounting for liquid volume removed."""
        if well.dip_btm is None or well.well_diameter is None:
            raise ValueError("Cylinder strategy requires well_diameter and dip_btm")

        radius_m = well.well_diameter / (2 * self.MM_TO_M)
        height_change_m = (volume * self.LITERS_TO_CUBIC_M) / (math.pi * radius_m**2)
        height_change_mm = height_change_m * self.MM_TO_M

        well.dip_curr += height_change_mm
        well.dip_curr = min(well.dip_curr, well.dip_btm)

        return well.dip_curr

    def validate_well_config(
        self, well_diameter: float | None, dip_btm: float | None
    ) -> None:
        """Validate that the well configuration supports this strategy."""
        if well_diameter is None:
            raise ValueError("Cylinder strategy requires well_diameter")
        if dip_btm is None:
            raise ValueError("Cylinder strategy requires dip_btm")


class StrategyType(str, Enum):
    """Available dip strategy types."""

    SIMPLE = "simple"
    CYLINDER = "cylinder"


class StrategyRegistry:
    """Registry for mapping strategy names to implementations."""

    _strategies: dict[StrategyType, DipStrategy] = {
        StrategyType.SIMPLE: SimpleDipStrategy(),
        StrategyType.CYLINDER: CylinderDipStrategy(),
    }

    @classmethod
    def get_strategy(cls, strategy_type: StrategyType) -> DipStrategy:
        """Get a strategy instance by type."""
        return cls._strategies[strategy_type]

    @classmethod
    def get_strategy_name(cls, strategy: DipStrategy) -> StrategyType:
        """Get the name of a strategy instance."""
        for name, strat in cls._strategies.items():
            if isinstance(strategy, type(strat)):
                return name
        raise ValueError(f"Unknown strategy: {type(strategy).__name__}")


class WellParams(BaseModel):
    """A data validation class to hold Well related variables."""

    coor: Coordinate
    dip_top: float = Field(..., gt=0)
    dip_btm: float | None = Field(None, gt=0)
    strategy_type: StrategyType = StrategyType.SIMPLE
    well_diameter: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_strategy_requirements(self) -> "WellParams":
        """Validate that the well configuration matches strategy requirements."""
        strategy = StrategyRegistry.get_strategy(self.strategy_type)
        strategy.validate_well_config(self.well_diameter, self.dip_btm)
        return self


class Well:
    """A vessel to hold chemicals."""

    def __init__(
        self,
        coor: Coordinate,
        dip_top: float,
        dip_btm: float | None = None,
        strategy_type: StrategyType = StrategyType.SIMPLE,
        well_diameter: float | None = None,
    ) -> None:
        """Initialize a well with the specified dip strategy."""
        self.coor = coor
        self.dip_top = dip_top
        self.dip_btm = dip_btm
        self.dip_curr = dip_top
        self.well_diameter = well_diameter

        self._strategy = StrategyRegistry.get_strategy(strategy_type)
        self._strategy.validate_well_config(well_diameter, dip_btm)

    def get_dip_distance(self, volume: float) -> float:
        """Return the distance needed to dip into a well for the given volume."""
        return self._strategy.calculate_dip_distance(self, volume)

    @property
    def strategy_name(self) -> StrategyType:
        """Get the name of the current strategy."""
        return StrategyRegistry.get_strategy_name(self._strategy)


WellParams.model_rebuild()
