#!/usr/bin/env python3
"""Location and plate management for the AutoPipette system.

This module handles storage, retrieval, and management of named locations
and plates used in pipetting operations using JSON configuration.
"""

from __future__ import annotations

import copy
import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from tricca_autopipette.core.config_writer import write_json_atomic
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import (
    DefaultFilenames,
    DefaultPaths,
    LocalConfigRoots,
    PlateType,
)
from tricca_autopipette.core.pipette_exceptions import (
    DrawerNotAtStopError,
    NotALocationError,
)
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

if TYPE_CHECKING:
    # Type only: core never imports the daemon at runtime. The value is
    # handed in by `AutoPipetteService` once it has read Klipper (#138).
    from tricca_autopipette.daemon.moonraker_state import AxisConfig

logger = logging.getLogger(__name__)

CONFIG_LOCATIONS = DefaultFilenames.CONFIG_LOCATIONS


@dataclass(frozen=True)
class Drawer:
    """A plate drawer's named stops, from a locations file's ``drawers`` block.

    Issue #142 (addendum D37/D38). Klipper knows no stop names: a stop is
    just a position (mm) along the drawer's travel, named here so protocols
    and deck locations can refer to it.

    Attributes:
        stops: Stop name to position (mm).
        pipetting: The stops at which the tip may descend into the drawer.
        source: The file (or inline source) that defined it.
        raw: Its file entry as written, for `LocationManager.save_to_json`.
    """

    stops: dict[str, float]
    pipetting: tuple[str, ...]
    source: str = field(default="<inline>", compare=False)
    raw: dict[str, Any] = field(default_factory=dict[str, Any], compare=False)


def drawer_problems(name: str, drawer: Drawer, axes: AxisConfig) -> list[str]:
    """Check a drawer's stops against Klipper's plate config (addendum D39).

    Klipper's copy of the tip-safe positions is the safety authority; tapd's
    named stops are validated against it rather than trusted.

    Args:
        name: The drawer's name, which must be one of Klipper's plates.
        drawer: Its stops.
        axes: Klipper's plate config, as discovered (issue #138).

    Returns:
        One message per problem; empty if the drawer is valid.

    Example:
        >>> from tricca_autopipette.daemon.moonraker_state import (
        ...     AxisConfig,
        ...     PlateAxis,
        ... )
        >>> axes = AxisConfig(plates=(PlateAxis("plate1", "U", 0, 350, (0.0,)),))
        >>> drawer_problems("plate1", Drawer({"in": 0.0}, ("in",)), axes)
        []
    """
    plate = next((p for p in axes.plates if p.name == name), None)
    if plate is None:
        if not axes.plates:
            return [
                f"drawer {name!r}: this machine has no plates configured in "
                f"Klipper, so it accepts no 'drawers' block"
            ]
        known = ", ".join(p.name for p in axes.plates)
        return [f"drawer {name!r} is not a plate Klipper knows ({known})"]

    problems: list[str] = []
    lo, hi = plate.position_min, plate.position_max
    tol = axes.park_tol or 0.0
    for stop, mm in drawer.stops.items():
        if (lo is not None and mm < lo) or (hi is not None and mm > hi):
            problems.append(
                f"drawer {name!r}: stop {stop!r} at {mm:g} mm is outside its "
                f"travel ({lo} to {hi} mm)"
            )
    for stop in drawer.pipetting:
        mm = drawer.stops[stop]
        if not any(abs(mm - safe) <= tol for safe in plate.safe_stops):
            safe = ", ".join(f"{s:g}" for s in plate.safe_stops) or "none"
            problems.append(
                f"drawer {name!r}: pipetting stop {stop!r} at {mm:g} mm is not "
                f"within {tol:g} mm of a tip-safe position in Klipper ({safe})"
            )
    return problems


