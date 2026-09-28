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
from typing import Any


def write_json_atomic(path: Path, data: Any) -> None:
    """Write JSON to `path` atomically: temp file in the same dir, then replace.

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
        '{\\n  "a": 1\\n}\\n'
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
