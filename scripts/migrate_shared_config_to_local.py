#!/usr/bin/env python3
"""One-off migration: real per-machine data out of the shared repo (issue #68).

`config/`/`protocols/` are the shared code repo now that the local-root
split (`core/pipette_constants.py`'s `LocalConfigRoots`, `daemon/main.py`'s
`resolve_system_config`) has landed, but the *data* that motivated the split
hasn't moved yet: `config/system/system.json`/`default_system.json` still
carry TAP-Tyson's real hostname, and (once PR #66's Murphy conversion lands
alongside this) `config/{system,locations,pipettes}/murphy_*` and
`protocols/legacy/murphy_*/` carry that rig's real deck/protocols too. This
script copies whichever of that real data actually exists in this checkout
out to a local config root, shaped the way `DefaultPaths.DIR_LOCAL_*`
expects it.

Deliberately **dry-run by default**; the copy only happens with `--apply`.
The shared-repo half of the job -- deleting the migrated files and scrubbing
`config/system/default_system.json` back to a generic, non-identifying
template -- is **always** print-only from this script, never executed here.
That's a separate, explicit step: it rewrites real hostname data and (once
the Murphy files exist on this branch) deletes over a hundred tracked files,
which is worth a human actually reading the plan before it happens, run by
hand once this script's copy has been confirmed to have landed correctly.

Run directly, from the repo root:

    python scripts/migrate_shared_config_to_local.py                # dry run
    python scripts/migrate_shared_config_to_local.py --apply         # copies
    python scripts/migrate_shared_config_to_local.py --out /some/dir --apply

`--out` defaults to the real local config root
(`DefaultPaths.DIR_LOCAL_ROOT` -- i.e. `$AUTOPIPETTE_LOCAL_DIR`, falling back
to `$XDG_CONFIG_HOME/tricca-autopipette`/`~/.config/tricca-autopipette`), so
running this with no flags at all on the real physical machine is the normal
case; pass `--out` to migrate into a scratch directory for review instead.

Not meant to be re-run blindly once the shared repo has actually been
scrubbed -- at that point `default_system.json` is a generic template, not
real data, and there is nothing left here worth migrating. Kept as a record
of exactly how the migration was done, in the same spirit as the (separate,
Murphy-specific) `scripts/convert_murphy_legacy.py`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, cast

from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_SYSTEM = REPO_ROOT / "config" / "system"
SHARED_LOCATIONS = REPO_ROOT / "config" / "locations"
SHARED_PIPETTES = REPO_ROOT / "config" / "pipettes"
SHARED_PROTOCOLS_LEGACY = REPO_ROOT / "protocols" / "legacy"

#: Filenames in config/system/ carrying TAP-Tyson's real data today. Only
#: default_system.json is actually migrated (system.json is a byte-for-byte
#: duplicate of it, kept only because tapd used to require an explicit
#: `--config system.json` to reach it -- no longer true post-#68).
TAP_TYSON_SYSTEM_FILES = ("default_system.json", "system.json")

#: Machine-name prefixes PR #66's Murphy conversion uses for its config
#: files. Empty on a checkout where that PR hasn't landed yet -- every glob
#: below simply matches nothing, and this script migrates only TAP-Tyson's
#: data in that case.
MURPHY_MACHINE_PREFIXES = ("murphy_100", "murphy_1000")


class Plan:
    """Accumulates what would be copied, without touching the filesystem."""

    def __init__(self, out_root: Path) -> None:
        """Initialize an empty plan targeting `out_root`.

        Args:
            out_root: Local config root the plan's copies are relative to.
        """
        self.out_root = out_root
        self.copies: list[tuple[Path, Path]] = []  # (source, dest)

    def add(self, source: Path, dest_relative: Path) -> None:
        """Queue one file to copy.

        Args:
            source: Existing file in the shared repo.
            dest_relative: Path relative to `out_root` to copy it to.
        """
        self.copies.append((source, self.out_root / dest_relative))

    def execute(self) -> None:
        """Perform every queued copy, creating parent directories as needed."""
        for source, dest in self.copies:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)

    def describe(self) -> str:
        """Render the plan as human-readable lines.

        Returns:
            One line per queued copy.
        """
        if not self.copies:
            return "  (nothing to migrate -- no real per-machine data found)"
        lines = [
            f"  {src.relative_to(REPO_ROOT)} -> {dest}" for src, dest in self.copies
        ]
        return "\n".join(lines)


def _flatten_system_config(path: Path) -> dict[str, Any]:
    """Read a system config, resolving any `extends` chain against SHARED_SYSTEM.

    Mirrors `JsonConfigManager._load_system_data`'s merge order (child keys
    win over ancestors), but reads only from the shared repo -- the source
    files being migrated haven't moved yet, so their `extends` targets (if
    any) still live there too.

    Args:
        path: The system config file to flatten.

    Returns:
        The fully-merged config, with `extends` removed.

    Raises:
        ValueError: If any file in the chain isn't a JSON object, or the
            chain cycles.
    """
    chain: list[str] = []
    merged: dict[str, Any] = {}
    current: Path | None = path

    while current is not None:
        current_name: str = current.name
        if current_name in chain:
            raise ValueError(f"Cyclic 'extends' migrating {path}: {chain}")
        chain.append(current_name)

        raw: Any = json.loads(current.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{current} must contain a JSON object")
        data = cast("dict[str, Any]", raw)

        parent_name: str | None = data.pop("extends", None)
        merged = {**data, **merged}
        current = (SHARED_SYSTEM / parent_name) if parent_name else None

    return merged


def _plan_tap_tyson(plan: Plan) -> None:
    """Queue TAP-Tyson's real system config, flattened, if it exists.

    Args:
        plan: Plan to add to.
    """
    src = SHARED_SYSTEM / DefaultFilenames.CONFIG_SYSTEM
    if not src.exists():
        return

    flattened = _flatten_system_config(src)
    if flattened == json.loads(src.read_text(encoding="utf-8")):
        # No `extends` to resolve -- copy the file verbatim rather than a
        # dict round-tripped through json.dumps, to preserve key order/
        # formatting for a human reviewing the migrated copy.
        plan.add(src, Path("system") / DefaultFilenames.CONFIG_SYSTEM)
    else:
        # `extends` chain flattened -- caller must write this out, not just
        # copy a file. Recorded here as a copy of the resolved *source*'s
        # nearest ancestor for traceability; `--apply` special-cases this.
        plan.copies.append((src, plan.out_root / "system" / "_FLATTEN_PENDING.json"))


def _plan_murphy(plan: Plan) -> None:
    """Queue Murphy-shaped config/protocols, for whichever prefixes exist.

    A no-op on a checkout that doesn't have PR #66's conversion -- every
    glob below simply matches nothing.

    Args:
        plan: Plan to add to.
    """
    for prefix in MURPHY_MACHINE_PREFIXES:
        system_file = SHARED_SYSTEM / f"{prefix}_system.json"
        if system_file.exists():
            plan.add(system_file, Path("system") / f"{prefix}_system.json")

        for deck_file in sorted(SHARED_LOCATIONS.glob(f"{prefix}_*.json")):
            plan.add(deck_file, Path("locations") / deck_file.name)

        pipette_file = SHARED_PIPETTES / f"{prefix}.json"
        if pipette_file.exists():
            plan.add(pipette_file, Path("pipettes") / pipette_file.name)

        legacy_dir = SHARED_PROTOCOLS_LEGACY / prefix
        if legacy_dir.is_dir():
            for proto_file in sorted(legacy_dir.glob("*.pipette")):
                plan.add(proto_file, Path("protocols") / proto_file.name)


def build_plan(out_root: Path) -> Plan:
    """Build the full migration plan.

    Args:
        out_root: Target local config root.

    Returns:
        The populated plan (not yet executed).
    """
    plan = Plan(out_root)
    _plan_tap_tyson(plan)
    _plan_murphy(plan)
    return plan


def _print_shared_repo_scrub_plan(plan: Plan) -> None:
    """Print (never execute) what the shared-repo half of the job would do."""
    print("\nShared-repo scrub (NOT executed by this script -- run by hand once")
    print("the copy above has been confirmed to have landed correctly):\n")
    print(
        "  1. Replace config/system/default_system.json's content with a "
        "generic,\n     non-identifying template (placeholder hostname, "
        "generic system_name).\n"
    )
    if (SHARED_SYSTEM / "system.json").exists():
        print(f"  2. git rm {(SHARED_SYSTEM / 'system.json').relative_to(REPO_ROOT)}")
    migrated_from_repo = {
        src for src, _dest in plan.copies if src.name != "default_system.json"
    }
    for src in sorted(migrated_from_repo):
        print(f"     git rm {src.relative_to(REPO_ROOT)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list, or None to use `sys.argv`.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DefaultPaths.DIR_LOCAL_ROOT,
        help="Target local config root (default: the real one this machine "
        "would use -- DefaultPaths.DIR_LOCAL_ROOT).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually copy files. Without this, only prints the plan.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list, or None to use `sys.argv`.

    Returns:
        Exit code.
    """
    args = parse_args(argv)
    plan = build_plan(args.out)

    print(f"Migration plan (target: {args.out}):")
    print(plan.describe())

    pending_flatten = [
        dest for _src, dest in plan.copies if dest.name == "_FLATTEN_PENDING.json"
    ]
    if pending_flatten:
        print(
            "\nNote: TAP-Tyson's system config has an 'extends' chain -- "
            "review the flattened\noutput by hand before applying; this "
            "script refuses to guess at merge intent\nfor a non-trivial "
            "chain."
        )
        return 1

    if not args.apply:
        print("\nDry run -- pass --apply to actually copy these files.")
        _print_shared_repo_scrub_plan(plan)
        return 0

    plan.execute()
    print(f"\nCopied {len(plan.copies)} file(s) to {args.out}.")
    _print_shared_repo_scrub_plan(plan)
    return 0


if __name__ == "__main__":
    sys.exit(main())
