#!/usr/bin/env python3
"""Entry point for the Tricca AutoPipette Shell application.

This module provides the main entry point and command-line argument parsing
for the Tricca AutoPipette Shell, a command-line interface for controlling
automated pipetting operations.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from cmd2 import Cmd2ArgumentParser
from pipette_constants import DefaultFilenames, DefaultPaths
from tap_shell import TriccaAutoPipetteShell

# Constants
DEFAULT_LOG_FILE = "app.log"
LOG_FORMAT = "%(asctime)s [%(module)s] %(levelname)s: %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO

# Configuration file paths
DIR_CONFIG = DefaultPaths.DIR_CONFIG
DIR_CONFIG_SYSTEM = DefaultPaths.DIR_CONFIG_SYSTEM
DIR_CONFIG_GANTRY = DefaultPaths.DIR_CONFIG_GANTRY
DIR_CONFIG_PIPETTE = DefaultPaths.DIR_CONFIG_PIPETTE
DIR_CONFIG_LOCATIONS = DefaultPaths.DIR_CONFIG_LOCATIONS
DIR_CONFIG_LIQUIDS = DefaultPaths.DIR_CONFIG_LIQUIDS

# Default configuration filenames
CONFIG_SYSTEM = DefaultFilenames.CONFIG_SYSTEM
CONFIG_GANTRY = DefaultFilenames.CONFIG_GANTRY
CONFIG_PIPETTE = DefaultFilenames.CONFIG_PIPETTE
CONFIG_LOCATIONS = DefaultFilenames.CONFIG_LOCATIONS
CONFIG_LIQUIDS = DefaultFilenames.CONFIG_LIQUIDS


def setup_logging(
    log_file: str = DEFAULT_LOG_FILE, level: int = DEFAULT_LOG_LEVEL
) -> None:
    """Configure application logging.

    Sets up file-based logging with a consistent format for all log messages.

    Args:
        log_file: Path to the log file (default: "app.log").
        level: Logging level (default: logging.INFO).

    Example:
        >>> setup_logging("custom.log", logging.DEBUG)
    """
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),  # Also log to console
        ],
    )
    logging.info("Logging initialized: %s", log_file)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Namespace object containing parsed command-line arguments.

    Example:
        Command line: python tricca_autopipette.py --config config.json
        Returns: Namespace(config='config.json')
    """
    parser = Cmd2ArgumentParser(
        description="Tricca AutoPipette Shell - Automated pipetting control interface"
    )
    # --------------------------- Configuration arguments --------------------------- #
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to optional system configuration file (JSON format)",
    )
    parser.add_argument(
        "--config-gantry",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to optional gantry configuration file (JSON format)",
    )
    parser.add_argument(
        "--config-pipette",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to optional pipette model configuration file (JSON format)",
    )
    parser.add_argument(
        "--config-liquids",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to optional liquid profile configurations file (JSON format)",
    )
    parser.add_argument(
        "--config-locations",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to optional location configurations file (JSON format)",
    )
    # ----------------------------- Logging arguments ----------------------------- #
    parser.add_argument(
        "--log-file",
        type=str,
        default=DEFAULT_LOG_FILE,
        metavar="FILE",
        help=f"Path to log file (default: {DEFAULT_LOG_FILE})",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    # ----------------------------- Connection arguments ----------------------------- #
    parser.add_argument(
        "--no-connect",
        default=False,
        action="store_true",
        help="Start the shell without attempting to connect to websocket",
    )
    parser.add_argument(
        "--local-connect",
        default=False,
        action="store_true",
        help="Start the shell and connect to a local websocket server (ws://localhost:8765)",
    )
    return parser.parse_args()


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
        config_system_path: Path = DIR_CONFIG_SYSTEM / Path(config_system)
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
        # config_pipette_path = DIR_CONFIG_PIPETTE / DEFAULT_CONFIG_PIPETTE
        config_pipette_path = (
            None  # Pipette config is optional, use None to skip validation
        )

    if config_locations is not None:
        config_locations_path = DIR_CONFIG_LOCATIONS / Path(config_locations)
    else:
        # config_locations_path = DIR_CONFIG_LOCATIONS / DEFAULT_CONFIG_LOCATIONS
        config_locations_path = (
            None  # Locations config is optional, use None to skip validation
        )

    if config_liquids is not None:
        config_liquids_path = DIR_CONFIG_LIQUIDS / Path(config_liquids)
    else:
        # config_liquids_path = DIR_CONFIG_LIQUIDS / DEFAULT_CONFIG_LIQUIDS
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


def main() -> int:
    """Entry point for the Tricca AutoPipette Shell application.

    Parses command-line arguments, configures logging, validates inputs,
    and launches the interactive shell interface.

    Returns:
        Exit code (0 for success, non-zero for errors).

    Example:
        >>> sys.exit(main())
    """
    try:
        # Parse command-line arguments
        args = parse_arguments()

        # Setup logging
        log_level = getattr(logging, args.log_level.upper())
        setup_logging(args.log_file, log_level)

        # Validate configuration file if provided
        validate_config_files(
            config_system=args.config,
            config_gantry=args.config_gantry,
            config_pipette=args.config_pipette,
            config_locations=args.config_locations,
            config_liquids=args.config_liquids,
        )

        if args.config is not None:
            config_system_path: Path = DIR_CONFIG_SYSTEM / Path(args.config)
        else:
            config_system_path = DIR_CONFIG_SYSTEM / CONFIG_SYSTEM

        if args.config_gantry is not None:
            config_gantry_path = DIR_CONFIG_GANTRY / Path(args.config_gantry)
        else:
            config_gantry_path = (
                None  # Gantry config is optional, use None to skip validation
            )

        if args.config_pipette is not None:
            config_pipette_path = DIR_CONFIG_PIPETTE / Path(args.config_pipette)
        else:
            config_pipette_path = (
                None  # Pipette config is optional, use None to skip validation
            )

        if args.config_locations is not None:
            config_locations_path = DIR_CONFIG_LOCATIONS / Path(args.config_locations)
        else:
            config_locations_path = (
                None  # Locations config is optional, use None to skip validation
            )

        if args.config_liquids is not None:
            config_liquids_path = DIR_CONFIG_LIQUIDS / Path(args.config_liquids)
        else:
            config_liquids_path = (
                None  # Liquids config is optional, use None to skip validation
            )
        # Launch the shell
        logging.info("Starting Tricca AutoPipette Shell")
        shell = TriccaAutoPipetteShell(
            config_system=config_system_path,
            config_gantry=config_gantry_path,
            config_pipette=config_pipette_path,
            config_locations=config_locations_path,
            config_liquids=config_liquids_path,
            connect_websocket=not args.no_connect,
        )
        shell.cmdloop()

        logging.info("Tricca AutoPipette Shell terminated successfully")
        return 0

    except (FileNotFoundError, ValueError) as e:
        logging.error("Configuration error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
        print("\nExiting...", file=sys.stderr)
        return 130  # Standard exit code for SIGINT

    except Exception as e:
        logging.exception("Unexpected error occurred")
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
