#!/usr/bin/env python3
"""Entry point for the ``tapd`` control daemon.

Parses the ``--config*``/``--no-connect``/``--local-connect`` flags that
``tap`` (``cli/main.py``) used to parse before the daemon split —
``cli/main.py`` no longer loads config files at all. Builds an
``AutoPipetteService`` and serves the control-plane WebSocket forever via
``ControlServer``.

Also owns the local ``system/`` config lifecycle (issue #68):
`resolve_system_config` implements the bootstrap-copy/ambiguous-choice-
prompt/no-TTY-hard-fail dance that decides which local system profile a
headless (or interactive) start loads, and `init_local_config` backs
``--init-local-config``. Both live here rather than in `core/` because they
need to prompt on stdin and can exit the process outright -- process-level
concerns, not config-loading ones.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import signal
import sys
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tricca_autopipette.core.config_validation import validate_config_files
from tricca_autopipette.core.pipette_constants import (
    DefaultFilenames,
    DefaultPaths,
    LocalConfigRoots,
)
from tricca_autopipette.daemon.control_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ControlServer,
)
from tricca_autopipette.daemon.service import AutoPipetteService

DEFAULT_LOG_FILE = "tapd.log"
LOG_FORMAT = "%(asctime)s [%(module)s] %(levelname)s: %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO
# Issue #52 meaningfully increases log volume (an INFO line per movement/
# pipetting action plus every control-plane RPC) -- a plain FileHandler
# would grow unbounded on a long-running daemon, so rotate instead. 10 MiB
# x 5 backups is a size cap, not a tuned figure; revisit if real-world
# volume warrants it.
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 5


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
            RotatingFileHandler(
                log_file,
                maxBytes=DEFAULT_LOG_MAX_BYTES,
                backupCount=DEFAULT_LOG_BACKUP_COUNT,
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info(
        "Logging initialized: %s (rotating, max %d bytes x %d backups)",
        log_file,
        DEFAULT_LOG_MAX_BYTES,
        DEFAULT_LOG_BACKUP_COUNT,
    )


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
        help=(
            "Name of the local system configuration profile to load "
            "(resolved under the per-machine local config root's system/ "
            "directory, never the shared repo -- see config/README.md). "
            "Also re-points system/active.json at it."
        ),
    )
    parser.add_argument(
        "--init-local-config",
        type=str,
        nargs="?",
        const="default_system",
        default=None,
        metavar="NAME",
        help=(
            "Copy the shared default system config template into the local "
            "config root as NAME.json (default 'default_system' if NAME is "
            "omitted), then exit without starting the daemon."
        ),
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


def _copy_shared_default_system() -> Path:
    """Copy the shared repo's system-config template into the local root.

    Returns:
        The path the template was copied to, under `DefaultPaths.DIR_LOCAL_SYSTEM`.

    Raises:
        FileNotFoundError: If the shared template itself is missing.
    """
    src = DefaultPaths.DIR_CONFIG_SYSTEM / DefaultFilenames.CONFIG_SYSTEM
    if not src.exists():
        raise FileNotFoundError(f"Shared system config template not found: {src}")

    dest_dir = DefaultPaths.DIR_LOCAL_SYSTEM
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / DefaultFilenames.CONFIG_SYSTEM
    shutil.copy2(src, dest)
    return dest


def init_local_config(name: str) -> Path:
    """Bootstrap a named local system profile from the shared template.

    Backs ``--init-local-config``. Never overwrites an existing profile --
    unlike the automatic none-found bootstrap in `resolve_system_config`
    (which only ever runs when nothing local exists yet), this is an
    explicit operator action naming a specific target file, so silently
    clobbering it would be a surprise.

    Args:
        name: Profile name (without ``.json``) to create under the local
            ``system/`` directory.

    Returns:
        The path the template was copied to.

    Raises:
        FileNotFoundError: If the shared template itself is missing.
        FileExistsError: If a local profile with that name already exists.
    """
    dest_dir = DefaultPaths.DIR_LOCAL_SYSTEM
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.json"
    if dest.exists():
        raise FileExistsError(
            f"Local system config {dest} already exists; remove it or choose "
            f"a different name."
        )

    src = DefaultPaths.DIR_CONFIG_SYSTEM / DefaultFilenames.CONFIG_SYSTEM
    if not src.exists():
        raise FileNotFoundError(f"Shared system config template not found: {src}")

    shutil.copy2(src, dest)
    return dest


def _prompt_for_system_config(names: list[str], default: str) -> str:
    """Ask an operator to pick among several local system configs.

    The real, stdin-based implementation `resolve_system_config` uses when
    not given an injected `prompt` callable.

    Args:
        names: Available profile filenames, in `list_system_configs` order.
        default: Filename to use if the operator presses Enter with no input.

    Returns:
        The chosen filename (not validated against `names` -- the caller
        does that).
    """
    print("Multiple local system configs found:", file=sys.stderr)
    for index, name in enumerate(names, start=1):
        marker = " (last loaded)" if name == default else ""
        print(f"  {index}) {name}{marker}", file=sys.stderr)
    choice = input(f"Load which config? [{default}]: ").strip()
    if not choice:
        return default
    if choice.isdigit() and 1 <= int(choice) <= len(names):
        return names[int(choice) - 1]
    return choice


def resolve_system_config(
    explicit: str | None,
    *,
    interactive: bool | None = None,
    prompt: Callable[[list[str], str], str] | None = None,
) -> str:
    """Decide which local system config file to load (issue #68).

    - An explicit ``--config`` always resolves under the local ``system/``
      directory, bypassing discovery entirely, and re-points ``active.json``
      at it.
    - No local system config at all: warns, auto-copies the shared template
      in, and points ``active.json`` at the copy.
    - Exactly one local system config: used as-is; ``active.json`` is
      (re)pointed at it.
    - More than one, no explicit ``--config``, and stdin is a TTY: prompts
      interactively, defaulting to whatever ``active.json`` currently names
      (falling back to the most recently added file if unset/stale).
    - More than one, no explicit ``--config``, and stdin is not a TTY (the
      normal systemd case): hard-fails naming the available profiles, rather
      than guessing or hanging waiting on input that will never arrive.

    Args:
        explicit: The ``--config`` value, or None.
        interactive: Overrides the TTY check, for tests. None (the default)
            means "ask `sys.stdin.isatty()`".
        prompt: Overrides the real stdin-based prompt, for tests. Takes the
            available filenames and the default choice, returns the chosen
            filename.

    Returns:
        The filename (not a path) of the chosen local system config --
        resolved against `DefaultPaths.DIR_LOCAL_SYSTEM` by
        `JsonConfigManager`.

    Raises:
        FileNotFoundError: If an explicit ``--config`` names a file that
            doesn't exist locally, or the shared template is missing when an
            auto-copy is needed.
        ValueError: If multiple local configs exist, no ``--config`` was
            given, and stdin is not a TTY to prompt on; or a prompted choice
            doesn't name one of the available files.
    """
    local_dir = DefaultPaths.DIR_LOCAL_SYSTEM
    local_dir.mkdir(parents=True, exist_ok=True)

    if explicit is not None:
        chosen = local_dir / explicit
        if not chosen.exists():
            raise FileNotFoundError(
                f"System config not found: {explicit} (searched in {local_dir})"
            )
        LocalConfigRoots.set_active_system(chosen)
        return explicit

    existing = LocalConfigRoots.list_system_configs()

    if not existing:
        logging.warning(
            "No local system config found in %s; copying in the shared "
            "default template (%s)",
            local_dir,
            DefaultFilenames.CONFIG_SYSTEM,
        )
        copied = _copy_shared_default_system()
        LocalConfigRoots.set_active_system(copied)
        return copied.name

    if len(existing) == 1:
        LocalConfigRoots.set_active_system(existing[0])
        return existing[0].name

    names = [path.name for path in existing]
    is_interactive = sys.stdin.isatty() if interactive is None else interactive
    if not is_interactive:
        raise ValueError(
            f"Multiple local system configs found ({', '.join(names)}) and "
            f"no --config given; refusing to guess at startup with no "
            f"terminal to prompt on. Pass --config <name>, or set "
            f"{LocalConfigRoots.active_system_link_path()} by hand."
        )

    active = LocalConfigRoots.active_system_target()
    default_name = (
        active.name if active is not None and active in existing else names[-1]
    )
    ask = prompt or _prompt_for_system_config
    chosen_name = ask(names, default_name)
    if chosen_name not in names:
        raise ValueError(
            f"{chosen_name!r} is not one of the available configs: {names}"
        )

    chosen = local_dir / chosen_name
    LocalConfigRoots.set_active_system(chosen)
    return chosen_name


async def _serve(args: argparse.Namespace, system_filename: str) -> None:
    """Build the service/server and run until interrupted.

    Args:
        args: Parsed command-line arguments.
        system_filename: The local system config filename to load, as
            resolved by `resolve_system_config`.
    """
    config_system: Path = DefaultPaths.DIR_LOCAL_SYSTEM / system_filename
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

        if args.init_local_config is not None:
            path = init_local_config(args.init_local_config)
            print(f"Copied shared default system config to {path}")
            return 0

        system_filename = resolve_system_config(args.config)

        validate_config_files(
            config_gantry=args.config_gantry,
            config_pipette=args.config_pipette,
            config_locations=args.config_locations,
            config_liquids=args.config_liquids,
        )

        asyncio.run(_serve(args, system_filename))
        return 0

    except (FileNotFoundError, FileExistsError, ValueError) as e:
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
