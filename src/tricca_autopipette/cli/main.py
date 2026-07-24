#!/usr/bin/env python3
"""Entry point for the interactive Tricca AutoPipette client (``tap``).

``tap`` is a thin client of the ``tapd`` control daemon: all domain logic,
config loading, and the Moonraker connection live in the daemon
(``tricca_autopipette.daemon``), not here. See ``cli/remote_shell.py`` for
the shell that forwards commands over the control-plane WebSocket.

Note this is a breaking change from earlier versions of ``tap``, which
loaded config files and connected to Moonraker directly: the
``--config*``/``--no-connect``/``--local-connect`` flags that used to
configure *this* process now configure ``tapd`` instead (run ``tapd
--help``); ``tap`` itself only needs to know where the daemon's control
plane is (``--control-uri``).
"""

from __future__ import annotations

import argparse
import logging
import sys

from tricca_autopipette.cli.remote_shell import RemoteTapShell
from tricca_autopipette.daemon.control_server import DEFAULT_HOST, DEFAULT_PORT

DEFAULT_LOG_FILE = "app.log"
LOG_FORMAT = "%(asctime)s [%(module)s] %(levelname)s: %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_CONTROL_URI = f"ws://{DEFAULT_HOST}:{DEFAULT_PORT}/control"


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
    """
    parser = argparse.ArgumentParser(
        description="Tricca AutoPipette Shell - thin client for the tapd control daemon"
    )
    parser.add_argument(
        "--control-uri",
        type=str,
        default=DEFAULT_CONTROL_URI,
        metavar="URI",
        help=f"tapd control-plane WebSocket URI (default: {DEFAULT_CONTROL_URI})",
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


def main() -> int:
    """Entry point for the interactive Tricca AutoPipette client.

    Parses command-line arguments, configures logging, and connects a
    ``RemoteTapShell`` to the ``tapd`` control daemon.

    Returns:
        Exit code (0 for success, non-zero for errors).

    Example:
        >>> sys.exit(main())
    """
    try:
        args = parse_arguments()

        log_level = getattr(logging, args.log_level.upper())
        setup_logging(args.log_file, log_level)

        logging.info("Starting Tricca AutoPipette Shell (tapd client)")
        shell = RemoteTapShell(args.control_uri)
        shell.cmdloop()

        logging.info("Tricca AutoPipette Shell terminated successfully")
        return 0

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
