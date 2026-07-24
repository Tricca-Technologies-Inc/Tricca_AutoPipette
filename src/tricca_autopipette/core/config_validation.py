"""Shared configuration-file validation.

Moved out of `cli/main.py` in the daemon migration: `tapd` (the only
process that still loads config files directly) needs this, but the
interactive `tap` CLI no longer does now that it's a thin client of the
daemon (see `cli/remote_shell.py`).
"""

from __future__ import annotations

import logging
from pathlib import Path

from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths

DIR_CONFIG_SYSTEM = DefaultPaths.DIR_CONFIG_SYSTEM
DIR_CONFIG_GANTRY = DefaultPaths.DIR_CONFIG_GANTRY
DIR_CONFIG_PIPETTE = DefaultPaths.DIR_CONFIG_PIPETTE
DIR_CONFIG_LOCATIONS = DefaultPaths.DIR_CONFIG_LOCATIONS
DIR_CONFIG_LIQUIDS = DefaultPaths.DIR_CONFIG_LIQUIDS

CONFIG_SYSTEM = DefaultFilenames.CONFIG_SYSTEM


def validate_config_files(
    config_system: str | None,
    config_gantry: str | None,
    config_pipette: str | None,
    config_locations: str | None,
    config_liquids: str | None,
) -> None:
    """Validate that each configuration file exists if a path is provided.

    Resolves each config argument against its corresponding default directory,
    falling back to the default filename if the argument is None.

    Args:
        config_system: Filename of the system configuration file, or None to use the
                       default.
        config_gantry: Filename of the gantry configuration file, or None to use the
                       default.
        config_pipette: Filename of the pipette configuration file, or None to use the
                        default.
        config_locations: Filename of the locations configuration file, or None to use
                          the default.
        config_liquids: Filename of the liquids configuration file, or None to use the
                        default.

    Example:
        >>> validate_config_files("system.json", None, None, None, None)
        >>> validate_config_files(None, None, None, None, None)  # all defaults
    """

    def _validate_path_as_file(config_path: Path | None) -> None:
        """Check that a resolved config path exists and is a regular file.

        Args:
            config_path: Resolved path to validate, or None to skip validation.

        Raises:
            FileNotFoundError: If the path does not exist.
            ValueError: If the path exists but is not a regular file.
        """
        if config_path is not None:
            if not config_path.exists():
                raise FileNotFoundError(f"Configuration file not found: {config_path}")
            if not config_path.is_file():
                raise ValueError(f"Configuration path is not a file: {config_path}")
            logging.info("Using configuration file: %s", config_path)

    config_system_path: Path
    config_gantry_path: Path | None
    config_pipette_path: Path | None
    config_locations_path: Path | None
    config_liquids_path: Path | None

    if config_system is not None:
        config_system_path = DIR_CONFIG_SYSTEM / Path(config_system)
    else:
        config_system_path = DIR_CONFIG_SYSTEM / CONFIG_SYSTEM

    if config_gantry is not None:
        config_gantry_path = DIR_CONFIG_GANTRY / Path(config_gantry)
    else:
        config_gantry_path = (
            None  # Gantry config is optional, use None to skip validation
        )

    if config_pipette is not None:
        config_pipette_path = DIR_CONFIG_PIPETTE / Path(config_pipette)
    else:
        config_pipette_path = (
            None  # Pipette config is optional, use None to skip validation
        )

    if config_locations is not None:
        config_locations_path = DIR_CONFIG_LOCATIONS / Path(config_locations)
    else:
        config_locations_path = (
            None  # Locations config is optional, use None to skip validation
        )

    if config_liquids is not None:
        config_liquids_path = DIR_CONFIG_LIQUIDS / Path(config_liquids)
    else:
        config_liquids_path = (
            None  # Liquids config is optional, use None to skip validation
        )

    for config_path in [
        config_system_path,
        config_gantry_path,
        config_pipette_path,
        config_locations_path,
        config_liquids_path,
    ]:
        if config_path is not None:
            config_path = Path(config_path)
        _validate_path_as_file(config_path)
