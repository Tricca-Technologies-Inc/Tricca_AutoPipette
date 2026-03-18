#!/usr/bin/env python3
"""Well + dip-strategy system (strategies, registry, and validated config).

This module bundles the core pieces needed to compute pipette tip immersion
("dip") depth for a well:

- Strategy interface and implementations for computing dip distance as a
  function of well geometry and handled volume.
- A registry/enumeration for selecting strategies by name.
- A Pydantic configuration model (`WellParams`) that validates well geometry
  and strategy requirements.
- A runtime `Well` object that tracks current dip depth and delegates dip
  calculations to its configured strategy.

Core behavior:

- `DipStrategy` defines the interface:
  - `calculate_dip_distance(well, volume)` returns a dip distance (mm) and may
    update well state.
  - `validate_well_config(well_diameter, dip_btm)` enforces required geometry
    for a strategy.
- `SimpleDipStrategy` returns `well.dip_top` unchanged (no volume tracking).
- `CylinderDipStrategy` assumes a cylindrical well and converts a volume change
  (µL) into a liquid-height change using the well diameter, updating
  `well.dip_curr` and clamping it to `well.dip_btm`.
- `StrategyType` enumerates supported strategies and `StrategyRegistry` provides
  singleton instances and reverse lookup.
- `WellParams` validates that the chosen strategy has the required parameters
  (e.g., CYLINDER requires both `well_diameter` and `dip_btm`).
- `Well` stores geometry and dip state (`dip_curr`) and exposes
  `get_dip_distance(volume)` for use by pipetting operations.

Units:
    - Distances are in millimeters (mm).
    - Volumes are in microliters (µL).

Notes:
    - Some strategies (notably `CylinderDipStrategy`) mutate `Well.dip_curr`
      as a side effect; callers should treat `dip_curr` as stateful.
    - `WellParams.model_rebuild()` is called at module import time to ensure
      any forward references in type hints are resolved.

Typical usage:
    >>> params = WellParams(
    ...     coor=Coordinate(x=10, y=20, z=5),
    ...     dip_top=10.0,
    ...     dip_btm=50.0,
    ...     strategy_type=StrategyType.CYLINDER,
    ...     well_diameter=8.0,
    ... )
    >>> well = Well(**params.model_dump())
    >>> dip_mm = well.get_dip_distance(volume=100.0)
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from enum import Enum

from coordinate import Coordinate
from pydantic import BaseModel, Field, model_validator


class DipStrategy(ABC):
    """Base class for dip strategies.

    Dip strategies determine how deep a pipette tip should descend into a well
    based on the well's geometry and the volume of liquid being handled. Different
    strategies account for factors like liquid level changes and well shape.

    All subclasses must implement calculate_dip_distance and validate_well_config
    to define their specific behavior.
    """

    @abstractmethod
    def calculate_dip_distance(self, well: Well, volume: float) -> float:
        """Calculate the dip distance for the given well and volume.

        Determines how far the pipette tip should descend into the well from
        the top reference point, potentially accounting for liquid volume and
        well geometry.

        Args:
            well: The well to calculate dip distance for.
            volume: Volume of liquid being aspirated/dispensed in microliters.

        Returns:
            Distance to dip from the top reference point in millimeters.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement calculate_dip_distance")

    @abstractmethod
    def validate_well_config(
        self, well_diameter: float | None, dip_btm: float | None
    ) -> None:
        """Validate that the well configuration supports this strategy.

        Checks whether the well has the required configuration parameters
        (diameter, bottom distance) needed for this strategy to function
        correctly.

        Args:
            well_diameter: Diameter of the well in millimeters, or None.
            dip_btm: Distance from top to bottom of well in millimeters, or None.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
            ValueError: If well configuration is invalid for this strategy
                (raised by subclass implementations).
        """
        raise NotImplementedError("Subclasses must implement validate_well_config")


