#!/usr/bin/env python3
"""Entry point for the ``tapd`` control daemon.

Parses the same ``--config*`` arguments as the interactive ``tap`` CLI
(``cli/main.py``), builds an ``AutoPipetteService``, and serves the
control-plane WebSocket forever via ``ControlServer``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from tricca_autopipette.core.config_validation import validate_config_files
from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths
from tricca_autopipette.daemon.control_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ControlServer,
)
from tricca_autopipette.daemon.service import AutoPipetteService

DEFAULT_LOG_FILE = "tapd.log"
LOG_FORMAT = "%(asctime)s [%(module)s] %(levelname)s: %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO


def setup_logging(
    log_file: str = DEFAULT_LOG_FILE, level: int = DEFAULT_LOG_LEVEL
) -> None:
    """Configure daemon logging.

    Args:
        log_file: Path to the log file.
        level: Logging level.
    """
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("Logging initialized: %s", log_file)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for ``tapd``.

    Returns:
        Namespace object containing parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Tricca AutoPipette control daemon (tapd)"
    )
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
    parser.add_argument(
        "--no-connect",
        default=False,
        action="store_true",
        help="Start without connecting to Moonraker (for local testing)",
    )
    parser.add_argument(
        "--local-connect",
        default=False,
        action="store_true",
        help="Connect to a local Moonraker instance (ws://localhost/websocket)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Control-plane bind host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Control-plane bind port (default: {DEFAULT_PORT})",
    )
    return parser.parse_args()


async def _serve(args: argparse.Namespace) -> None:
    """Build the service/server and run until interrupted.

    Args:
        args: Parsed command-line arguments.
    """
    dir_config_system = DefaultPaths.DIR_CONFIG_SYSTEM
    config_system: Path = (
        dir_config_system / args.config
        if args.config is not None
        else dir_config_system / DefaultFilenames.CONFIG_SYSTEM
    )
    config_gantry = (
        DefaultPaths.DIR_CONFIG_GANTRY / args.config_gantry
        if args.config_gantry is not None
        else None
    )
    config_pipette = (
        DefaultPaths.DIR_CONFIG_PIPETTE / args.config_pipette
        if args.config_pipette is not None
        else None
    )
    config_locations = (
        DefaultPaths.DIR_CONFIG_LOCATIONS / args.config_locations
        if args.config_locations is not None
        else None
    )
    config_liquids = (
        DefaultPaths.DIR_CONFIG_LIQUIDS / args.config_liquids
        if args.config_liquids is not None
        else None
    )

    service = AutoPipetteService(
        config_system=config_system,
        config_gantry=config_gantry,
        config_pipette=config_pipette,
        config_locations=config_locations,
        config_liquids=config_liquids,
        connect_websocket=not args.no_connect,
        connect_local_websocket=args.local_connect,
    )
    server = ControlServer(service, host=args.host, port=args.port)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await server.start()
    logging.info("tapd started")
    try:
        await stop_event.wait()
    finally:
        logging.info("tapd shutting down")
        await server.stop()


def main() -> int:
    """Entry point for the ``tapd`` control daemon.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    try:
        args = parse_arguments()
        log_level = getattr(logging, args.log_level.upper())
        setup_logging(args.log_file, log_level)

        validate_config_files(
            config_system=args.config,
            config_gantry=args.config_gantry,
            config_pipette=args.config_pipette,
            config_locations=args.config_locations,
            config_liquids=args.config_liquids,
        )

        asyncio.run(_serve(args))
        return 0

    except (FileNotFoundError, ValueError) as e:
        logging.error("Configuration error: %s", e)
        print(f"Error: {e}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        logging.info("tapd interrupted by user")
        print("\nExiting...", file=sys.stderr)
        return 130

    except Exception as e:
        logging.exception("Unexpected error occurred")
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
