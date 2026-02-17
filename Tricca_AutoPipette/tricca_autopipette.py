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
from tap_shell import TriccaAutoPipetteShell

# Constants
DEFAULT_LOG_FILE = "app.log"
LOG_FORMAT = "%(asctime)s [%(module)s] %(levelname)s: %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO


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
        Command line: python tricca_autopipette.py --conf config.yaml
        Returns: Namespace(conf='config.yaml')
    """
    parser = Cmd2ArgumentParser(
        description="Tricca AutoPipette Shell - Automated pipetting control interface"
    )
    parser.add_argument(
        "--conf",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to optional configuration file (YAML format)",
    )
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

    return parser.parse_args()


def validate_config_file(config_path: str | None) -> None:
    """Validate that the configuration file exists if provided.

    Args:
        config_path: Path to configuration file, or None.

    Raises:
        FileNotFoundError: If config file is specified but doesn't exist.
        ValueError: If config path exists but is not a file.

    Example:
        >>> validate_config_file("config.yaml")
        >>> validate_config_file(None)  # No validation needed
    """
    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        if not path.is_file():
            raise ValueError(f"Configuration path is not a file: {config_path}")
        logging.info("Using configuration file: %s", config_path)


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
        validate_config_file(args.conf)

        # Launch the shell
        logging.info("Starting Tricca AutoPipette Shell")
        shell = TriccaAutoPipetteShell(conf_autopipette=args.conf)
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
