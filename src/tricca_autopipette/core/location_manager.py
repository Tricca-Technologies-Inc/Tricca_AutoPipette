#!/usr/bin/env python3
"""Location and plate management for the AutoPipette system.

This module handles storage, retrieval, and management of named locations
and plates used in pipetting operations using JSON configuration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import (
    DefaultFilenames,
    DefaultPaths,
    LocalConfigRoots,
    PlateType,
)
from tricca_autopipette.core.pipette_exceptions import NotALocationError
from tricca_autopipette.core.plates import (
    Plate,
    PlateFactory,
    PlateParams,
    TipBox,
    WasteContainer,
)
from tricca_autopipette.core.tipbox_manager import TipBoxManager
from tricca_autopipette.core.traversal import (
    TraversalOrder,
    TraversalRegistry,
    WellMask,
    coerce_traversal_order,
    compress_to_ranges,
    parse_well_ranges,
)
from tricca_autopipette.core.well import StrategyType, Well

logger = logging.getLogger(__name__)

CONFIG_LOCATIONS = DefaultFilenames.CONFIG_LOCATIONS


class LocationManager:
    """Manages named locations and plates for the pipette system.

    Handles storage and retrieval of coordinates and plates, including
    special handling for tipboxes and waste containers. Uses JSON
    configuration for persistence.

    Attributes:
        locations: Dictionary mapping location names to Coordinates or Plates.
        waste_container: The designated waste container (if configured).
        tipbox_manager: Owns every registered tipbox and decides which supplies
            the next tip. Replaces an earlier single `tipboxes` attribute that
            merged extra boxes into the first one.
        locations_dir: Directory `load_from_json`/`save_to_json` resolve
            their filenames against.

    Example:
        >>> manager = LocationManager()
        >>> coord = Coordinate(x=100, y=50, z=10)
        >>> manager.set_coordinate("home", coord)
        >>> position = manager.get_coordinate("home")
    """

    def __init__(self, locations_dir: Path | None = None) -> None:
        """Initialize the location manager.

        Args:
            locations_dir: Directory to load/save locations files from. If
                None (the default), every filename is resolved through
                `LocalConfigRoots` instead -- shared ``config/locations/``
                and the per-machine local root (issue #68), local winning on
                a name collision. An explicit directory is mainly an
                injection point for tests, which would otherwise have to
                write scratch files into the real repo/local root and clean
                up after themselves; it disables the shared/local split
                entirely; only that one directory is used.

        Example:
            >>> # Resolve locations via the shared/local split
            >>> manager = LocationManager()

            >>> # Use a single custom locations directory instead
            >>> manager = LocationManager(Path("/custom/config/locations"))
        """
        self.locations_dir: Path | None = locations_dir
        self.locations: dict[str, Coordinate | Plate] = {}
        self.waste_container: WasteContainer | None = None
        self.tipbox_manager: TipBoxManager = TipBoxManager()
        # name -> originating file, so a duplicate-name warning can name both
        # sides and `ls` can show where a location came from.
        self._sources: dict[str, str] = {}

    def clear(self) -> None:
        """Clear all locations, tipboxes, and waste container.

        Example:
            >>> manager = LocationManager()
            >>> manager.clear()
            >>> # All locations removed
        """
        self.locations.clear()
        self.waste_container = None
        self.tipbox_manager.clear()
        self._sources.clear()

    def set_coordinate(self, name: str, coord: Coordinate) -> None:
        """Create or update a named coordinate location.

        Args:
            name: Name to assign to this coordinate.
            coord: Coordinate object representing the position.

        Note:
            If a location with this name already exists, it will be overwritten.

        Example:
            >>> manager = LocationManager()
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

        Note:
            - Removes any existing location with the same name
            - Waste containers are automatically set as the default waste location
            - Tipboxes are registered with `tipbox_manager`, which draws from
              them in registration order. Each stays a separate object with its
              own consumed-tip state, so one can be unloaded without disturbing
              the others.

        Example:
            >>> from tricca_autopipette.core.well import Well
            >>> from tricca_autopipette.core.coordinate import Coordinate
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="array", well_template=well, num_row=8, num_col=12
            ... )
            >>> manager.set_plate("96_well_plate", params)
        """
        # Drop any prior location under this name, including its tipbox
        # registration, so replacing a plate never leaves a stale box behind.
        self.remove_location(name)

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
            logger.info(f"Set waste container: {name}")
        elif plate_params.plate_type == PlateType.TIPBOX.value:
            if not isinstance(plate, TipBox):
                raise TypeError(
                    f"Plate type is '{PlateType.TIPBOX.value}' but "
                    f"factory created {type(plate).__name__}"
                )
            self.tipbox_manager.register(name, plate)
            logger.info(f"Registered tipbox: {name}")

    def has_location(self, name: str) -> bool:
        """Check if a named location exists.

        Args:
            name: Name of the location to check.

        Returns:
            True if the location exists, False otherwise.

        Example:
            >>> manager = LocationManager()
            >>> manager.set_coordinate("plate_a", Coordinate(x=0, y=0, z=0))
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
            ValueError: If only one of row/col is provided, or if row/col
                address a cell outside the plate.

        Example:
            >>> manager = LocationManager()
            >>> manager.set_coordinate("home", Coordinate(x=0, y=0, z=0))

            >>> # Get simple coordinate
            >>> coord = manager.get_coordinate("home")

            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="array", well_template=well, num_row=8, num_col=12
            ... )
            >>> manager.set_plate("plate_a", params)

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
            if row is not None and col is not None:
                # get_coor raises ValueError for an out-of-bounds cell; it
                # never returns None.
                return location.get_coor(row, col)
            raise ValueError(
                "Both row and col must be provided together, or both must be None"
            )
        return location

    def get_plate_names(self) -> list[str]:
        """Get names of all locations that are plates.

        Returns:
            List of location names that contain Plate objects.

        Example:
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="array", well_template=well, num_row=8, num_col=12
            ... )
            >>> manager.set_plate("96_well_plate", params)
            >>> manager.get_plate_names()
            ['96_well_plate']
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
            >>> manager = LocationManager()
            >>> manager.set_coordinate("home", Coordinate(x=0, y=0, z=0))
            >>> manager.get_coordinate_names()
            ['home']
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
            >>> manager = LocationManager()
            >>> manager.set_coordinate("home", Coordinate(x=0, y=0, z=0))
            >>> manager.get_all_names()
            ['home']
        """
        return list(self.locations.keys())

    def remove_location(self, name: str) -> None:
        """Remove a location by name.

        Args:
            name: Name of the location to remove.

        Note:
            Does nothing if the location doesn't exist.
            If removing a waste container or tipbox, those references are
            cleared. Unloading one tipbox leaves every other box's consumed-tip
            state untouched.

        Example:
            >>> manager = LocationManager()
            >>> manager.set_coordinate("old_plate", Coordinate(x=0, y=0, z=0))
            >>> manager.remove_location("old_plate")
            >>> manager.has_location("old_plate")
            False
        """
        if name not in self.locations:
            return

        location = self.locations[name]

        # Clear special references
        if location is self.waste_container:
            self.waste_container = None

        self.tipbox_manager.unregister(name)

        # Remove from locations
        self.locations.pop(name)

    def unload(self, name: str) -> bool:
        """Remove a single location by name.

        The counterpart to additive loading: a deck composed from several
        groups can have one item taken off it without reloading the rest.

        Args:
            name: Name of the location to unload.

        Returns:
            True if a location was removed, False if no such name was loaded.

        Note:
            Unloading a tipbox leaves every other box's consumed-tip state
            untouched.

        Example:
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="tipbox", well_template=well, num_row=8, num_col=12
            ... )
            >>> manager.set_plate("tipbox_a", params)
            >>> manager.unload("tipbox_a")
            True
        """
        if name not in self.locations:
            return False

        self.remove_location(name)
        self._sources.pop(name, None)
        logger.info(f"Unloaded location: {name}")
        return True

    def source_of(self, name: str) -> str | None:
        """Report which file a location was loaded from.

        Args:
            name: Name of the location.

        Returns:
            The source description recorded at load time, or None for
            locations created interactively (via `set_coordinate`/`set_plate`)
            or not loaded at all.

        Example:
            >>> manager = LocationManager()
            >>> manager.apply_locations_data(
            ...     {"coordinates": [{"name": "tipbox_a", "x": 0, "y": 0, "z": 0}]},
            ...     source="deck_a.json",
            ... )
            >>> manager.source_of("tipbox_a")
            'deck_a.json'
        """
        return self._sources.get(name)

    def load_from_json(
        self, filename: str = CONFIG_LOCATIONS, *, replace: bool = False
    ) -> None:
        """Load locations from a JSON configuration file.

        Loads locations from `self.locations_dir / filename`.

        Args:
            filename: Name of locations JSON file. Defaults to
                     'default_locations.json'.
            replace: If True, clear all existing locations first. Defaults to
                False, so groups compose -- loading a second file adds to the
                deck rather than replacing it.

        Raises:
            FileNotFoundError: If locations file doesn't exist.
            ValueError: If JSON is invalid, or an entry is malformed.

        Note:
            The file is fully read and parsed *before* anything is applied, so
            a missing file or a malformed entry leaves the existing deck
            untouched. An earlier version cleared first and validated second,
            which wiped the deck on a mistyped filename.

        Example:
            >>> manager = LocationManager()
            >>> manager.load_from_json()  # loads default_locations.json
            >>> manager.load_from_json("default_locations.json")  # adds to the deck
        """  # ruff: ignore[docstring-extraneous-exception]
        locations_data = self._read_locations_file(filename)
        self.apply_locations_data(locations_data, source=filename, replace=replace)

    def load_group(self, filenames: list[str], *, replace: bool = False) -> None:
        """Load several locations files in order, composing one deck.

        Args:
            filenames: Locations filenames to load, in order. Later files win
                on a name collision.
            replace: If True, clear existing locations before the first file.

        Raises:
            FileNotFoundError: If any file doesn't exist.
            ValueError: If any file is invalid.

        Note:
            Every file is read and parsed before any is applied, so one bad
            file in the group aborts the whole load rather than leaving the
            deck half-built.

        Example:
            >>> manager = LocationManager()
            >>> manager.load_group([
            ...     "standard_deck.json",
            ...     "assay_a.json",
            ... ])  # doctest: +SKIP
        """  # ruff: ignore[docstring-extraneous-exception]
        parsed = [(name, self._read_locations_file(name)) for name in filenames]

        if replace:
            self.clear()
        for name, data in parsed:
            self.apply_locations_data(data, source=name, replace=False)

    def load_spec(
        self, sources: list[str | dict[str, Any]], *, replace: bool = False
    ) -> None:
        """Load an ordered list of locations sources.

        The runtime counterpart of a system config's ``locations`` section (see
        `pipette_models.LocationsConfig`): each entry is either a filename to
        resolve against `locations_dir` or an inline payload.

        Args:
            sources: Filenames and/or inline payloads, applied in order. Later
                entries win on a name collision.
            replace: If True, clear existing locations before the first source.

        Raises:
            FileNotFoundError: If a referenced file doesn't exist.
            ValueError: If a source's contents are invalid.

        Note:
            Every source is read and validated before any is applied, so a
            broken entry leaves the existing deck untouched.

        Example:
            >>> manager.load_spec([
            ...     "standard_deck.json",
            ...     {"coordinates": [{"name": "home", "x": 0, "y": 0, "z": 0}]},
            ... ])  # doctest: +SKIP
        """  # ruff: ignore[docstring-extraneous-exception]
        # Resolve everything up front so the commit below cannot fail halfway.
        # Entry types are already validated by `LocationsConfig`, so a
        # non-string here is an inline payload.
        resolved: list[tuple[str, dict[str, Any]]] = []
        for index, entry in enumerate(sources):
            if isinstance(entry, str):
                resolved.append((entry, self._read_locations_file(entry)))
            else:
                resolved.append((f"<inline #{index + 1}>", entry))

        if replace:
            self.clear()
        for source, data in resolved:
            self.apply_locations_data(data, source=source, replace=False)

    def apply_locations_data(
        self,
        locations_data: dict[str, Any],
        *,
        source: str = "<inline>",
        replace: bool = False,
    ) -> None:
        """Apply an already-parsed locations payload.

        Shared by file loading and by the ``locations`` section of a system
        config, which carries the same shape inline. Everything is validated
        before anything is applied.

        Args:
            locations_data: Mapping with optional ``coordinates`` and
                ``plates`` lists, each entry carrying a unique ``name``.
            source: Human-readable origin, used in duplicate-name warnings and
                recorded for `source_of`.
            replace: If True, clear existing locations before applying.

        Raises:
            ValueError: If an entry is malformed or names a plate type that is
                not registered.

        Example:
            >>> manager = LocationManager()
            >>> manager.apply_locations_data(
            ...     {"coordinates": [{"name": "home", "x": 0, "y": 0, "z": 0}]},
            ...     source="system.json",
            ... )
        """  # ruff: ignore[docstring-extraneous-exception]
        coordinates = self._parse_coordinates(locations_data, source)
        plates = self._parse_plates(locations_data, source)

        # Nothing above mutates state, so a failure here leaves the deck as it
        # was. Only past this point do we commit.
        if replace:
            self.clear()

        for name, coord in coordinates:
            self._warn_on_duplicate(name, source)
            self.set_coordinate(name, coord)
            self._sources[name] = source

        for name, params, consumed in plates:
            self._warn_on_duplicate(name, source)
            self.set_plate(name, params)
            self._sources[name] = source
            if consumed is not None:
                self.tipbox_manager.set_consumed(name, consumed)

        logger.info(
            f"Applied {len(coordinates)} coordinate(s) and {len(plates)} "
            f"plate(s) from {source}; deck now holds {len(self.locations)} "
            f"location(s)"
        )

    def _warn_on_duplicate(self, name: str, source: str) -> None:
        """Log when an incoming location overwrites an existing one.

        Names are unique identifiers, so a collision means one definition is
        being discarded. Last load wins, but silently retargeting a pipetting
        step at a different deck position would be dangerous, so it is logged
        with both origins.

        Args:
            name: The location name being applied.
            source: Origin of the incoming definition.
        """
        if name not in self.locations:
            return

        previous = self._sources.get(name, "an earlier definition")
        logger.warning(
            "Location %r from %s overwrites the one from %s", name, source, previous
        )

    def _read_locations_file(self, filename: str) -> dict[str, Any]:
        """Read and parse a locations JSON file.

        Args:
            filename: Name of the file. Resolved against `locations_dir` if
                one was injected, else via `LocalConfigRoots` (shared/local,
                local wins).

        Returns:
            The parsed JSON object.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file is not valid JSON, or is not a JSON object.
        """
        if self.locations_dir is not None:
            locations_file = self.locations_dir / filename
            if not locations_file.exists():
                logger.warning(f"Locations file not found: {locations_file}")
                raise FileNotFoundError(f"Locations file not found: {locations_file}")
        else:
            try:
                locations_file = LocalConfigRoots.resolve("locations", filename)
            except FileNotFoundError as e:
                logger.warning(f"Locations file not found: {e}")
                raise FileNotFoundError(f"Locations file not found: {e}") from e

        try:
            with locations_file.open("r", encoding="utf-8") as f:
                data: Any = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in locations file: {e}")
            raise ValueError(f"Invalid JSON in {filename}: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(
                f"Locations file {filename} must contain a JSON object, got "
                f"{type(data).__name__}"
            )

        return cast("dict[str, Any]", data)

    def _parse_coordinates(
        self, locations_data: dict[str, Any], source: str
    ) -> list[tuple[str, Coordinate]]:
        """Build coordinate entries without applying them.

        Args:
            locations_data: The locations payload.
            source: Origin, for error messages.

        Returns:
            List of ``(name, Coordinate)`` pairs in file order.

        Raises:
            ValueError: If an entry lacks a name or has invalid geometry.
        """
        parsed: list[tuple[str, Coordinate]] = []

        for entry in locations_data.get("coordinates", []):
            coord_data = cast("dict[str, Any]", entry)
            name = self._require_name(coord_data, source, "coordinate")
            try:
                coord = Coordinate(
                    x=coord_data["x"], y=coord_data["y"], z=coord_data["z"]
                )
            except (KeyError, ValueError) as e:
                raise ValueError(f"Invalid coordinate {name!r} in {source}: {e}") from e
            parsed.append((name, coord))

        return parsed

    def _parse_plates(
        self, locations_data: dict[str, Any], source: str
    ) -> list[tuple[str, PlateParams, set[int] | None]]:
        """Build plate entries without applying them.

        Args:
            locations_data: The locations payload.
            source: Origin, for error messages.

        Returns:
            List of ``(name, PlateParams, consumed_indices)`` triples in file
            order. ``consumed_indices`` is None unless the entry declares a
            partially-used tipbox via a ``tips`` block.

        Raises:
            ValueError: If an entry is malformed, names an unregistered plate
                type, or declares tip ranges outside the plate.
            FileNotFoundError: If a ``plate_file`` reference doesn't exist in
                either config root.
        """
        parsed: list[tuple[str, PlateParams, set[int] | None]] = []

        for entry in locations_data.get("plates", []):
            plate_data = cast("dict[str, Any]", entry)
            name = self._require_name(plate_data, source, "plate")

            # A referenced template supplies geometry; the locations entry
            # supplies placement and any per-deck overrides.
            if "plate_file" in plate_data:
                try:
                    plate_file_path = LocalConfigRoots.resolve(
                        "plates", plate_data["plate_file"]
                    )
                except FileNotFoundError as e:
                    raise FileNotFoundError(f"Plate definition not found: {e}") from e
                plate_def = self._load_plate_definition(plate_file_path)
                plate_def.update({
                    key: value
                    for key, value in plate_data.items()
                    if key not in {"name", "plate_file"}
                })
            else:
                plate_def = plate_data

            try:
                params = self._build_plate_params(plate_def)
            except ValueError as e:
                raise ValueError(f"Invalid plate {name!r} in {source}: {e}") from e

            parsed.append((name, params, self._parse_tips(plate_def, params, name)))

        return parsed

    @staticmethod
    def _require_name(entry: dict[str, Any], source: str, kind: str) -> str:
        """Extract an entry's name, which is its unique identifier.

        Args:
            entry: The raw entry mapping.
            source: Origin, for error messages.
            kind: ``"coordinate"`` or ``"plate"``, for error messages.

        Returns:
            The entry's name.

        Raises:
            ValueError: If the entry has no non-empty string name.
        """
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Every {kind} in {source} needs a non-empty 'name'")
        return name

    @staticmethod
    def _build_plate_params(plate_def: dict[str, Any]) -> PlateParams:
        """Build validated plate parameters from a merged plate definition.

        Args:
            plate_def: Plate geometry merged with its placement, i.e. a plate
                template overlaid with the locations entry.

        Returns:
            Validated `PlateParams`.

        Raises:
            ValueError: If geometry, traversal order, or mask is invalid.
        """  # ruff: ignore[docstring-extraneous-exception]
        well = Well(
            coor=Coordinate(x=plate_def["x"], y=plate_def["y"], z=plate_def["z"]),
            dip_top=float(plate_def.get("dip_top", 0)),
            dip_btm=(float(plate_def["dip_btm"]) if plate_def.get("dip_btm") else None),
            strategy_type=StrategyType(plate_def.get("dip_func", "simple")),
            well_diameter=(
                float(plate_def["well_diameter"])
                if plate_def.get("well_diameter")
                else None
            ),
        )

        mask_data = plate_def.get("mask")
        order_data = plate_def.get("order")
        return PlateParams(
            plate_type=plate_def.get("type", "array"),
            well_template=well,
            num_row=int(plate_def.get("num_row", 1)),
            num_col=int(plate_def.get("num_col", 1)),
            spacing_row=float(plate_def.get("spacing_row", 0)),
            spacing_col=float(plate_def.get("spacing_col", 0)),
            order=(
                coerce_traversal_order(order_data)
                if order_data is not None
                else TraversalOrder()
            ),
            mask=WellMask(**mask_data) if mask_data else None,
            on_exhaust=plate_def.get("on_exhaust", "wrap"),
        )

    @staticmethod
    def _parse_tips(
        plate_def: dict[str, Any], params: PlateParams, name: str
    ) -> set[int] | None:
        """Resolve a ``tips`` block into consumed well indices.

        Lets a locations file declare a partially-used tipbox, e.g. a box that
        was half consumed before the deck was set up.

        Args:
            plate_def: The merged plate definition.
            params: The plate's validated parameters, for its dimensions.
            name: Plate name, for error messages.

        Returns:
            Set of consumed flat well indices, or None if the entry declares no
            tip state (in which case the box is assumed full).

        Raises:
            ValueError: If ``tips`` is declared on a non-tipbox, is malformed,
                or names wells outside the plate.
        """
        tips = plate_def.get("tips")
        if tips is None:
            return None

        if params.plate_type != PlateType.TIPBOX.value:
            raise ValueError(f"Plate {name!r} declares 'tips' but is not a tipbox")
        if not isinstance(tips, dict):
            raise ValueError(f"Plate {name!r} has a malformed 'tips' block")

        consumed = cast("dict[str, Any]", tips).get("consumed", [])
        if not isinstance(consumed, list):
            raise ValueError(f"Plate {name!r} has a malformed 'tips.consumed' list")

        try:
            return parse_well_ranges(
                cast("list[str]", consumed), params.num_row, params.num_col
            )
        except ValueError as e:
            raise ValueError(f"Invalid 'tips.consumed' for plate {name!r}: {e}") from e

    def save_to_json(self, filename: str = "custom_locations.json") -> None:
        """Save all locations to a JSON configuration file.

        Saves to `self.locations_dir / filename` if an explicit directory was
        injected, else to `DefaultPaths.DIR_LOCAL_LOCATIONS` -- a save never
        writes into the shared repo at runtime.

        Args:
            filename: Name of output JSON file. Defaults to
                     'custom_locations.json'.

        Note:
            Creates the locations directory if it doesn't exist.

        Example:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     manager = LocationManager(Path(tmp))
            ...     manager.set_coordinate("home", Coordinate(x=0, y=0, z=0))
            ...     manager.save_to_json("backup_locations.json")
            ...     (Path(tmp) / "backup_locations.json").exists()
            True
        """
        locations_dir = self.locations_dir or DefaultPaths.DIR_LOCAL_LOCATIONS
        locations_dir.mkdir(parents=True, exist_ok=True)

        locations_file = locations_dir / filename

        # Build JSON structure
        data: dict[str, list[dict[str, Any]]] = {"coordinates": [], "plates": []}

        # Save coordinates
        for name in self.get_coordinate_names():
            location = self.locations[name]
            if isinstance(location, Coordinate):
                data["coordinates"].append({
                    "name": name,
                    "x": location.x,
                    "y": location.y,
                    "z": location.z,
                })

        # Save plates
        for name in self.get_plate_names():
            location = self.locations[name]
            if isinstance(location, Plate):
                plate_data: dict[str, Any] = {
                    "name": name,
                    "type": PlateFactory.type_name_for(location),
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

                self._save_traversal_fields(location, plate_data)
                data["plates"].append(plate_data)

        # Write to file
        with locations_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Saved {len(self.locations)} location(s) to {filename}")

    @staticmethod
    def _save_traversal_fields(plate: Plate, plate_data: dict[str, Any]) -> None:
        """Add traversal order, mask, exhaustion policy, and tip state.

        Omits anything left at its default, so a hand-written file that used no
        traversal options round-trips unchanged rather than growing noise.

        Args:
            plate: The plate being serialized.
            plate_data: The entry being built, modified in place.
        """
        # A plate written with a preset name saves back as that name; an
        # unnamed combination falls back to the explicit descriptor.
        preset = TraversalRegistry.name_for(plate.order)
        if preset is not None:
            if preset != "row_major":
                plate_data["order"] = preset
        else:
            plate_data["order"] = plate.order.model_dump(mode="json")

        if plate.mask is not None and not plate.mask.is_noop():
            plate_data["mask"] = plate.mask.model_dump(mode="json", exclude_none=True)

        if isinstance(plate, TipBox):
            # Forced to "error" by TipBox itself, so writing it back would only
            # add noise -- but the consumed map is real state worth preserving.
            consumed = compress_to_ranges(plate.consumed_indices(), plate.num_col)
            if consumed:
                plate_data["tips"] = {"consumed": consumed}
        elif plate.on_exhaust != "wrap":
            plate_data["on_exhaust"] = plate.on_exhaust

    def _load_plate_definition(self, plate_file: Path) -> dict[str, Any]:
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
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="array", well_template=well, num_row=8, num_col=12
            ... )
            >>> manager.set_plate("plate_a", params)
            >>> info = manager.get_location_info("plate_a")
            >>> info["type"], info["rows"], info["cols"]
            ('plate', '8', '12')
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
        info: dict[str, str] = {
            "type": "plate",
            "rows": str(location.num_row),
            "cols": str(location.num_col),
        }
        if hasattr(location, "current_row") and hasattr(location, "current_col"):
            info["current_row"] = str(location.current_row)
            info["current_col"] = str(location.current_col)
        return info

    def __repr__(self) -> str:
        """Return string representation of LocationManager.

        Returns:
            String showing number of locations and special plates.

        Example:
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> tipbox_params = PlateParams(
            ...     plate_type="tipbox", well_template=well, num_row=8, num_col=12
            ... )
            >>> manager.set_plate("tipbox_a", tipbox_params)
            >>> waste_params = PlateParams(
            ...     plate_type="waste_container",
            ...     well_template=well,
            ...     num_row=1,
            ...     num_col=1,
            ... )
            >>> manager.set_plate("waste", waste_params)
            >>> repr(manager)
            'LocationManager(locations=2, tipboxes=1, waste=yes)'
        """
        return (
            f"LocationManager("
            f"locations={len(self.locations)}, "
            f"tipboxes={len(self.tipbox_manager.boxes)}, "
            f"waste={'yes' if self.waste_container else 'no'})"
        )
