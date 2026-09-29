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
from typing import Any, cast, get_args, get_origin

from pydantic import BaseModel

from tricca_autopipette.core.json_config_manager import JsonConfigManager
from tricca_autopipette.core.pipette_constants import DefaultPaths, LocalConfigRoots
from tricca_autopipette.core.pipette_models import (
    GantryKinematics,
    LiquidProfile,
    LocationsConfig,
    PipetteModel,
    PipetteSyringeKinematics,
    ServoConfig,
    SystemConfig,
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

    if _set_at_path(data, key_path, value):
        _check_known_key(category, key_path)

    try:
        _validate(category, source.resolve().name, data)
    except (ValueError, TypeError, KeyError) as e:  # pydantic's is a ValueError
        raise ValueError(
            f"Refusing to write {category}/{filename}: it would not load ({e})"
        ) from e
    _check_bounds(category, key_path, value)
    write_json_atomic(target, data)
    return target


def _set_at_path(data: dict[str, Any], key_path: str, value: object) -> bool:
    """Set `value` at dotted `key_path` inside `data`, in place.

    Args:
        data: Parsed JSON object.
        key_path: Dotted path; list indices are integer segments.
        value: The value to set.

    Returns:
        True if the leaf key was newly added to an object.

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
            return False
        if isinstance(node, dict):
            obj = cast("dict[str, object]", node)
            added = leaf not in obj
            obj[leaf] = value
            return added
        raise KeyError(leaf)
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"Key path {key_path!r} not found: {e}") from e


#: The model each category's file is parsed as, for `_check_known_key`.
#: ``locations``/``plates`` have none: `LocationManager` parses raw dicts and
#: keeps unknown keys on save, so any key is allowed there.
_CATEGORY_MODELS: dict[str, type[BaseModel]] = {
    "system": SystemConfig,
    "gantry": GantryKinematics,
    "pipettes": PipetteModel,
    "liquids": LiquidProfile,
}


def _check_known_key(category: str, key_path: str) -> None:
    """Reject adding a key the category's model doesn't define.

    The models ignore unknown fields, so without this a mistyped field name
    would be written and then silently do nothing. Only *new* keys are
    checked; editing a key already in the file is always allowed.

    Args:
        category: The config category.
        key_path: Dotted path of the newly added key.

    Raises:
        ValueError: If the model has no such field.
    """
    model = _CATEGORY_MODELS.get(category)
    if model is None or (category == "system" and key_path == "extends"):
        return
    if not _model_defines(model, key_path.split(".")):
        raise ValueError(
            f"Unknown key {key_path!r} for {category}: {model.__name__} has no "
            f"such field (known: {sorted(model.model_fields)})"
        )


def _model_defines(model: type[BaseModel], parts: list[str]) -> bool:
    """Report whether `parts` names a field path through `model`.

    Args:
        model: The model to walk.
        parts: Key path segments.

    Returns:
        True if the path is a known field, or passes into a free-form value
        (a ``dict[str, str]``, a list, `LocationsConfig`'s raw sources) where
        there is nothing to check against.
    """
    field = model.model_fields.get(parts[0])
    if field is None:
        return False
    rest = parts[1:]
    annotation: Any = field.annotation
    while rest and get_origin(annotation) is dict:
        # A keyed collection (e.g. liquids by name): the segment is a key.
        annotation, rest = get_args(annotation)[1], rest[1:]
    if not rest:
        return True
    candidates = get_args(annotation) or (annotation,)
    models = [
        c
        for c in candidates
        if isinstance(c, type) and issubclass(c, BaseModel) and c is not LocationsConfig
    ]
    return not models or any(_model_defines(m, rest) for m in models)


#: Allowed range of every high-risk numeric field (issue #33 slice c), keyed
#: by the model that owns it -- so the same bound applies however the field is
#: reached (``gantry/x.json`` ``speed_xy`` or a system file's
#: ``gantry.speed_xy``). Enforced on every write, not on load, so an existing
#: rig file outside a range still loads. The kiosk Settings page shows exactly
#: these fields for its pipette and gantry sections, with these bounds.
#:
#: Ceilings are the highest value any shared ``config/`` file ships with (the
#: known-good envelope). The one exception is ``max_volume_ul``, whose ceiling
#: is 1000 uL, the largest syringe in use (Murphy's 1000 uL profile). Speed and
#: acceleration floors sit well below anything shipped, slow enough for
#: bring-up, but rule out a near-zero value that makes one move take minutes.
HIGH_RISK_BOUNDS: dict[tuple[type[BaseModel], str], tuple[float, float]] = {
    (GantryKinematics, "speed_xy"): (100, 38000),  # mm/min
    (GantryKinematics, "speed_z"): (100, 12000),  # mm/min
    (GantryKinematics, "speed_max"): (100, 99999),  # mm/min
    (GantryKinematics, "accel_xy"): (100, 40000),  # mm/s²
    (GantryKinematics, "accel_z"): (100, 40000),  # mm/s²
    (GantryKinematics, "accel_max"): (100, 40000),  # mm/s²
    (PipetteSyringeKinematics, "max_volume_ul"): (1, 1000),
    (PipetteSyringeKinematics, "min_volume_ul"): (0.1, 100),
    (PipetteSyringeKinematics, "capacity_margin_ul"): (0, 50),
    # The hard mechanical limit (#29): the syringe's physical stroke is 60 mm,
    # and homing drives up to twice this toward the endstop.
    (PipetteSyringeKinematics, "max_travel_mm"): (1, 60),
    (PipetteSyringeKinematics, "speed_aspirate"): (0.25, 50),  # mm/s
    (PipetteSyringeKinematics, "speed_dispense"): (0.25, 50),  # mm/s
    (PipetteSyringeKinematics, "accel_home"): (2.5, 200),  # mm/s²
    (PipetteSyringeKinematics, "accel_move"): (2.5, 200),  # mm/s²
    (PipetteSyringeKinematics, "wait_aspirate_ms"): (0, 10000),
    (PipetteSyringeKinematics, "wait_dispense_ms"): (0, 10000),
    (ServoConfig, "angle_retract"): (0, 180),  # degrees
    (ServoConfig, "angle_eject"): (0, 180),  # degrees
    (ServoConfig, "wait_ms"): (0, 5000),
}


def _check_bounds(category: str, key_path: str, value: object) -> None:
    """Reject a write that puts a high-risk field outside `HIGH_RISK_BOUNDS`.

    A dict `value` (a whole block, e.g. ``gantry``) is checked leaf by leaf.

    Args:
        category: The config category.
        key_path: Dotted path the value is written at.
        value: The value being written.

    Raises:
        ValueError: If a bounded field's new value is out of range.
    """
    model = _CATEGORY_MODELS.get(category)
    if model is None:
        return
    if isinstance(value, dict):
        for key, sub in cast("dict[str, object]", value).items():
            _check_bounds(category, f"{key_path}.{key}", sub)
        return
    owner = _owning_field(model, key_path.split("."))
    bounds = HIGH_RISK_BOUNDS.get(owner) if owner else None
    if bounds is None or isinstance(value, bool) or not isinstance(value, int | float):
        return  # unbounded, or not a number (the model rejects that itself)
    low, high = bounds
    if not low <= value <= high:
        raise ValueError(
            f"{key_path} = {value} is outside the allowed range {low:g}-{high:g}"
        )


def _owning_field(
    model: type[BaseModel], parts: list[str]
) -> tuple[type[BaseModel], str] | None:
    """Find the model and field a key path ends on (see `_model_defines`).

    Args:
        model: The model to walk.
        parts: Key path segments.

    Returns:
        ``(owning model, field name)``, or None if the path isn't a model field.
    """
    field = model.model_fields.get(parts[0])
    if field is None:
        return None
    rest = parts[1:]
    annotation: Any = field.annotation
    while rest and get_origin(annotation) is dict:
        annotation, rest = get_args(annotation)[1], rest[1:]
    if not rest:
        return model, parts[0]
    for candidate in get_args(annotation) or (annotation,):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            found = _owning_field(candidate, rest)
            if found is not None:
                return found
    return None


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
