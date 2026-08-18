#!/usr/bin/env python3
"""Constants and enumerations for the AutoPipette system.

This module defines all constant values, magic numbers, and enumerations
used throughout the pipette control system.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

__all__ = [
    "ConfigKey",
    "CoordinateSystem",
    "DefaultFilenames",
    "DefaultPaths",
    "GCodeCommand",
    "HomingTargets",
    "LocalConfigRoots",
    "PhysicalConstants",
    "PlateType",
    "TriggerChannels",
]


class CoordinateSystem(StrEnum):
    """Coordinate system modes for motion commands.

    Attributes:
        ABSOLUTE: Coordinates are absolute positions (G90).
        RELATIVE: Coordinates are offsets from current position (G91).

    Example:
        >>> mode = CoordinateSystem.ABSOLUTE
        >>> mode.value
        'absolute'
    """

    ABSOLUTE = "absolute"
    RELATIVE = "relative"


class PlateType(StrEnum):
    """Special plate type identifiers.

    These types receive special handling during configuration.

    Attributes:
        WASTE_CONTAINER: Waste disposal location for used tips.
        TIPBOX: Tip storage for automatic tip pickup.
        ARRAY: Standard well plate or array.
    """

    WASTE_CONTAINER = "waste_container"
    TIPBOX = "tipbox"
    ARRAY = "array"


class GCodeCommand:
    """G-code command constants.

    Standard G-code commands used for pipette control.

    Example:
        >>> from tricca_autopipette.core.pipette_constants import GCodeCommand
        >>> home_cmd = GCodeCommand.HOME_ALL
        >>> home_cmd
        'G28'
    """

    # Coordinate systems
    ABSOLUTE_MODE = "G90"
    RELATIVE_MODE = "G91"

    # Homing
    HOME_ALL = "G28"
    HOME_X = "G28 X"
    HOME_Y = "G28 Y"
    HOME_Z = "G28 Z"

    # Movement
    LINEAR_MOVE = "G1"

    # Timing
    DWELL = "G4"

    # Display
    DISPLAY_MESSAGE = "M117"

    # Speed control
    SPEED_FACTOR = "M220"


class PhysicalConstants:
    """Physical measurement constants.

    Default values for movements and tolerances.

    Attributes:
        WIGGLE_OFFSET_MM: Offset for wiggle motion in millimeters.
        VOLUME_TOLERANCE_UL: Minimum significant volume in microliters.
    """

    WIGGLE_OFFSET_MM = 1.0  # Offset for wiggle motion in millimeters
    VOLUME_TOLERANCE_UL = 1e-6  # Minimum significant volume in microliters


class HomingTargets:
    """Motor-name lookup tables for the ``home``/``init`` commands.

    Shared between ``commands/movement_commands.py`` (the cmd2 adapter) and
    ``daemon/service.py`` (``AutoPipetteService.home``/``init``, the
    business-logic owner) so both stay in sync without either importing
    from the other.

    Attributes:
        MOTOR_METHODS: Maps motor name to (output filename, ``AutoPipette``
            method name) for motors that map directly to a single method.
        MOTOR_SPECIAL: Motor names that don't map to a single method --
            ``"all"`` delegates to ``AutoPipette.init_pipette()`` instead.
        VALID_MOTORS: Combined set of all valid motor names, kept in sync
            with ``MOTOR_METHODS``/``MOTOR_SPECIAL`` manually.
    """

    MOTOR_METHODS: ClassVar[dict[str, tuple[str, str]]] = {
        "x": ("home_x.gcode", "home_x"),
        "y": ("home_y.gcode", "home_y"),
        "z": ("home_z.gcode", "home_z"),
        "pipette": ("home_pipette.gcode", "home_pipette_motors"),
        "axis": ("home_axis.gcode", "home_axis"),
        "servo": ("home_servo.gcode", "home_servo"),
    }

    MOTOR_SPECIAL: ClassVar[dict[str, str]] = {
        "all": "home_all.gcode",
    }

    VALID_MOTORS: frozenset[str] = frozenset({
        "x",
        "y",
        "z",
        "pipette",
        "axis",
        "servo",
        "all",
    })


class TriggerChannels:
    """Valid channel/state names for the (not-yet-implemented) ``trigger`` command.

    Shared between ``commands/utility_commands.py`` (the cmd2 adapter) and
    ``daemon/service.py`` (``AutoPipetteService.trigger``) for the same
    reason as :class:`HomingTargets`.
    """

    VALID_CHANNELS: frozenset[str] = frozenset({"air", "shake", "aux"})
    VALID_STATES: frozenset[str] = frozenset({"on", "off"})


class DefaultFilenames:
    """Default filenames for configuration files.

    These are the default names for configuration files if not specified
    by the user.

    Attributes:
        CONFIG_SYSTEM: Default system configuration filename.
        CONFIG_GANTRY: Default gantry configuration filename.
        CONFIG_PIPETTE: Default pipette configuration filename.
        CONFIG_LOCATIONS: Default locations configuration filename.
        CONFIG_LIQUIDS: Default liquids configuration filename.
    """

    CONFIG_SYSTEM = "default_system.json"
    CONFIG_GANTRY = "default_gantry.json"
    CONFIG_PIPETTE = "default_pipette.json"
    CONFIG_LOCATIONS = "default_locations.json"
    CONFIG_LIQUIDS = "default_liquids.json"


class DefaultPaths:
    """Default file paths for configuration and data.

    Attributes:
        CONFIG_DIR: Directory containing configuration files.
        DEFAULT_CONFIG: Default configuration filename.
    """

    # Four levels up: core -> tricca_autopipette -> src -> repo root. Only
    # correct when running from a src-layout checkout; installed packages
    # (Nix, pip, wheel) drop the "src" segment, so this lands one directory
    # too high with no config/protocols/gcode underneath it. Override with
    # AUTOPIPETTE_REPO_ROOT wherever the package is actually installed.
    #
    # An empty override is treated as unset, and a relative one is rejected
    # outright: systemd starts services with cwd=/ and neither shipped unit
    # sets WorkingDirectory, so "Environment=AUTOPIPETTE_REPO_ROOT=" or a
    # relative value would otherwise resolve config/ against / and surface
    # as a FileNotFoundError far from the actual mistake.
    _REPO_ROOT_OVERRIDE = os.environ.get("AUTOPIPETTE_REPO_ROOT", "").strip()
    if _REPO_ROOT_OVERRIDE and not Path(_REPO_ROOT_OVERRIDE).expanduser().is_absolute():
        raise ValueError(
            f"AUTOPIPETTE_REPO_ROOT must be an absolute path, got "
            f"{_REPO_ROOT_OVERRIDE!r}. It is the directory containing config/, "
            f"protocols/ and gcode/; see systemd/README.md."
        )
    DIR_REPO_ROOT: Path = (
        Path(_REPO_ROOT_OVERRIDE).expanduser()
        if _REPO_ROOT_OVERRIDE
        else Path(__file__).parents[3]
    )

    DIR_SHELL: Path = Path(__file__).parent
    DIR_GCODE: Path = DIR_REPO_ROOT / "gcode"
    DIR_PROTOCOL: Path = DIR_REPO_ROOT / "protocols"
    DIR_CONFIG: Path = DIR_REPO_ROOT / "config/"
    DIR_CONFIG_SYSTEM: Path = DIR_CONFIG / "system/"
    DIR_CONFIG_GANTRY: Path = DIR_CONFIG / "gantry/"
    DIR_CONFIG_PIPETTE: Path = DIR_CONFIG / "pipettes/"
    DIR_CONFIG_LOCATIONS: Path = DIR_CONFIG / "locations/"
    DIR_CONFIG_LIQUIDS: Path = DIR_CONFIG / "liquids/"
    DIR_CONFIG_PLATES: Path = DIR_CONFIG / "plates/"

    # Per-machine local config root (issue #68). Real per-rig data -- a
    # machine's hostname, its deck layout, its own protocols -- has no
    # business living in the shared code repo above; this is a second root,
    # outside DIR_REPO_ROOT entirely, that the operator manages as its own
    # git repo by hand. tapd/tap never shell out to git for it.
    #
    # Same override/validation shape as AUTOPIPETTE_REPO_ROOT above: empty is
    # treated as unset, and a relative value is rejected outright rather than
    # silently resolved against a systemd unit's cwd=/.
    _LOCAL_DIR_OVERRIDE = os.environ.get("AUTOPIPETTE_LOCAL_DIR", "").strip()
    if _LOCAL_DIR_OVERRIDE and not Path(_LOCAL_DIR_OVERRIDE).expanduser().is_absolute():
        raise ValueError(
            f"AUTOPIPETTE_LOCAL_DIR must be an absolute path, got "
            f"{_LOCAL_DIR_OVERRIDE!r}. It is the per-machine local config "
            f"root; see config/README.md."
        )
    _XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", "").strip()
    _XDG_BASE: Path = (
        Path(_XDG_CONFIG_HOME).expanduser()
        if _XDG_CONFIG_HOME
        else Path.home() / ".config"
    )
    DIR_LOCAL_ROOT: Path = (
        Path(_LOCAL_DIR_OVERRIDE).expanduser()
        if _LOCAL_DIR_OVERRIDE
        else _XDG_BASE / "tricca-autopipette"
    )

    # Mirror the shared categories directly as children -- no redundant
    # "config/" segment, since this root holds nothing else.
    DIR_LOCAL_SYSTEM: Path = DIR_LOCAL_ROOT / "system"
    DIR_LOCAL_GANTRY: Path = DIR_LOCAL_ROOT / "gantry"
    DIR_LOCAL_PIPETTE: Path = DIR_LOCAL_ROOT / "pipettes"
    DIR_LOCAL_LIQUIDS: Path = DIR_LOCAL_ROOT / "liquids"
    DIR_LOCAL_LOCATIONS: Path = DIR_LOCAL_ROOT / "locations"
    DIR_LOCAL_PLATES: Path = DIR_LOCAL_ROOT / "plates"
    DIR_LOCAL_PROTOCOL: Path = DIR_LOCAL_ROOT / "protocols"


class LocalConfigRoots:
    """Resolves per-machine local config against the shared repo (issue #68).

    Two merge mechanisms, by category shape:

    - **Union categories** (``gantry``, ``pipettes``, ``liquids``,
      ``locations``, ``plates``, ``protocols``): the union of shared and
      local. The same filename in both roots means local wins; a filename in
      only one root is included as-is. `resolve` picks one named file this
      way; `list_files` returns the whole union.
    - **``system``**: not a union at all -- pick exactly one active file, and
      it comes from the local root only. The shared repo's
      ``config/system/default_system.json`` is a copy-from template, never
      consulted live once a local file exists. `list_system_configs` and the
      ``active.json`` symlink helpers below implement that side; the
      surrounding startup lifecycle (bootstrap-copy, the ambiguous-choice
      prompt, the no-TTY hard fail) lives in ``daemon/main.py``, since it
      needs to prompt/exit the process, not just resolve a path.

    Example:
        >>> LocalConfigRoots.roots("liquids") == (
        ...     DefaultPaths.DIR_CONFIG_LIQUIDS,
        ...     DefaultPaths.DIR_LOCAL_LIQUIDS,
        ... )
        True
    """

    #: Registered union-category names -- `roots` and `list_files` accept any
    #: of these.
    CATEGORY_NAMES: ClassVar[frozenset[str]] = frozenset({
        "gantry",
        "pipettes",
        "liquids",
        "locations",
        "plates",
        "protocols",
    })

    #: Name of the symlink tracking which local system config is active --
    #: human-inspectable/settable with plain `ls -l`/`ln -sf`, not a state
    #: file. Excluded from `list_system_configs`, since it names a config
    #: rather than being one.
    ACTIVE_SYSTEM_LINK: ClassVar[str] = "active.json"

    @classmethod
    def roots(cls, category: str) -> tuple[Path, Path]:
        """Look up a union category's (shared dir, local dir) pair.

        Read from `DefaultPaths` on every call, rather than captured once at
        class-definition time, so a test's ``monkeypatch.setattr(DefaultPaths,
        "DIR_CONFIG_...", ...)`` is actually seen by `resolve`/`list_files`.

        Args:
            category: One of `CATEGORY_NAMES`.

        Returns:
            The ``(shared_dir, local_dir)`` pair for that category.

        Raises:
            KeyError: If `category` isn't a registered union category.

        Example:
            >>> LocalConfigRoots.roots("plates") == (
            ...     DefaultPaths.DIR_CONFIG_PLATES,
            ...     DefaultPaths.DIR_LOCAL_PLATES,
            ... )
            True
        """
        if category not in cls.CATEGORY_NAMES:
            raise KeyError(
                f"Unknown config category {category!r}; expected one of "
                f"{sorted(cls.CATEGORY_NAMES)}"
            )
        return {
            "gantry": (DefaultPaths.DIR_CONFIG_GANTRY, DefaultPaths.DIR_LOCAL_GANTRY),
            "pipettes": (
                DefaultPaths.DIR_CONFIG_PIPETTE,
                DefaultPaths.DIR_LOCAL_PIPETTE,
            ),
            "liquids": (
                DefaultPaths.DIR_CONFIG_LIQUIDS,
                DefaultPaths.DIR_LOCAL_LIQUIDS,
            ),
            "locations": (
                DefaultPaths.DIR_CONFIG_LOCATIONS,
                DefaultPaths.DIR_LOCAL_LOCATIONS,
            ),
            "plates": (DefaultPaths.DIR_CONFIG_PLATES, DefaultPaths.DIR_LOCAL_PLATES),
            "protocols": (DefaultPaths.DIR_PROTOCOL, DefaultPaths.DIR_LOCAL_PROTOCOL),
        }[category]

    @classmethod
    def resolve(cls, category: str, filename: str) -> Path:
        """Resolve one file in a union category: local wins over shared.

        Args:
            category: One of `CATEGORY_NAMES`.
            filename: Filename to look for in either root.

        Returns:
            The local path if it exists, else the shared path.

        Raises:
            FileNotFoundError: If `filename` exists in neither root.

        Example:
            >>> LocalConfigRoots.resolve("liquids", "water.json").name
            'water.json'
        """
        shared_dir, local_dir = cls.roots(category)

        local_path = local_dir / filename
        if local_path.exists():
            return local_path

        shared_path = shared_dir / filename
        if shared_path.exists():
            return shared_path

        raise FileNotFoundError(
            f"{filename!r} not found in {local_dir} or {shared_dir}"
        )

    @classmethod
    def list_files(cls, category: str, pattern: str = "*.json") -> dict[str, Path]:
        """List every file in a union category: the union of shared and local.

        Args:
            category: One of `CATEGORY_NAMES`.
            pattern: Glob pattern to match within each root.

        Returns:
            Mapping of filename to resolved path. A filename present in both
            roots resolves to the local one; a missing root is treated as
            empty rather than raising.

        Example:
            >>> "water.json" in LocalConfigRoots.list_files("liquids")
            True
        """
        shared_dir, local_dir = cls.roots(category)

        found: dict[str, Path] = {}
        if shared_dir.exists():
            for path in sorted(shared_dir.glob(pattern)):
                found[path.name] = path
        if local_dir.exists():
            for path in sorted(local_dir.glob(pattern)):
                found[path.name] = path  # local overwrites shared on collision

        return found

    @classmethod
    def list_system_configs(cls) -> list[Path]:
        """List local system config profiles.

        ``system/`` is local-only, so unlike `list_files` there is no shared
        side to union in.

        Returns:
            Sorted ``*.json`` files directly in `DefaultPaths.DIR_LOCAL_SYSTEM`,
            excluding `ACTIVE_SYSTEM_LINK` itself. Empty if the directory
            doesn't exist yet.

        Example:
            >>> LocalConfigRoots.list_system_configs()  # doctest: +SKIP
            [PosixPath('.../system/default_system.json')]
        """
        local_dir = DefaultPaths.DIR_LOCAL_SYSTEM
        if not local_dir.exists():
            return []
        return sorted(
            path
            for path in local_dir.glob("*.json")
            if path.name != cls.ACTIVE_SYSTEM_LINK
        )

    @classmethod
    def active_system_link_path(cls) -> Path:
        """Path to the ``active.json`` symlink, whether or not it exists.

        Returns:
            `DefaultPaths.DIR_LOCAL_SYSTEM` / `ACTIVE_SYSTEM_LINK`.
        """
        return DefaultPaths.DIR_LOCAL_SYSTEM / cls.ACTIVE_SYSTEM_LINK

    @classmethod
    def set_active_system(cls, path: Path) -> None:
        """(Re)point ``active.json`` at the given local system config.

        Args:
            path: The chosen system config file, expected to already live in
                `DefaultPaths.DIR_LOCAL_SYSTEM`.

        Example:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as tmp:
            ...     from unittest.mock import patch
            ...     from pathlib import Path
            ...
            ...     local_system = Path(tmp) / "system"
            ...     local_system.mkdir()
            ...     cfg = local_system / "murphy_100.json"
            ...     _ = cfg.write_text("{}")
            ...     with patch.object(DefaultPaths, "DIR_LOCAL_SYSTEM", local_system):
            ...         LocalConfigRoots.set_active_system(cfg)
            ...         LocalConfigRoots.active_system_target().name
            'murphy_100.json'
        """
        link = cls.active_system_link_path()
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(path.name)

    @classmethod
    def active_system_target(cls) -> Path | None:
        """Resolve ``active.json`` to the file it currently points at.

        Returns:
            The target path if the symlink exists and points at a real file,
            else None -- covers "never set" and "points at a file that was
            since removed" alike, rather than raising for either.
        """
        link = cls.active_system_link_path()
        if not link.is_symlink():
            return None
        target = link.parent / os.readlink(link)
        return target if target.exists() else None


class ConfigKey:
    """Configuration file key names.

    Organized by section for easy reference. Use these constants
    instead of hardcoding configuration key strings.

    Example:
        >>> from tricca_autopipette.core.pipette_constants import ConfigKey
        >>> speed_key = ConfigKey.Speed.XY
        >>> speed_key
        'SPEED_XY'
    """

    class Network:
        """Network configuration keys."""

        IP = "IP"
        HOSTNAME = "HOSTNAME"

    class Name:
        """Motor name configuration keys."""

        PIPETTE_SERVO = "NAME_PIPETTE_SERVO"
        PIPETTE_STEPPER = "NAME_PIPETTE_STEPPER"

    class Speed:
        """Speed configuration keys."""

        XY = "SPEED_XY"
        Z = "SPEED_Z"
        PIPETTE_DOWN = "SPEED_PIPETTE_DOWN"
        PIPETTE_UP = "SPEED_PIPETTE_UP"
        PIPETTE_UP_SLOW = "SPEED_PIPETTE_UP_SLOW"
        MAX = "SPEED_MAX"
        FACTOR = "SPEED_FACTOR"
        VELOCITY_MAX = "VELOCITY_MAX"
        ACCEL_MAX = "ACCEL_MAX"

    class Servo:
        """Servo configuration keys."""

        ANGLE_RETRACT = "SERVO_ANGLE_RETRACT"
        ANGLE_EJECT = "SERVO_ANGLE_EJECT"

    class Wait:
        """Timing configuration keys."""

        EJECT = "WAIT_EJECT"
        MOVEMENT = "WAIT_MOVEMENT"
        ASPIRATE = "WAIT_ASPIRATE"

    class VolumeConv:
        """Volume conversion configuration keys."""

        MAX_VOL = "max_vol"
        VOLUMES = "volumes"
        STEPS = "steps"
