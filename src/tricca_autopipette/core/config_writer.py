"""Validated, non-lossy, atomic config write-back (issue #33).

The one place config files are written at runtime. Two rules make it safe:

- **Raw JSON only.** A write edits one file's unparsed JSON at a key path and
  never round-trips through a deserialized model, so fields a model doesn't
  know about, ``extends`` references, and ``plate_file`` references all
  survive byte-for-byte in meaning.
- **Never the shared repo.** A write to a file that currently resolves only
  from the shared ``config/`` root is copy-on-write into the per-machine
  local root (issue #68's filename override, local wins). ``system/`` is
  already local-only.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from tricca_autopipette.core.json_config_manager import JsonConfigManager
from tricca_autopipette.core.pipette_constants import DefaultPaths, LocalConfigRoots
from tricca_autopipette.core.pipette_models import (
    GantryKinematics,
    LiquidProfile,
    PipetteModel,
)

#: Categories `set_config_value` accepts. ``protocols`` is a union category
#: too, but holds ``.pipette`` scripts, not JSON config.
WRITABLE_CATEGORIES = ("system", "gantry", "pipettes", "liquids", "locations", "plates")


def set_config_value(
    category: str, filename: str, key_path: str, value: object
) -> Path:
    """Set one value in one config file and save it to the local root.

    Reads the file's raw JSON (local copy if there is one, else the shared
    one), sets `value` at `key_path`, and writes the result to the local root
    atomically.

    Args:
        category: ``system`` or a union category (``gantry``, ``pipettes``,
            ``liquids``, ``locations``, ``plates``).
        filename: Bare filename within that category, e.g. ``water.json``.
        key_path: Dotted path to the value, e.g. ``syringe.max_volume_ul``;
            a segment indexing into a JSON list is an integer, e.g.
            ``plates.0.x``. Every segment but the last must already exist.
        value: New JSON-serializable value.

    Returns:
        The local file that was written.

    Raises:
        ValueError: If the category or filename is invalid, `key_path` doesn't
            lead anywhere, or the edited file would not load. Nothing is
            written in any of these cases.
        FileNotFoundError: If the file exists in neither root (for
            ``system``: in the local root).

    Example:
        >>> set_config_value(
        ...     "liquids", "water.json", "density_g_ml", 1.0
        ... )  # doctest: +SKIP
        PosixPath('/home/me/.config/tricca-autopipette/liquids/water.json')
    """
    if category not in WRITABLE_CATEGORIES:
        raise ValueError(
            f"Unknown config category {category!r}; expected one of "
            f"{list(WRITABLE_CATEGORIES)}"
        )
    if Path(filename).name != filename:
        raise ValueError(f"Expected a bare filename, got {filename!r}")

    if category == "system":
        # Local-only (issue #68): the shared template is never read live.
        source = DefaultPaths.DIR_LOCAL_SYSTEM / filename
        if not source.exists():
            raise FileNotFoundError(f"System config not found: {source}")
        target = source
    else:
        source = LocalConfigRoots.resolve(category, filename)
        target = LocalConfigRoots.roots(category)[1] / filename
    raw: object = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{source} does not contain a JSON object")
    data = cast("dict[str, Any]", raw)

    _set_at_path(data, key_path, value)

    try:
        _validate(category, source.resolve().name, data)
    except (ValueError, TypeError, KeyError) as e:  # pydantic's is a ValueError
        raise ValueError(
            f"Refusing to write {category}/{filename}: it would not load ({e})"
        ) from e
    write_json_atomic(target, data)
    return target


def _set_at_path(data: dict[str, Any], key_path: str, value: object) -> None:
    """Set `value` at dotted `key_path` inside `data`, in place.

    Args:
        data: Parsed JSON object.
        key_path: Dotted path; list indices are integer segments.
        value: The value to set.

    Raises:
        ValueError: If an intermediate segment doesn't exist, or a segment
            can't index its container.
    """  # ruff: ignore[docstring-missing-exception]
    *parents, leaf = key_path.split(".")
    node: object = data
    try:
        for part in parents:
            if isinstance(node, list):
                node = cast("list[object]", node)[int(part)]
            elif isinstance(node, dict):
                node = cast("dict[str, object]", node)[part]
            else:
                raise KeyError(part)
        if isinstance(node, list):
            cast("list[object]", node)[int(leaf)] = value
        elif isinstance(node, dict):
            cast("dict[str, object]", node)[leaf] = value
        else:
            raise KeyError(leaf)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"Key path {key_path!r} not found: {e}") from e


def _validate(category: str, filename: str, data: dict[str, Any]) -> None:
    """Check that `data` would load as a `category` config file.

    Uses the same parsers the loaders use, on the in-memory dict, so nothing
    touches disk before the data is known good.

    Args:
        category: The config category.
        filename: The file's name (``system`` resolves ``extends`` against
            its siblings; locations use it in error messages).
        data: The raw JSON about to be written.

    Raises:
        KeyError: If `category` has no validator.
    """
    # Imported here: location_manager imports this module for
    # write_json_atomic.
    from tricca_autopipette.core.location_manager import LocationManager

    match category:
        case "system":
            JsonConfigManager().validate_system_data(filename, data)
        case "gantry":
            GantryKinematics(**data)
        case "pipettes":
            PipetteModel(**data)
        case "liquids":
            LiquidProfile(**data)
        case "locations":
            LocationManager().apply_locations_data(data, source=filename)
        case "plates":
            # A template carries geometry but no placement; place it far from
            # the origin (wells extend toward -x) and parse a one-plate deck.
            entry = {"x": 1e6, "y": 1e6, "z": 0, **data, "name": filename}
            LocationManager().apply_locations_data({"plates": [entry]})
        case _:
            raise KeyError(f"No validator for config category {category!r}")


def write_json_atomic(path: Path, data: object) -> None:
    r"""Write JSON to `path` atomically: temp file in the same dir, then replace.

    A crash mid-write leaves either the old file or the new one, never a
    truncated mix. A symlinked `path` (e.g. ``system/active.json``) is written
    through to its target rather than replaced by a regular file.

    Args:
        path: Destination file. Its parent directory is created if missing.
        data: JSON-serializable data.

    Example:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     target = Path(tmp) / "x.json"
        ...     write_json_atomic(target, {"a": 1})
        ...     target.read_text()
        '{\n  "a": 1\n}\n'
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
