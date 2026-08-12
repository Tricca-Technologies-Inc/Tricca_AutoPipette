"""Freshness checks for the generated ``docs/protocol-command-reference.md``.

Mirrors ``tests/daemon/test_control_server_dispatch_completeness.py``'s
"assert a generated-from-code artifact isn't stale" pattern, but for
``scripts/generate_protocol_reference.py`` instead of ``ControlServer``.
Two independent checks:

- The committed file's contents match what the generator produces *right
  now* -- catches someone editing the committed Markdown by hand, or
  editing a parser's help text without regenerating.
- The generator's own command list (``_COMMANDS``) names exactly the set of
  commands ``AutoPipetteService`` actually dispatches from a protocol-file
  line (``_LINE_DISPATCH``/``_STR_ARG_DISPATCH``, plus the special-cased
  ``break``) -- catches a protocol command being added/renamed/removed in
  the daemon without updating the generator to match.
"""

from __future__ import annotations

from pathlib import Path

import generate_protocol_reference as gpr

from tricca_autopipette.daemon.service import _LINE_DISPATCH, _STR_ARG_DISPATCH

_REFERENCE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "protocol-command-reference.md"
)


def test_committed_reference_matches_generator_output() -> None:
    """The committed file must equal the generator's current output.

    A mismatch means either the Markdown was hand-edited, or a
    ``TAPCmdParsers`` parser/description changed without regenerating --
    run ``python scripts/generate_protocol_reference.py`` and commit the
    result.
    """
    committed = _REFERENCE_PATH.read_text(encoding="utf-8")
    generated = gpr.generate()

    assert committed == generated, (
        "docs/protocol-command-reference.md is stale -- regenerate it with "
        "`python scripts/generate_protocol_reference.py` and commit the "
        "result."
    )


def test_command_list_matches_real_protocol_dispatch_tables() -> None:
    """``_COMMANDS``'s names must match the daemon's real dispatch tables.

    Guards the generator's coverage itself: without this, a command added
    to ``_LINE_DISPATCH``/``_STR_ARG_DISPATCH`` that nobody added to
    ``_COMMANDS`` would just be silently missing from the reference, and a
    stale/renamed entry in ``_COMMANDS`` would document a command that no
    longer exists.
    """
    real_commands = set(_LINE_DISPATCH) | set(_STR_ARG_DISPATCH) | {"break"}
    documented_commands = {doc.name for doc in gpr._COMMANDS}

    missing = real_commands - documented_commands
    assert not missing, (
        f"scripts/generate_protocol_reference.py's _COMMANDS is missing: "
        f"{sorted(missing)} -- add an entry so the reference documents it."
    )
    stale = documented_commands - real_commands
    assert not stale, (
        f"scripts/generate_protocol_reference.py's _COMMANDS documents "
        f"commands no longer dispatched from a protocol file: "
        f"{sorted(stale)} -- AutoPipetteService's dispatch tables must have "
        "changed."
    )
