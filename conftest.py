"""Repo-root pytest configuration: isolates the per-machine local config root.

Must run -- and set ``AUTOPIPETTE_LOCAL_DIR`` -- before anything imports
``tricca_autopipette.core.pipette_constants``: `DefaultPaths.DIR_LOCAL_ROOT`
(like the pre-existing `DefaultPaths.DIR_REPO_ROOT`) is resolved once at
class-body/import time, not per-call, so setting the env var from
``tests/conftest.py`` -- which already imports `pipette_constants` itself --
would be too late.

Kept at the repo root rather than under ``tests/``, and deliberately
importing nothing from `tricca_autopipette`, so pytest collects and executes
it before ``tests/conftest.py``. Without this, every test that loads "the
real default configs" (see ``tests/conftest.py``) would resolve
``system/`` -- local-only per issue #68 -- against the developer's actual
``~/.config/tricca-autopipette``, which has no seeded ``default_system.json``
and must never be written to by an automated test run regardless.

The six other categories (``gantry``/``pipettes``/``liquids``/``locations``/
``plates``/``protocols``) need no seeding here: they stay shared-and-local
union categories that fall through to the real shared ``config/``/
``protocols/`` trees when the isolated local root is empty for them, exactly
as today.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_LOCAL_DIR = Path(tempfile.mkdtemp(prefix="tap-test-local-config-"))
os.environ["AUTOPIPETTE_LOCAL_DIR"] = str(_LOCAL_DIR)
atexit.register(shutil.rmtree, _LOCAL_DIR, ignore_errors=True)

_REPO_ROOT = Path(__file__).parent
_SHARED_DEFAULT_SYSTEM = _REPO_ROOT / "config" / "system" / "default_system.json"

_local_system_dir = _LOCAL_DIR / "system"
_local_system_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(_SHARED_DEFAULT_SYSTEM, _local_system_dir / _SHARED_DEFAULT_SYSTEM.name)