@dataclass
class LocationMembershipSnapshot:
    """Which locations/tipboxes are registered, for full deck-membership rollback.

    Companion to `snapshot_cursors`/`TipBoxManager.snapshot`, which capture
    *internal* per-object state (cursor position, tip presence) but assume
    the same objects are still registered under the same names --
    `del_loc`/`clear_locs`/`load_locations`/`unload_locations` change *which*
    objects exist at all, which neither of those covers. Used by
    `daemon/service.py`'s `domain_state_snapshot` so a compile-time failure
    or dry-run validation can undo membership changes too, not just mutate
    the objects that happen to still be there afterward.

    Shallow copies only: the same `Coordinate`/`Plate`/`TipBox` objects are
    kept, not cloned, so restoring membership plus the existing per-object
    cursor/presence restore compose correctly (an object present both before
    and after a run has its own internal state independently reset).
    """

    locations: dict[str, Coordinate | Plate]
    waste_container: WasteContainer | None
    sources: dict[str, str]
    tipboxes: dict[str, TipBox]
    drawers: dict[str, Drawer] = field(default_factory=dict[str, Drawer])
    drawer_links: dict[str, tuple[str, str]] = field(
        default_factory=dict[str, tuple[str, str]]
    )


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
        drawers: Named drawer stops, by drawer (plate) name (issue #142).
        drawer_links: Location name to the ``(drawer, stop)`` it is tied to.
        drawer_positions: The compile-time drawer-position model: drawer
            name to where it is (mm), as far as tapd knows. A drawer missing
            here is at an unknown position.
        axis_config: Klipper's plate config once tapd has read it, or None
            before the first connection.

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
        # name -> (object it was loaded as, its raw file entry), so
        # `save_to_json` writes a loaded location back exactly as it was
        # written (template references, unknown keys and all) instead of
        # reconstructing it from the parsed object. Keyed on object identity:
        # once a name is re-set interactively the stored entry no longer
        # matches and is ignored, so no other method has to maintain this.
        self._raw_entries: dict[str, tuple[Coordinate | Plate, dict[str, Any]]] = {}
        self.drawers: dict[str, Drawer] = {}
        self.drawer_links: dict[str, tuple[str, str]] = {}
        self.drawer_positions: dict[str, float] = {}
        self.axis_config: AxisConfig | None = None

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
        self.drawers.clear()
        self.drawer_links.clear()

    def set_axis_config(self, axes: AxisConfig) -> list[str]:
        """Record Klipper's plate config and re-check the loaded drawers.

        Called on connect (issue #142): drawers loaded before tapd could read
        Klipper were kept unchecked. From now on a load with a bad drawer is
        refused outright; an already-loaded bad drawer stays loaded (so a save
        still round-trips) but no location linked to it can be used.

        Args:
            axes: Klipper's plate config (issue #138).

        Returns:
            One message per problem with a loaded drawer; empty if all pass.
        """
        self.axis_config = axes
        return [
            problem
            for name, drawer in self.drawers.items()
            for problem in drawer_problems(name, drawer, axes)
        ]

    def seed_drawer_positions(self, positions: Mapping[str, float]) -> None:
        """Replace the drawer-position model with live positions.

        Called at the start of a protocol or command; a drawer missing from
        `positions` becomes unknown.

        Args:
            positions: Drawer name to its live position (mm).
        """
        self.drawer_positions = dict(positions)

    def set_drawer_position(self, drawer: str, position: float) -> None:
        """Record where a compiled drawer move leaves a drawer.

        The update a ``plate_move``/``plates_in``/plate ``home`` line makes
        (TAP-4/TAP-5), so later lines in the same batch see the drawer there.

        Args:
            drawer: Drawer (plate) name.
            position: Its position after the move (mm).
        """
        self.drawer_positions[drawer] = float(position)

    def check_drawer(self, name: str) -> None:
        """Refuse a drawer-linked location unless its drawer is at its stop.

        tapd's early refusal (issue #142, addendum D40); Klipper's interlock
        stays the authority. A location with no link passes.

        Args:
            name: Location name.

        Raises:
            DrawerNotAtStopError: If the location is linked and its drawer is
                undefined, rejected by Klipper's config, at an unknown
                position, or not within ``park_tol`` of the linked stop.
        """
        link = self.drawer_links.get(name)
        if link is None:
            return
        drawer_name, stop = link
        drawer = self.drawers.get(drawer_name)
        if drawer is None:
            raise DrawerNotAtStopError(name, drawer_name, stop, "not defined")
        if self.axis_config is not None:
            problems = drawer_problems(drawer_name, drawer, self.axis_config)
            if problems:
                raise DrawerNotAtStopError(
                    name, drawer_name, stop, f"misconfigured ({'; '.join(problems)})"
                )
        required = drawer.stops.get(stop)
        if required is None:
            raise DrawerNotAtStopError(name, drawer_name, stop, "without that stop")
        actual = self.drawer_positions.get(drawer_name)
        if actual is None:
            raise DrawerNotAtStopError(
                name, drawer_name, stop, "at an unknown position"
            )
        tol = (self.axis_config.park_tol if self.axis_config else None) or 0.0
        if abs(actual - required) > tol:
            raise DrawerNotAtStopError(name, drawer_name, stop, f"at {actual:g} mm")

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
        # A location re-set by hand is a new location: no drawer link.
        self.drawer_links.pop(name, None)

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
            DrawerNotAtStopError: If the location is linked to a drawer stop
                and the drawer isn't there (see `check_drawer`).
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
        """  # ruff: ignore[docstring-extraneous-exception]
        if name not in self.locations:
            raise NotALocationError(name)
        self.check_drawer(name)

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

    def snapshot_cursors(self) -> dict[str, int]:
        """Capture every plate's traversal cursor (`Plate.curr`).

        Companion to `TipBoxManager.snapshot`, which captures per-position tip
        *presence* but not the traversal cursor -- a sample plate has no
        presence map at all, so its cursor is the only progress a run can
        leave behind. Used by `daemon/service.py`'s `domain_state_snapshot`
        to roll a compile-time protocol failure back to a pristine deck.

        Returns:
            Mapping of plate name to its current `curr` value. Only plates
            (including tipboxes) are included; plain coordinates have no
            cursor.

        Example:
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="array", well_template=well, num_row=1, num_col=4
            ... )
            >>> manager.set_plate("plate_a", params)
            >>> manager.snapshot_cursors()
            {'plate_a': 0}
        """
        return {
            name: location.curr
            for name, location in self.locations.items()
            if isinstance(location, Plate)
        }

    def restore_cursors(self, cursors: dict[str, int]) -> list[str]:
        """Reapply a `snapshot_cursors` mapping to the live plates.

        Args:
            cursors: A mapping previously produced by `snapshot_cursors`.
                Entries naming a plate that is no longer registered (e.g.
                unloaded mid-run) are ignored rather than raising -- there is
                nothing left to restore it onto.

        Returns:
            Names of plates whose stored cursor no longer fits the live
            plate's traversal sequence (e.g. reloaded with fewer wells since
            the snapshot was taken) and were therefore left untouched.
            Callers should surface this -- the restored cursor is stale.

        Example:
            >>> manager = LocationManager()
            >>> well = Well(coor=Coordinate(x=10, y=10, z=5), dip_top=10.0)
            >>> params = PlateParams(
            ...     plate_type="array", well_template=well, num_row=1, num_col=4
            ... )
            >>> manager.set_plate("plate_a", params)
            >>> manager.get_coordinate("plate_a")  # doctest: +ELLIPSIS
            Coordinate(...)
            >>> manager.restore_cursors({"plate_a": 0})
            []
            >>> manager.locations["plate_a"].curr
            0
        """
        skipped: list[str] = []
        for name, curr in cursors.items():
            location = self.locations.get(name)
            if not isinstance(location, Plate):
                continue
            if not 0 <= curr <= len(location.sequence):
                logger.warning(
                    "Plate %r's traversal sequence changed (stored cursor %d "
                    "no longer fits its %d positions); cursor left as-is",
                    name,
                    curr,
                    len(location.sequence),
                )
                skipped.append(name)
                continue
            location.curr = curr
        return skipped

    def snapshot_membership(self) -> LocationMembershipSnapshot:
        """Capture exactly which locations/tipboxes are registered.

        Companion to `snapshot_cursors`/`TipBoxManager.snapshot` -- see
        `LocationMembershipSnapshot`'s docstring for why membership needs
        its own snapshot separate from per-object internal state.

        Returns:
            A snapshot suitable for `restore_membership`.

        Example:
            >>> manager = LocationManager()
            >>> manager.set_coordinate("bench", Coordinate(x=1, y=1, z=1))
            >>> snapshot = manager.snapshot_membership()
            >>> manager.remove_location("bench")
            >>> manager.restore_membership(snapshot)
            >>> manager.has_location("bench")
            True
        """
        return LocationMembershipSnapshot(
            locations=dict(self.locations),
            waste_container=self.waste_container,
            sources=dict(self._sources),
            tipboxes=dict(self.tipbox_manager.boxes),
            drawers=dict(self.drawers),
            drawer_links=dict(self.drawer_links),
        )

    def restore_membership(self, snapshot: LocationMembershipSnapshot) -> None:
        """Reapply a `snapshot_membership` snapshot, undoing any add/remove.

        Restores the exact set of registered locations/tipboxes and which
        objects they map to -- a location added after the snapshot is
        dropped, one removed is brought back (as the same object, so its own
        internal state -- e.g. tip presence -- reflects whatever it held at
        snapshot time, not a freshly-reset default). Callers that also want
        an object's *internal* state restored (cursor, tip presence) should
        call `restore_cursors`/`TipBoxManager.restore` afterward -- this only
        fixes which objects exist, not their contents.

        Args:
            snapshot: A snapshot previously produced by `snapshot_membership`.

        Example:
            >>> manager = LocationManager()
            >>> manager.set_coordinate("bench", Coordinate(x=1, y=1, z=1))
            >>> snapshot = manager.snapshot_membership()
            >>> manager.set_coordinate("extra", Coordinate(x=2, y=2, z=2))
            >>> manager.restore_membership(snapshot)
            >>> manager.has_location("extra")
            False
        """
        self.locations = dict(snapshot.locations)
        self.waste_container = snapshot.waste_container
        self._sources = dict(snapshot.sources)
        self.tipbox_manager.boxes = dict(snapshot.tipboxes)
        self.drawers = dict(snapshot.drawers)
        self.drawer_links = dict(snapshot.drawer_links)

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
        self.drawer_links.pop(name, None)

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

    def loaded_files(self) -> list[str]:
        """List the locations files the deck currently holds entries from.

        Returns:
            Distinct source filenames, in first-seen order. Inline system-config
            payloads (``<inline ...>`` sources) are not files and are excluded.
        """
        return list(
            dict.fromkeys(s for s in self._sources.values() if not s.startswith("<"))
        )

    def reload_source(self, filename: str) -> bool:
        """Re-read a loaded locations file so its edits take effect (issue #33).

        Only the names the deck currently takes from `filename` are replaced,
        plus names the file newly adds; a name another file overrode is left
        alone. Names the file no longer lists are unloaded. Parse-then-apply:
        a bad file leaves the deck untouched.

        Args:
            filename: A locations file name, as passed to `load_from_json`.

        Returns:
            True if the file was loaded (and so reloaded), False if the deck
            holds nothing from it.

        Raises:
            FileNotFoundError: If the file no longer exists.
            ValueError: If the file is invalid.

        Example:
            >>> LocationManager().reload_source("deck.json")
            False
        """  # ruff: ignore[docstring-extraneous-exception]
        live = {name for name, src in self._sources.items() if src == filename}
        live_drawers = {n for n, d in self.drawers.items() if d.source == filename}
        if not live and not live_drawers:
            return False
        data = self._read_locations_file(filename)
        entries: dict[str, Any] = {
            key: [
                entry
                for entry in cast("list[dict[str, Any]]", data.get(key, []))
                if entry.get("name") in live or entry.get("name") not in self.locations
            ]
            for key in ("coordinates", "plates")
        }
        drawers: Any = data.get("drawers", {})
        if isinstance(drawers, dict):  # else left for apply to reject
            drawers = {
                name: entry
                for name, entry in cast("dict[str, Any]", drawers).items()
                if name in live_drawers or name not in self.drawers
            }
        entries["drawers"] = drawers
        self.apply_locations_data(entries, source=filename)
        listed = {
            entry.get("name")
            for key in ("coordinates", "plates")
            for entry in entries[key]
        }
        for name in live - listed:
            self.unload(name)
        for name in live_drawers - set(drawers):
            del self.drawers[name]
        return True

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
        """
        coordinates = self._parse_coordinates(locations_data, source)
        plates = self._parse_plates(locations_data, source)
        drawers = self._parse_drawers(locations_data, source)
        links = self._parse_links(locations_data, source)
        if self.axis_config is not None:
            for drawer_name, drawer in drawers.items():
                problems = drawer_problems(drawer_name, drawer, self.axis_config)
                if problems:
                    raise ValueError(f"In {source}: {'; '.join(problems)}")
        # Every link as it would stand after this load, checked against the
        # drawers as they would stand: a redefined drawer must still carry
        # every stop an earlier file's location relies on.
        incoming = {name for name, _ in coordinates} | {p[0] for p in plates}
        kept = {
            name: link
            for name, link in ({} if replace else self.drawer_links).items()
            if name not in incoming
        }
        self._check_links(
            {**kept, **links}, {**({} if replace else self.drawers), **drawers}
        )

        # Nothing above mutates state, so a failure here leaves the deck as it
        # was. Only past this point do we commit.
        if replace:
            self.clear()

        for drawer_name, drawer in drawers.items():
            previous = self.drawers.get(drawer_name)
            if previous is not None and previous.source != source:
                logger.warning(
                    "Drawer %r from %s overwrites the one from %s",
                    drawer_name,
                    source,
                    previous.source,
                )
            self.drawers[drawer_name] = drawer

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

        # After set_coordinate/set_plate, which drop any earlier link.
        self.drawer_links.update(links)

        for key in ("coordinates", "plates"):
            for entry in cast("list[dict[str, Any]]", locations_data.get(key, [])):
                name = entry["name"]
                self._raw_entries[name] = (self.locations[name], copy.deepcopy(entry))

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
        # Re-applying a file over itself (reload_source) replaces nothing.
        if name not in self.locations or self._sources.get(name) == source:
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
        # Several entries commonly share one template (e.g. identical
        # tipboxes) -- cache each file's parse for the rest of this call so
        # it's read once, not once per referencing entry. Scoped to this one
        # call (not persisted on self) since a template edited between two
        # separate load_from_json calls should be picked up fresh.
        plate_def_cache: dict[Path, dict[str, Any]] = {}

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
                if plate_file_path not in plate_def_cache:
                    plate_def_cache[plate_file_path] = self._load_plate_definition(
                        plate_file_path
                    )
                # Copied so the .update() below (per-entry overrides) can't
                # mutate the cached template out from under the next entry
                # that references the same file.
                plate_def = dict(plate_def_cache[plate_file_path])
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
    def _parse_drawers(
        locations_data: dict[str, Any], source: str
    ) -> dict[str, Drawer]:
        """Build a payload's ``drawers`` block without applying it.

        Args:
            locations_data: The locations payload.
            source: Origin, for error messages and `Drawer.source`.

        Returns:
            Drawer name to `Drawer`, in file order.

        Raises:
            ValueError: If the block, a drawer, a stop position or the
                ``pipetting`` list is malformed, or ``pipetting`` names a
                stop the drawer doesn't have.
        """
        block: Any = locations_data.get("drawers", {})
        if not isinstance(block, dict):
            raise ValueError(f"'drawers' must be an object in {source}")
        parsed: dict[str, Drawer] = {}
        for name, entry in cast("dict[str, Any]", block).items():
            where = f"drawer {name!r} in {source}"
            raw_stops: Any = (
                cast("dict[str, Any]", entry).get("stops")
                if isinstance(entry, dict)
                else None
            )
            if not isinstance(raw_stops, dict):
                raise ValueError(f"{where} needs a 'stops' object")
            stops: dict[str, float] = {}
            for stop, mm in cast("dict[str, Any]", raw_stops).items():
                if (
                    isinstance(mm, bool)
                    or not isinstance(mm, int | float)
                    or not math.isfinite(mm)
                ):
                    raise ValueError(f"{where}: stop {stop!r} must be a number (mm)")
                stops[stop] = float(mm)
            pipetting: Any = cast("dict[str, Any]", entry).get("pipetting", [])
            if not isinstance(pipetting, list):
                raise ValueError(f"{where}: 'pipetting' must be a list of stops")
            for stop in cast("list[Any]", pipetting):
                if stop not in stops:
                    raise ValueError(
                        f"{where}: pipetting stop {stop!r} is not one of its stops"
                    )
            parsed[name] = Drawer(
                stops=stops,
                pipetting=tuple(cast("list[str]", pipetting)),
                source=source,
                raw=copy.deepcopy(cast("dict[str, Any]", entry)),
            )
        return parsed

    @staticmethod
    def _parse_links(
        locations_data: dict[str, Any], source: str
    ) -> dict[str, tuple[str, str]]:
        """Collect the ``drawer``/``stop`` links on a payload's entries.

        Args:
            locations_data: The locations payload.
            source: Origin, for error messages.

        Returns:
            Location name to ``(drawer, stop)``, for linked entries only.

        Raises:
            ValueError: If an entry carries only one of ``drawer``/``stop``,
                or either isn't a string.
        """
        links: dict[str, tuple[str, str]] = {}
        for key in ("coordinates", "plates"):
            for entry in cast("list[dict[str, Any]]", locations_data.get(key, [])):
                drawer, stop = entry.get("drawer"), entry.get("stop")
                if drawer is None and stop is None:
                    continue
                if not isinstance(drawer, str) or not isinstance(stop, str):
                    raise ValueError(
                        f"Location {entry.get('name')!r} in {source} needs both "
                        f"'drawer' and 'stop' (as names), or neither"
                    )
                links[entry["name"]] = (drawer, stop)
        return links

    @staticmethod
    def _check_links(
        links: Mapping[str, tuple[str, str]], drawers: Mapping[str, Drawer]
    ) -> None:
        """Check every link against the drawer it names.

        A link to a drawer no file has defined (yet) is allowed, since a deck
        may load its drawers from another file, and is logged; pipetting at
        such a location is refused until the drawer exists.

        Args:
            links: Location name to ``(drawer, stop)``.
            drawers: The drawers to check them against.

        Raises:
            ValueError: If a link names a stop its drawer doesn't define, or
                one that isn't a pipetting stop.
        """
        for name, (drawer_name, stop) in links.items():
            drawer = drawers.get(drawer_name)
            if drawer is None:
                logger.warning(
                    "Location %r is linked to drawer %r, which no loaded file "
                    "defines; it can't be used until one does",
                    name,
                    drawer_name,
                )
            elif stop not in drawer.stops:
                raise ValueError(
                    f"Location {name!r} is linked to stop {stop!r}, which drawer "
                    f"{drawer_name!r} doesn't define"
                )
            elif stop not in drawer.pipetting:
                raise ValueError(
                    f"Location {name!r} is linked to stop {stop!r}, but {stop!r} "
                    f"is not a pipetting stop of drawer {drawer_name!r}"
                )

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
        """Save the whole deck to a locations JSON file, atomically.

        Saves to `self.locations_dir / filename` if an explicit directory was
        injected, else to `DefaultPaths.DIR_LOCAL_LOCATIONS` -- a save never
        writes into the shared repo at runtime.

        A location loaded from a file is written back as its raw file entry
        (``plate_file`` references, unknown keys and all), so loading a file
        and saving it reproduces it. Only a location created or replaced
        interactively (``coor``/``plate``) is serialized from its object.
        Either way a tipbox's ``tips`` block reflects its *current* consumed
        state. The write goes through `config_writer.write_json_atomic`.

        Args:
            filename: Name of output JSON file. Defaults to
                     'custom_locations.json'.

        Raises:
            ValueError: If `filename` is not a bare filename.

        Example:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     manager = LocationManager(Path(tmp))
            ...     manager.set_coordinate("home", Coordinate(x=0, y=0, z=0))
            ...     manager.save_to_json("backup_locations.json")
            ...     (Path(tmp) / "backup_locations.json").exists()
            True
        """
        if Path(filename).name != filename:
            raise ValueError(f"Expected a bare filename, got {filename!r}")
        locations_dir = self.locations_dir or DefaultPaths.DIR_LOCAL_LOCATIONS

        data: dict[str, Any] = {}
        if self.drawers:
            data["drawers"] = {
                name: copy.deepcopy(drawer.raw) for name, drawer in self.drawers.items()
            }
        for name, location in self.locations.items():
            raw = self._raw_entries.get(name)
            entry: dict[str, Any]
            if raw is not None and raw[0] is location:
                entry = copy.deepcopy(raw[1])
            elif isinstance(location, Coordinate):
                entry = {"name": name, "x": location.x, "y": location.y}
                entry["z"] = location.z
            else:
                entry = self._serialize_plate(name, location)
            if isinstance(location, TipBox):
                self._overlay_tip_state(location, entry)
            key = "coordinates" if isinstance(location, Coordinate) else "plates"
            data.setdefault(key, []).append(entry)

        write_json_atomic(locations_dir / filename, data)
        logger.info(f"Saved {len(self.locations)} location(s) to {filename}")

    @staticmethod
    def _serialize_plate(name: str, plate: Plate) -> dict[str, Any]:
        """Serialize an interactively-created plate (no raw entry to reuse).

        Omits traversal/mask/exhaust fields left at their defaults, so the
        output stays minimal.

        Args:
            name: The plate's location name.
            plate: The plate to serialize.

        Returns:
            A locations-file plate entry.
        """
        first = plate.wells[0] if plate.wells else None
        entry: dict[str, Any] = {
            "name": name,
            "type": PlateFactory.type_name_for(plate),
            "x": first.coor.x if first else 0,
            "y": first.coor.y if first else 0,
            "z": first.coor.z if first else 0,
            "num_row": plate.num_row,
            "num_col": plate.num_col,
            "spacing_row": plate.spacing_row,
            "spacing_col": plate.spacing_col,
        }
        if first is not None:
            entry["dip_top"] = first.dip_top
            if first.dip_btm is not None:
                entry["dip_btm"] = first.dip_btm
            entry["dip_func"] = first.strategy_type.value
            if first.well_diameter is not None:
                entry["well_diameter"] = first.well_diameter

        # A plate written with a preset name saves back as that name; an
        # unnamed combination falls back to the explicit descriptor.
        preset = TraversalRegistry.name_for(plate.order)
        if preset is None:
            entry["order"] = plate.order.model_dump(mode="json")
        elif preset != "row_major":
            entry["order"] = preset
        if plate.mask is not None and not plate.mask.is_noop():
            entry["mask"] = plate.mask.model_dump(mode="json", exclude_none=True)
        # TipBox forces "error" itself, so writing it back would only add noise.
        if not isinstance(plate, TipBox) and plate.on_exhaust != "wrap":
            entry["on_exhaust"] = plate.on_exhaust
        return entry

    @staticmethod
    def _overlay_tip_state(box: TipBox, entry: dict[str, Any]) -> None:
        """Write a tipbox's current consumed map into its entry's ``tips`` block.

        Args:
            box: The tipbox.
            entry: Its locations-file entry, modified in place.
        """
        consumed = compress_to_ranges(box.consumed_indices(), box.num_col)
        if consumed:
            entry["tips"] = {"consumed": consumed}
        else:
            entry.pop("tips", None)

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
