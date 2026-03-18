#!/usr/bin/env python3
"""Location and plate management for the AutoPipette system.

This module handles storage, retrieval, and management of named locations
and plates used in pipetting operations using JSON configuration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from coordinate import Coordinate
from pipette_constants import (
    DefaultFilenames,
    DefaultPaths,
    PlateType,
)
from pipette_exceptions import NotALocationError
from plates import Plate, PlateFactory, PlateParams, TipBox, WasteContainer
from well import StrategyType, Well

logger = logging.getLogger(__name__)

CONFIG_LOCATIONS = DefaultFilenames.CONFIG_LOCATIONS
DIR_CONFIG_LOCATIONS = DefaultPaths.DIR_CONFIG_LOCATIONS
DIR_CONFIG_PLATES = DefaultPaths.DIR_CONFIG_PLATES


class LocationManager:
    """Manages named locations and plates for the pipette system.

    Handles storage and retrieval of coordinates and plates, including
    special handling for tipboxes and waste containers. Uses JSON
    configuration for persistence.

    Attributes:
        locations: Dictionary mapping location names to Coordinates or Plates.
        waste_container: The designated waste container (if configured).
        tipboxes: The primary tipbox or linked tipboxes (if configured).
        config_dir: Path to configuration directory for loading/saving.

    Example:
        >>> manager = LocationManager()
        >>> coord = Coordinate(x=100, y=50, z=10)
        >>> manager.set_coordinate("home", coord)
        >>> position = manager.get_coordinate("home")
    """

    def __init__(self) -> None:
        """Initialize the location manager.

        Example:
            >>> # Use default config directory
            >>> manager = LocationManager()

            >>> # Use custom config directory
            >>> manager = LocationManager(Path("/custom/config"))
        """
        self.locations: dict[str, Coordinate | Plate] = {}
        self.waste_container: WasteContainer | None = None
        self.tipboxes: TipBox | None = None

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

        Example:
            >>> coord = Coordinate(x=100, y=50, z=10)
            >>> manager.set_coordinate("home_position", coord)
        """
        self.locations[name] = coord

    def set_plate(self, name: str, plate_params: PlateParams) -> None:
        """Create or update a plate at a named location.

        Creates a Plate object from parameters and stores it with the given name.
        Handles special plate types (waste_container, tipbox) automatically.

        Args:
            name: Name to assign to this plate.
            plate_params: Validated plate parameters including type and dimensions.

        Raises:
            TypeError: If the plate factory creates an incorrect plate type.
            RuntimeError: If appending to the tipbox and it is not a tipbox

        Note:
            - Removes any existing location with the same name
            - Waste containers are automatically set as the default waste location
            - Tipboxes are added to the tipbox pool

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

        # Handle special plate types with type checking
        if plate_params.plate_type == PlateType.WASTE_CONTAINER.value:
            if not isinstance(plate, WasteContainer):
                raise TypeError(
                    f"Plate type is '{PlateType.WASTE_CONTAINER.value}' but "
                    f"factory created {type(plate).__name__}"
                )
            self.waste_container = plate
            self.locations["waste_container"] = self.waste_container
            logger.info(f"Set waste container: {name}")
        elif plate_params.plate_type == PlateType.TIPBOX.value:
            if not isinstance(plate, TipBox):
                raise TypeError(
                    f"Plate type is '{PlateType.TIPBOX.value}' but "
                    f"factory created {type(plate).__name__}"
                )
            if self.tipboxes is None:
                self.tipboxes = plate
                logger.info(f"Set primary tipbox: {name}")
            else:
                if not isinstance(self.tipboxes, TipBox):
                    raise RuntimeError("Existing tipboxes is not a TipBox instance")
                self.tipboxes.append_box(plate)  # type: ignore[attr-defined]
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
            ValueError: If only one of row/col is provided.

        Example:
            >>> # Get simple coordinate
            >>> coord = manager.get_coordinate("home")

            >>> # Get next well from plate
            >>> well1 = manager.get_coordinate("plate_a")

            >>> # Get specific well (row 1, col 1 = B2)
            >>> well_b2 = manager.get_coordinate("plate_a", row=1, col=1)
        """
        if name not in self.locations:
            raise NotALocationError(name)

        location = self.locations[name]

        if isinstance(location, Plate):
            if row is None and col is None:
                return location.next()
            elif row is not None and col is not None:
                coor = location.get_coor(row, col)
                if coor is not None:
                    return coor
                else:
                    raise ValueError("Coordinate returned from location is None.")
            else:
                raise ValueError(
                    "Both row and col must be provided together, or both must be None"
                )
        elif isinstance(location, Coordinate):
            return location
        else:
            raise NotALocationError(name)

    def get_plate_names(self) -> list[str]:
        """Get names of all locations that are plates.

        Returns:
            List of location names that contain Plate objects.

        Example:
            >>> plates = manager.get_plate_names()
            >>> # plates = ['96_well_plate', 'tipbox', 'waste']
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

    def load_from_json(self, filename: str = CONFIG_LOCATIONS) -> None:
        """Load all locations from a JSON configuration file.

        Loads locations from config_dir/locations/filename.

        Args:
            filename: Name of locations JSON file. Defaults to
                     'default_locations.json'.

        Raises:
            FileNotFoundError: If locations file doesn't exist.
            ValueError: If JSON is invalid.

        Note:
            Clears existing locations before loading.

        Example:
            >>> manager = LocationManager(Path("config"))
            >>> manager.load_from_json("my_locations.json")
        """
        self.clear()

        locations_file = DIR_CONFIG_LOCATIONS / filename

        if not locations_file.exists():
            logger.warning(f"Locations file not found: {locations_file}")
            raise FileNotFoundError(f"Locations file not found: {locations_file}")

        try:
            with locations_file.open("r", encoding="utf-8") as f:
                locations_data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in locations file: {e}")
            raise ValueError(f"Invalid JSON in {filename}: {e}") from e

        # Load coordinates
        for coord_data in locations_data.get("coordinates", []):
            name = coord_data["name"]
            coord = Coordinate(x=coord_data["x"], y=coord_data["y"], z=coord_data["z"])
            self.set_coordinate(name, coord)
            logger.debug(f"Loaded coordinate: {name}")

        # Load plates
        for plate_data in locations_data.get("plates", []):
            name = plate_data["name"]

            # Load plate definition from separate file if referenced
            if "plate_file" in plate_data:
                plate_def = self._load_plate_definition(
                    DIR_CONFIG_PLATES / plate_data["plate_file"]
                )
                # Override coordinate from locations file
                plate_def["x"] = plate_data["x"]
                plate_def["y"] = plate_data["y"]
                plate_def["z"] = plate_data["z"]
            else:
                plate_def = plate_data

            # Create well template
            well = Well(
                coor=Coordinate(x=plate_def["x"], y=plate_def["y"], z=plate_def["z"]),
                dip_top=float(plate_def.get("dip_top", 0)),
                dip_btm=(
                    float(plate_def["dip_btm"]) if plate_def.get("dip_btm") else None
                ),
                strategy_type=StrategyType(plate_def.get("dip_func", "simple")),
                well_diameter=(
                    float(plate_def["well_diameter"])
                    if plate_def.get("well_diameter")
                    else None
                ),
            )

            # Create plate parameters
            plate_params = PlateParams(
                plate_type=plate_def.get("type", "array"),
                well_template=well,
                num_row=int(plate_def.get("num_row", 1)),
                num_col=int(plate_def.get("num_col", 1)),
                spacing_row=float(plate_def.get("spacing_row", 0)),
                spacing_col=float(plate_def.get("spacing_col", 0)),
            )

            self.set_plate(name, plate_params)
            logger.debug(f"Loaded plate: {name}")

        logger.info(
            f"Loaded {len(self.locations)} location(s) from {filename}: "
            f"{len(self.get_coordinate_names())} coordinates, "
            f"{len(self.get_plate_names())} plates"
        )

    def save_to_json(self, filename: str = "custom_locations.json") -> None:
        """Save all locations to a JSON configuration file.

        Saves to config_dir/locations/filename.

        Args:
            filename: Name of output JSON file. Defaults to
                     'custom_locations.json'.

        Note:
            Creates the locations directory if it doesn't exist.

        Example:
            >>> manager.save_to_json("backup_locations.json")
        """
        locations_dir = DIR_CONFIG_LOCATIONS
        locations_dir.mkdir(parents=True, exist_ok=True)

        locations_file = locations_dir / filename

        # Build JSON structure
        data = {"coordinates": [], "plates": []}

        # Save coordinates
        for name in self.get_coordinate_names():
            location = self.locations[name]
            if isinstance(location, Coordinate):
                data["coordinates"].append(
                    {"name": name, "x": location.x, "y": location.y, "z": location.z}
                )

        # Save plates
        for name in self.get_plate_names():
            location = self.locations[name]
            if isinstance(location, Plate):
                plate_data = {
                    "name": name,
                    "type": location.__class__.__name__.lower(),
                    "x": location.wells[0].coor.x if location.wells else 0,
                    "y": location.wells[0].coor.y if location.wells else 0,
                    "z": location.wells[0].coor.z if location.wells else 0,
                    "num_row": location.num_row,
                    "num_col": location.num_col,
                }

                # Add plate-specific attributes if they exist
                if hasattr(location, "spacing_row"):
                    plate_data["spacing_row"] = location.spacing_row
                if hasattr(location, "spacing_col"):
                    plate_data["spacing_col"] = location.spacing_col

                # Add well template info
                if location.wells:
                    first_well = location.wells[0]
                    plate_data["dip_top"] = first_well.dip_top
                    if first_well.dip_btm is not None:
                        plate_data["dip_btm"] = first_well.dip_btm
                    plate_data["dip_func"] = first_well.strategy_type.value
                    if first_well.well_diameter is not None:
                        plate_data["well_diameter"] = first_well.well_diameter

                data["plates"].append(plate_data)

        # Write to file
        with locations_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(self.locations)} location(s) to {filename}")

    def _load_plate_definition(self, plate_file: Path) -> dict:
        """Load plate definition from JSON file.

        Args:
            plate_file: Path to plate definition JSON file.

        Returns:
            Dictionary containing plate definition.

        Raises:
            FileNotFoundError: If plate file doesn't exist.
            ValueError: If JSON is invalid.
        """
        try:
            with plate_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as e:
            logger.error(f"Plate definition file not found: {plate_file}")
            raise FileNotFoundError(f"Plate definition not found: {plate_file}") from e
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in plate definition: {e}")
            raise ValueError(f"Invalid plate definition JSON: {e}") from e

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
            if hasattr(location, "current_row") and hasattr(location, "current_col"):
                info["current_row"] = str(location.current_row)
                info["current_col"] = str(location.current_col)
            return info
        else:
            return {"type": "unknown"}

    def __repr__(self) -> str:
        """Return string representation of LocationManager.

        Returns:
            String showing number of locations and special plates.

        Example:
            >>> manager = LocationManager()
            >>> repr(manager)
            'LocationManager(locations=5, tipboxes=yes, waste=yes)'
        """
        return (
            f"LocationManager("
            f"locations={len(self.locations)}, "
            f"tipboxes={'yes' if self.tipboxes else 'no'}, "
            f"waste={'yes' if self.waste_container else 'no'})"
        )
