"""Shared configuration-file validation.

Moved out of `cli/main.py` in the daemon migration: `tapd` (the only
process that still loads config files directly) needs this, but the
interactive `tap` CLI no longer does now that it's a thin client of the
daemon (see `cli/remote_shell.py`).

``config_system`` is deliberately not handled here (issue #68): resolving it
is no longer a straight lookup -- it can auto-copy a template in, prompt
interactively, or hard-fail on an ambiguous headless start -- so that whole
lifecycle lives in `daemon/main.py`'s ``resolve_system_config``, which runs
before this function and validates an explicit ``--config`` itself.
"""

from __future__ import annotations

import logging

from tricca_autopipette.core.pipette_constants import LocalConfigRoots


def validate_config_files(
    config_gantry: str | None,
    config_pipette: str | None,
    config_locations: str | None,
    config_liquids: str | None,
) -> None:
    """Validate that each configuration file exists if a path is provided.

    Resolves each config argument through `LocalConfigRoots` (local wins over
    shared); an argument left as None is optional and skipped entirely.

    Args:
        config_gantry: Filename of the gantry configuration file, or None to
                       skip validation.
        config_pipette: Filename of the pipette configuration file, or None
                        to skip validation.
        config_locations: Filename of the locations configuration file, or
                          None to skip validation.
        config_liquids: Filename of the liquids configuration file, or None
                        to skip validation.

    Raises:
        ValueError: If a named file exists but is not a regular file.

    Example:
        >>> validate_config_files("default_gantry.json", None, None, None)
        >>> validate_config_files(None, None, None, None)  # all skipped
    """
    for category, filename in (
        ("gantry", config_gantry),
        ("pipettes", config_pipette),
        ("locations", config_locations),
        ("liquids", config_liquids),
    ):
        if filename is None:
            continue

        config_path = LocalConfigRoots.resolve(category, filename)
        if not config_path.is_file():
            raise ValueError(f"Configuration path is not a file: {config_path}")
        logging.info("Using configuration file: %s", config_path)
