#!/usr/bin/env python3
"""Location and plate management for the AutoPipette system.

This module handles storage, retrieval, and management of named locations
and plates used in pipetting operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from coordinate import Coordinate
from pipette_constants import PlateType
from pipette_exceptions import NotALocationError
from plates import Plate, PlateFactory, PlateParams, TipBox, WasteContainer

if TYPE_CHECKING:
    from config_manager import ConfigManager

logger = logging.getLogger(__name__)


class LocationManager:
    """Manages named locations and plates for the pipette system.

    Handles storage and retrieval of coordinates and plates, including
    special handling for tipboxes and waste containers.

    Attributes:
        locations: Dictionary mapping location names to Coordinates or Plates.
        waste_container: The designated waste container (if configured).
        tipboxes: The primary tipbox or linked tipboxes (if configured).
        _config_manager: Optional config manager for persistence.

    Example:
        >>> manager = LocationManager()
        >>> coord = Coordinate(x=100, y=50, z=10)
        >>> manager.set_coordinate("home", coord)
        >>> position = manager.get_coordinate("home")
    """

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        """Initialize the location manager.

        Args:
            config_manager: Optional config manager for saving changes.

        Example:
            >>> # Without persistence
            >>> manager = LocationManager()

            >>> # With persistence
            >>> from config_manager import ConfigManager
            >>> config = ConfigManager()
            >>> manager = LocationManager(config)
        """
        self.locations: dict[str, Coordinate | Plate] = {}
        self.waste_container: WasteContainer | None = None
        self.tipboxes: TipBox | None = None
        self._config_manager = config_manager

    def clear(self) -> None:
        """Clear all locations, tipboxes, and waste container.

        Example:
            >>> manager.clear()
            >>> # All locations removed
        """
        self.locations.clear()
        self.waste_container = None
        self.tipboxes = None

    def set_coordinate(self, name: str, coord: Coordinate) -> None:
        """Create or update a named coordinate location.

        Args:
            name: Name to assign to this coordinate.
            coord: Coordinate object representing the position.

        Note:
            If a location with this name already exists, it will be overwritten.
            Updates configuration if config_manager is available.

        Example:
            >>> coord = Coordinate(x=100, y=50, z=10)
            >>> manager.set_coordinate("home_position", coord)
        """
        self.locations[name] = coord

        # Update configuration if available
        if self._config_manager is not None:
            conf_key = f"COORDINATE {name}"

            if not self._config_manager.config.has_section(conf_key):
                self._config_manager.config.add_section(conf_key)

            self._config_manager.update_value(conf_key, "x", str(coord.x))
            self._config_manager.update_value(conf_key, "y", str(coord.y))
            self._config_manager.update_value(conf_key, "z", str(coord.z))

    def set_plate(self, name: str, plate_params: PlateParams) -> None:
        """Create or update a plate at a named location.

        Creates a Plate object from parameters and stores it with the given name.
        Handles special plate types (waste_container, tipbox) automatically.

        Args:
            name: Name to assign to this plate.
            plate_params: Validated plate parameters including type and dimensions.

        Raises:
            TypeError: If the plate factory creates an incorrect plate type for
                       the specified plate_type (e.g., plate_type is 'waste_container'
                       but factory doesn't create a WasteContainer instance).

        Note:
            - Removes any existing location with the same name
            - Waste containers are automatically set as the default waste location
            - Tipboxes are added to the tipbox pool
            - Updates configuration if config_manager is available

        Example:
            >>> from well import Well
            >>> well = Well(coor=Coordinate(10, 10, 5), ...)
            >>> params = PlateParams(
            ...     plate_type="array",
            ...     well_template=well,
            ...     num_row=8,
            ...     num_col=12
            ... )
            >>> manager.set_plate("96_well_plate", params)
        """
        # Remove any existing location with this name
        self.locations.pop(name, None)

        # Create the plate using factory
        plate = PlateFactory.create(plate_params)
        self.locations[name] = plate

        # Update configuration if available
        if self._config_manager is not None:
            # Remove any existing COORDINATE section with the same name
            self._config_manager.config.remove_section(f"COORDINATE {name}")

            conf_key = f"PLATE {name}"
            if not self._config_manager.config.has_section(conf_key):
                self._config_manager.config.add_section(conf_key)

            # Save all plate parameters
            self._config_manager.update_value(
                conf_key, "x", str(plate_params.well_template.coor.x)
            )
            self._config_manager.update_value(
                conf_key, "y", str(plate_params.well_template.coor.y)
            )
            self._config_manager.update_value(
                conf_key, "z", str(plate_params.well_template.coor.z)
            )
            self._config_manager.update_value(
                conf_key, "type", str(plate_params.plate_type)
            )
            self._config_manager.update_value(
                conf_key, "row", str(plate_params.num_row)
            )
            self._config_manager.update_value(
                conf_key, "col", str(plate_params.num_col)
            )
            self._config_manager.update_value(
                conf_key, "spacing_row", str(plate_params.spacing_row)
            )
            self._config_manager.update_value(
                conf_key, "spacing_col", str(plate_params.spacing_col)
            )
            self._config_manager.update_value(
                conf_key, "dip_top", str(plate_params.well_template.dip_top)
            )
            self._config_manager.update_value(
                conf_key, "dip_btm", str(plate_params.well_template.dip_btm)
            )
            self._config_manager.update_value(
                conf_key, "dip_func", str(plate_params.well_template.strategy_name)
            )

        # Handle special plate types with type checking
        if plate_params.plate_type == PlateType.WASTE_CONTAINER.value:
            # Type check and assert
            if not isinstance(plate, WasteContainer):
                raise TypeError(
                    f"Plate type is '{PlateType.WASTE_CONTAINER.value}' but "
                    f"factory created {type(plate).__name__}"
                )
            self.waste_container = plate
            self.locations["waste_container"] = self.waste_container
            logger.info(f"Set waste container: {name}")
        elif plate_params.plate_type == PlateType.TIPBOX.value:
            # Type check and assert
            if not isinstance(plate, TipBox):
                raise TypeError(
                    f"Plate type is '{PlateType.TIPBOX.value}' but "
                    f"factory created {type(plate).__name__}"
                )
            if self.tipboxes is None:
                self.tipboxes = plate
                logger.info(f"Set primary tipbox: {name}")
            else:
                # Type checker can't infer tipboxes is TipBox in else branch
                existing_tipbox: TipBox = self.tipboxes
                existing_tipbox.append_box(plate)  # type: ignore[attr-defined]
                logger.info(f"Added additional tipbox: {name}")

    def has_location(self, name: str) -> bool:
        """Check if a named location exists.

        Args:
            name: Name of the location to check.

        Returns:
            True if the location exists, False otherwise.

        Example:
            >>> manager.has_location("plate_a")
            True
            >>> manager.has_location("nonexistent")
            False
        """
        return name in self.locations

    def get_coordinate(
        self,
        name: str,
        row: int | None = None,
        col: int | None = None,
    ) -> Coordinate:
        """Retrieve a coordinate from a named location.

        For simple coordinates, returns the coordinate directly.
        For plates, returns the next well position or a specific well.

        Args:
            name: Name of the location.
            row: Row index for plate wells (0-based), or None for next well.
            col: Column index for plate wells (0-based), or None for next well.

        Returns:
            Coordinate object representing the position.

        Raises:
            NotALocationError: If the location name doesn't exist.
            ValueError: If only one of row/col is provided (both required or both None).

        Note:
            For plates:
            - If row and col are None, returns the next sequential well
            - If row and col are specified, returns that specific well
            - Plate automatically tracks current position for sequential access

        Example:
            >>> # Get simple coordinate
            >>> coord = manager.get_coordinate("home")

            >>> # Get next well from plate
            >>> well1 = manager.get_coordinate("plate_a")

            >>> # Get specific well from plate (row 1, col 1 = B2)
            >>> well_b2 = manager.get_coordinate("plate_a", row=1, col=1)
        """
        if name not in self.locations:
            raise NotALocationError(name)

        location = self.locations[name]

        if isinstance(location, Plate):
            if row is None and col is None:
                # Get next sequential well
                return location.next()
            elif row is not None and col is not None:
                # Get specific well (both provided)
                # Type checker can't infer that row and col are not None
                return location.get_coor(row, col)  # type: ignore[attr-defined]
            else:
                # Only one of row/col provided - invalid
                raise ValueError(
                    "Both row and col must be provided together, or both must be None"
                )
        elif isinstance(location, Coordinate):
            return location
        else:
            # Shouldn't happen, but handle gracefully
            raise NotALocationError(name)

    def get_plate_names(self) -> list[str]:
        """Get names of all locations that are plates.

        Returns:
            List of location names that contain Plate objects.

        Example:
            >>> plates = manager.get_plate_names()
            >>> # plates = ['96_well_plate', 'tipbox', 'waste']
            >>> for plate_name in plates:
            ...     print(f"Plate: {plate_name}")
        """
        return [
            name
            for name, location in self.locations.items()
            if isinstance(location, Plate)
        ]

    def get_coordinate_names(self) -> list[str]:
        """Get names of all locations that are simple coordinates.

        Returns:
            List of location names that are Coordinate objects.

        Example:
            >>> coords = manager.get_coordinate_names()
            >>> # coords = ['home', 'safe_position']
        """
        return [
            name
            for name, location in self.locations.items()
            if isinstance(location, Coordinate)
        ]

    def get_all_names(self) -> list[str]:
        """Get all location names.

        Returns:
            List of all location names (coordinates and plates).

        Example:
            >>> all_locs = manager.get_all_names()
            >>> # all_locs = ['home', 'plate_a', 'tipbox', 'waste']
        """
        return list(self.locations.keys())

    def remove_location(self, name: str) -> None:
        """Remove a location by name.

        Args:
            name: Name of the location to remove.

        Note:
            Does nothing if the location doesn't exist.
            If removing a waste container or tipbox, those references are cleared.

        Example:
            >>> manager.remove_location("old_plate")
        """
        if name not in self.locations:
            return

        location = self.locations[name]

        # Clear special references
        if location is self.waste_container:
            self.waste_container = None
            self.locations.pop("waste_container", None)

        if location is self.tipboxes:
            self.tipboxes = None

        # Remove from locations
        self.locations.pop(name)

        # Remove from config if available
        if self._config_manager is not None:
            self._config_manager.config.remove_section(f"COORDINATE {name}")
            self._config_manager.config.remove_section(f"PLATE {name}")

    def load_from_config(self, config_manager: ConfigManager) -> None:
        """Load all locations from a configuration manager.

        Args:
            config_manager: ConfigManager with loaded configuration.

        Note:
            Clears existing locations before loading.

        Example:
            >>> from config_manager import ConfigManager
            >>> config = ConfigManager()
            >>> config.load("autopipette.conf")
            >>> manager.load_from_config(config)
        """
        self.clear()
        self._config_manager = config_manager

        # Parse locations from config
        parsed_locations = config_manager.parse_locations()

        # Add each location
        for name, (coord, plate_params) in parsed_locations.items():
            self.set_coordinate(name, coord)

            if plate_params is not None:
                self.set_plate(name, plate_params)

    def get_location_info(self, name: str) -> dict[str, str]:
        """Get information about a location.

        Args:
            name: Name of the location.

        Returns:
            Dictionary with location type and details.

        Raises:
            NotALocationError: If the location doesn't exist.

        Example:
            >>> info = manager.get_location_info("plate_a")
            >>> # info = {'type': 'plate', 'rows': '8', 'cols': '12'}
        """
        if name not in self.locations:
            raise NotALocationError(name)

        location = self.locations[name]

        if isinstance(location, Coordinate):
            return {
                "type": "coordinate",
                "x": str(location.x),
                "y": str(location.y),
                "z": str(location.z),
            }
        elif isinstance(location, Plate):
            info: dict[str, str] = {
                "type": "plate",
                "rows": str(location.num_row),
                "cols": str(location.num_col),
            }
            # Only add current position if attributes exist
            if hasattr(location, "current_row") and hasattr(location, "current_col"):
                # Type checker can't infer tipboxes is TipBox in else branch
                info["current_row"] = str(location.current_row)  # type: ignore[attr-defined]
                info["current_col"] = str(location.current_col)  # type: ignore[attr-defined]
            return info
        else:
            return {"type": "unknown"}