class SimpleDipStrategy(DipStrategy):
    """Return the dip distance without modification."""

    def calculate_dip_distance(
        self,
        well: Well,
        volume: float,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> float:
        """Calculate the dip distance for the given well and volume.

        Returns the distance to dip into the well from the top reference point.
        For the simple strategy, this always returns the initial dip distance
        without accounting for volume changes.

        Args:
            well: The well to calculate dip distance for.
            volume: Volume of liquid being aspirated/dispensed in microliters
                (unused in simple strategy).

        Returns:
            Distance to dip from the top reference point in millimeters.

        Example:
            >>> strategy = SimpleDipStrategy()
            >>> well = Well(coor=coord, dip_top=10.0, dip_btm=50.0)
            >>> distance = strategy.calculate_dip_distance(well, 100.0)
            >>> distance
            10.0
        """
        _ = volume
        return well.dip_top

    def validate_well_config(
        self, well_diameter: float | None, dip_btm: float | None
    ) -> None:
        """Validate that the well configuration supports this strategy."""
        _ = well_diameter
        _ = dip_btm
        pass  # No validation needed for simple strategy


class CylinderDipStrategy(DipStrategy):
    """Calculate dip distance for a cylindrical well based on volume.

    This strategy accounts for changes in liquid level as volume is removed
    from a cylindrical well. It calculates the height change based on the
    well's diameter and updates the dip distance accordingly.

    The strategy assumes:
    - The well has a constant circular cross-section (cylinder)
    - Liquid surface remains level during aspiration/dispensing
    - Volume changes directly affect liquid height

    Attributes:
        MM_TO_M: Conversion factor from millimeters to meters (1000).
        LITERS_TO_CUBIC_M: Conversion factor from microliters to cubic meters (1e-9).
    """

    MM_TO_M = 1000
    LITERS_TO_CUBIC_M = 1e-9

    def calculate_dip_distance(self, well: Well, volume: float) -> float:
        """Calculate the dip distance accounting for liquid volume removed.

        Computes how the liquid level changes when a given volume is removed
        from a cylindrical well, then updates and returns the new dip distance.
        The well's current dip distance is modified in place.

        Args:
            well: The cylindrical well to calculate dip distance for.
                Must have well_diameter and dip_btm defined.
            volume: Volume of liquid aspirated/dispensed in microliters.

        Returns:
            Updated dip distance in millimeters, clamped to dip_btm.

        Raises:
            ValueError: If well.well_diameter or well.dip_btm is None.

        Note:
            This method modifies well.dip_curr in place as a side effect.

        Example:
            >>> strategy = CylinderDipStrategy()
            >>> well = Well(coor=coord, dip_top=10.0, dip_btm=50.0,
            ...             well_diameter=8.0)
            >>> well.dip_curr = 10.0
            >>> distance = strategy.calculate_dip_distance(well, 100.0)
            >>> well.dip_curr  # Updated based on volume removed
            12.0
        """
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
        """Validate that the well configuration supports this strategy.

        Ensures the well has both diameter and bottom distance defined,
        which are required for cylindrical volume calculations.

        Args:
            well_diameter: Diameter of the well in millimeters, or None.
            dip_btm: Distance from top to bottom of well in millimeters, or None.

        Raises:
            ValueError: If well_diameter is None.
            ValueError: If dip_btm is None.

        Example:
            >>> strategy = CylinderDipStrategy()
            >>> strategy.validate_well_config(8.0, 50.0)  # Valid
            >>> strategy.validate_well_config(None, 50.0)  # Raises ValueError
        """
        if well_diameter is None:
            raise ValueError("Cylinder strategy requires well_diameter")
        if dip_btm is None:
            raise ValueError("Cylinder strategy requires dip_btm")


class StrategyType(str, Enum):
    """Available dip strategy types.

    Enumeration of supported strategies for calculating pipette dip distances.
    Each value corresponds to a registered DipStrategy implementation.

    Attributes:
        SIMPLE: Always returns the initial dip distance without adjustments.
        CYLINDER: Adjusts dip distance based on liquid volume in cylindrical wells.
    """

    SIMPLE = "simple"
    CYLINDER = "cylinder"


class StrategyRegistry:
    """Registry for mapping strategy names to implementations.

    Provides centralized management of dip strategy instances using the
    registry pattern. Strategies are pre-instantiated and reused across
    all wells using the same strategy type.

    This class should not be instantiated; all methods are class methods.

    Class Attributes:
        _strategies: Dictionary mapping StrategyType enums to strategy instances.
    """

    _strategies: dict[StrategyType, DipStrategy] = {
        StrategyType.SIMPLE: SimpleDipStrategy(),
        StrategyType.CYLINDER: CylinderDipStrategy(),
    }

    @classmethod
    def get_strategy(cls, strategy_type: StrategyType) -> DipStrategy:
        """Get a strategy instance by type.

        Retrieves the singleton instance of the requested strategy type
        from the registry.

        Args:
            strategy_type: The type of strategy to retrieve.

        Returns:
            The strategy instance corresponding to the given type.

        Note:
            All StrategyType enum values are guaranteed to be in the registry.

        Example:
            >>> strategy = StrategyRegistry.get_strategy(StrategyType.CYLINDER)
            >>> isinstance(strategy, CylinderDipStrategy)
            True
        """
        return cls._strategies[strategy_type]

    @classmethod
    def get_strategy_type(cls, strategy: DipStrategy) -> StrategyType:
        """Get the type of a strategy instance.

        Performs reverse lookup to find the StrategyType enum corresponding
        to a given strategy instance by comparing instance types.

        Args:
            strategy: The strategy instance to look up.

        Returns:
            The StrategyType enum for the given strategy.

        Raises:
            ValueError: If the strategy type is not registered.

        Example:
            >>> strategy = CylinderDipStrategy()
            >>> name = StrategyRegistry.get_strategy_name(strategy)
            >>> name
            <StrategyType.CYLINDER: 'cylinder'>
        """
        for name, strat in cls._strategies.items():
            if isinstance(strategy, type(strat)):
                return name
        raise ValueError(f"Unknown strategy: {type(strategy).__name__}")


class WellParams(BaseModel):
    """Data validation class for well configuration parameters.

    Validates and holds all configuration parameters needed to create a Well
    instance, including position, dip distances, strategy type, and geometry.
    Ensures that the selected dip strategy has all required parameters.

    Attributes:
        coor: 3D coordinate for the well position on the pipette bed.
        dip_top: Distance from top of well to initial liquid surface in mm (must be > 0)
        dip_btm: Distance from top of well to bottom in mm (must be > 0), or None.
        strategy_type: Type of dip strategy to use (default: SIMPLE).
        well_diameter: Diameter of the well in mm (must be > 0), or None.
    """

    coor: Coordinate
    dip_top: float = Field(..., gt=0)
    dip_btm: float | None = Field(None, gt=0)
    strategy_type: StrategyType = StrategyType.SIMPLE
    well_diameter: float | None = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_strategy_requirements(self) -> "WellParams":
        """Validate that the well configuration matches strategy requirements.

        Ensures the selected dip strategy has all the parameters it needs
        to function correctly. For example, CYLINDER strategy requires both
        well_diameter and dip_btm to be defined.

        Returns:
            Self with validated configuration.

        Note:
            Strategy validation will raise ValueError if required parameters
            are missing. For example, CYLINDER strategy requires well_diameter
            and dip_btm.

        Example:
            >>> # Valid simple strategy (no extra params needed)
            >>> params = WellParams(
            ...     coor=Coordinate(x=10, y=20, z=5),
            ...     dip_top=10.0,
            ...     strategy_type=StrategyType.SIMPLE
            ... )
            >>>
            >>> # Invalid cylinder strategy (missing diameter)
            >>> params = WellParams(
            ...     coor=Coordinate(x=10, y=20, z=5),
            ...     dip_top=10.0,
            ...     dip_btm=50.0,
            ...     strategy_type=StrategyType.CYLINDER
            ... )  # Will fail: Cylinder strategy requires well_diameter
        """
        strategy = StrategyRegistry.get_strategy(self.strategy_type)
        strategy.validate_well_config(self.well_diameter, self.dip_btm)
        return self


class Well:
    """A vessel to hold chemicals with configurable dip behavior.

    Represents a physical well on the pipette bed, tracking its position,
    geometry, and liquid level. Uses a dip strategy to determine how deep
    the pipette tip should descend based on liquid volume.

    Attributes:
        coor: 3D coordinate of the well position.
        dip_top: Distance from well top to initial liquid surface in mm.
        dip_btm: Distance from well top to bottom in mm, or None.
        dip_curr: Current dip distance in mm (updated by strategy).
        well_diameter: Diameter of the well in mm, or None.
    """

    def __init__(
        self,
        coor: Coordinate,
        dip_top: float,
        dip_btm: float | None = None,
        strategy_type: StrategyType = StrategyType.SIMPLE,
        well_diameter: float | None = None,
    ) -> None:
        """Initialize a well with the specified dip strategy.

        Creates a well at the given position with the specified geometry
        and dip strategy. Validates that the strategy has all required
        parameters.

        Args:
            coor: 3D coordinate for the well position.
            dip_top: Distance from top of well to initial liquid surface in mm.
            dip_btm: Distance from top of well to bottom in mm, or None.
            strategy_type: Type of dip strategy to use (default: SIMPLE).
            well_diameter: Diameter of the well in mm, or None.

        Note:
            Strategy validation ensures required parameters are provided.
            For example, CYLINDER strategy requires both well_diameter and dip_btm.

        Example:
            >>> # Simple well (no volume tracking)
            >>> well = Well(
            ...     coor=Coordinate(x=10, y=20, z=5),
            ...     dip_top=10.0
            ... )
            >>>
            >>> # Cylindrical well (tracks volume changes)
            >>> well = Well(
            ...     coor=Coordinate(x=10, y=20, z=5),
            ...     dip_top=10.0,
            ...     dip_btm=50.0,
            ...     strategy_type=StrategyType.CYLINDER,
            ...     well_diameter=8.0
            ... )
        """
        self.coor = coor
        self.dip_top = dip_top
        self.dip_btm = dip_btm
        self.dip_curr = dip_top
        self.well_diameter = well_diameter

        self._strategy = StrategyRegistry.get_strategy(strategy_type)
        self._strategy.validate_well_config(well_diameter, dip_btm)

    def get_dip_distance(self, volume: float) -> float:
        """Return the distance needed to dip into a well for the given volume.

        Calculates how far the pipette tip should descend from the top of
        the well, accounting for the volume being aspirated or dispensed
        according to the well's dip strategy.

        Args:
            volume: Volume of liquid being aspirated/dispensed in microliters.

        Returns:
            Dip distance from the top of the well in millimeters.

        Note:
            For CYLINDER strategy, this method updates dip_curr as a side effect.

        Example:
            >>> well = Well(
            ...     coor=Coordinate(x=10, y=20, z=5),
            ...     dip_top=10.0,
            ...     dip_btm=50.0,
            ...     strategy_type=StrategyType.CYLINDER,
            ...     well_diameter=8.0
            ... )
            >>> distance = well.get_dip_distance(100.0)
            >>> distance  # Accounts for 100 µL removed
            12.0
        """
        return self._strategy.calculate_dip_distance(self, volume)

    @property
    def strategy_type(self) -> StrategyType:
        """Get the name of the current strategy.

        Returns:
            StrategyType enum identifying the current dip strategy.

        Example:
            >>> well = Well(
            ...     coor=Coordinate(x=10, y=20, z=5),
            ...     dip_top=10.0,
            ...     strategy_type=StrategyType.CYLINDER,
            ...     well_diameter=8.0,
            ...     dip_btm=50.0
            ... )
            >>> well.strategy_name
            <StrategyType.CYLINDER: 'cylinder'>
        """
        return StrategyRegistry.get_strategy_type(self._strategy)


# Rebuild WellParams after Well is defined to resolve forward references
WellParams.model_rebuild()
