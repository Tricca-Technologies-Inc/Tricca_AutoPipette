#!/usr/bin/env python3
"""Generate ``docs/protocol-command-reference.md`` from the real parsers.

A ``.pipette`` protocol file's grammar is exactly the interactive shell's
own -- ``commands/tap_cmd_parsers.py``'s ``TAPCmdParsers`` is the
authoritative source (see CLAUDE.md), and this script walks it to render
one Markdown section per command that ``AutoPipetteService`` actually
dispatches from a protocol-file line. That command set is fixed here as
:data:`_COMMANDS` (mirroring ``daemon/service.py``'s ``_LINE_DISPATCH``/
``_STR_ARG_DISPATCH``, which aren't imported directly since they're private
to that module) rather than dumping every ``TAPCmdParsers`` parser --
diagnostic/reporting commands like ``send``/``ws_status``/``ls`` are real
shell commands but are deliberately not protocol-file-dispatchable at all
(see ``_LINE_DISPATCH``'s docstring), so listing them here would document
syntax a protocol file can't actually use.

Run directly to regenerate the committed file:

    python scripts/generate_protocol_reference.py

``tests/docs/test_protocol_reference_freshness.py`` asserts the committed
file matches this script's current output, and that :data:`_COMMANDS`'s
names match ``AutoPipetteService``'s real dispatch tables exactly -- so an
added/renamed/removed protocol command fails CI here rather than letting
the reference silently drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cmd2 import Cmd2ArgumentParser

from tricca_autopipette.commands.tap_cmd_parsers import TAPCmdParsers

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_OUTPUT_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "protocol-command-reference.md"
)

_HEADER = """\
<!--
  GENERATED FILE -- do not edit by hand.
  Produced by scripts/generate_protocol_reference.py from
  commands/tap_cmd_parsers.py's TAPCmdParsers. Regenerate with:

      python scripts/generate_protocol_reference.py

  tests/docs/test_protocol_reference_freshness.py fails CI if this file
  drifts from the generator's output.
-->

# Protocol command reference

Every command a `.pipette` protocol file may use, one per line, in the
order `tap`'s `run <path>`/the daemon's protocol replay dispatch them.
This is the generated syntax reference; for a task-oriented walkthrough of
writing a protocol file, see
[`protocol-authoring.md`](protocol-authoring.md).
"""


@dataclass(frozen=True)
class _CommandDoc:
    """One documented protocol-file command.

    Attributes:
        name: The bare command name as it appears at the start of a
            protocol-file line.
        parser: The command's ``Cmd2ArgumentParser``, or None for a command
            with no argparse parser (either it takes no arguments, or it
            takes one bare string argument -- see `manual_usage`).
        manual_usage: A hand-written ``Usage:`` line plus description, for
            a command with no `parser` to generate one from.
    """

    name: str
    parser: Cmd2ArgumentParser | None = None
    manual_usage: str | None = None

    def __post_init__(self) -> None:
        """Validate that exactly one of `parser`/`manual_usage` is set.

        Raises:
            ValueError: If both or neither are set.
        """
        if (self.parser is None) == (self.manual_usage is None):
            raise ValueError(
                f"{self.name!r} must set exactly one of parser/manual_usage"
            )


#: One entry per protocol-file-dispatchable command, grouped and ordered to
#: match `CLAUDE.md`'s shell-composition command-set groups. Keep this in
#: sync with `daemon/service.py`'s `_LINE_DISPATCH`/`_STR_ARG_DISPATCH`
#: (plus the special-cased `break`) -- the freshness test asserts the name
#: sets match exactly.
_COMMANDS: list[_CommandDoc] = [
    # -- Movement -----------------------------------------------------------
    _CommandDoc(
        "init",
        manual_usage=(
            "Usage: init\n\n"
            "Initialise the pipette: set the coordinate system and speed, "
            "then home every motor. Exempt from the homed-safety interlock "
            "-- this is what performs homing."
        ),
    ),
    _CommandDoc("home", parser=TAPCmdParsers.parser_home),
    _CommandDoc("move", parser=TAPCmdParsers.parser_move),
    _CommandDoc("move_loc", parser=TAPCmdParsers.parser_move_loc),
    _CommandDoc("move_rel", parser=TAPCmdParsers.parser_move_rel),
    # -- Pipetting ------------------------------------------------------------
    _CommandDoc("aspirate", parser=TAPCmdParsers.parser_aspirate),
    _CommandDoc("dispense", parser=TAPCmdParsers.parser_dispense),
    _CommandDoc("pipette", parser=TAPCmdParsers.parser_pipette),
    _CommandDoc(
        "next_tip",
        manual_usage=(
            "Usage: next_tip\n\n"
            "Pick up the next available tip from the configured "
            "tipbox(es), drawing in registration order."
        ),
    ),
    _CommandDoc(
        "eject_tip",
        manual_usage=(
            "Usage: eject_tip\n\n"
            "Eject the current tip in place -- unlike dispose_tip, this "
            "does not move to the waste container first."
        ),
    ),
    _CommandDoc(
        "dispose_tip",
        manual_usage=(
            "Usage: dispose_tip\n\n"
            "Move to the configured waste container and eject the current "
            "tip into it."
        ),
    ),
    _CommandDoc(
        "change_tip",
        manual_usage=(
            "Usage: change_tip\n\n"
            "Dispose the current tip (if any) and pick up a fresh one."
        ),
    ),
    _CommandDoc(
        "switch_liquid",
        manual_usage=(
            "Usage: switch_liquid <liquid_name>\n\n"
            "Switch the active liquid profile to an already-loaded one "
            "(see load_liquid). Affects the technique -- speeds, waits, "
            "prewet, air gaps -- used by subsequent aspirate/dispense/"
            "pipette commands."
        ),
    ),
    _CommandDoc(
        "load_liquid",
        manual_usage=(
            "Usage: load_liquid <filename>\n\n"
            "Load a new liquid profile from config/liquids/. Does not "
            "activate it -- follow with switch_liquid."
        ),
    ),
    # -- Configuration & locations --------------------------------------------
    _CommandDoc("set", parser=TAPCmdParsers.parser_set),
    _CommandDoc("coor", parser=TAPCmdParsers.parser_coor),
    _CommandDoc("plate", parser=TAPCmdParsers.parser_plate),
    _CommandDoc("reset_plate", parser=TAPCmdParsers.parser_reset_plate),
    _CommandDoc(
        "reset_plates",
        manual_usage=(
            "Usage: reset_plates\n\nReset every plate's traversal cursor "
            "to its first well."
        ),
    ),
    _CommandDoc("del_loc", parser=TAPCmdParsers.parser_del_loc),
    _CommandDoc(
        "clear_locs",
        manual_usage="Usage: clear_locs\n\nDelete every location on the deck.",
    ),
    _CommandDoc("load_locations", parser=TAPCmdParsers.parser_load_locations),
    _CommandDoc("unload_locations", parser=TAPCmdParsers.parser_unload_locations),
    _CommandDoc(
        "save_locations",
        manual_usage=(
            "Usage: save_locations [filename]\n\n"
            "Save the current deck to config/locations/. filename defaults "
            "to 'custom_locations.json' when omitted on a protocol-file "
            "line."
        ),
    ),
    _CommandDoc("reset_tips", parser=TAPCmdParsers.parser_reset_tips),
    _CommandDoc(
        "reset_tips_all",
        manual_usage=("Usage: reset_tips_all\n\nMark every configured tipbox as full."),
    ),
    _CommandDoc("set_tips", parser=TAPCmdParsers.parser_set_tips),
    _CommandDoc("tips", parser=TAPCmdParsers.parser_tips),
    # -- Utility --------------------------------------------------------------
    _CommandDoc("wait", parser=TAPCmdParsers.parser_wait),
    _CommandDoc("trigger", parser=TAPCmdParsers.parser_trigger),
    _CommandDoc("gcode_print", parser=TAPCmdParsers.parser_gcode_print),
    _CommandDoc("vol_to_steps", parser=TAPCmdParsers.parser_vol_to_steps),
    # -- Control flow -----------------------------------------------------------
    _CommandDoc(
        "break",
        manual_usage=(
            "Usage: break\n\n"
            "Pause the running protocol and wait for an operator (or "
            "remote client) to confirm continue/abort -- not a real "
            "AutoPipetteService method, handled specially by the protocol "
            "dispatch loop. Choosing abort raises ProtocolAbortedError and "
            "stops the rest of the file from running."
        ),
    ),
]


def _strip_ansi(text: str) -> str:
    """Remove ANSI colour escapes from rich-argparse's help output.

    Args:
        text: Help/usage text as produced by a `Cmd2ArgumentParser`, which
            renders in colour via rich-argparse regardless of TTY.

    Returns:
        The same text with every ANSI SGR escape sequence removed.
    """
    return _ANSI_ESCAPE_RE.sub("", text)


def _render_command(doc: _CommandDoc) -> str:
    """Render one command's Markdown section.

    Args:
        doc: The command to render.

    Returns:
        A Markdown section: a `###` heading followed by a fenced usage/help
        block.
    """
    if doc.parser is not None:
        doc.parser.prog = doc.name
        body = _strip_ansi(doc.parser.format_help()).rstrip()
    else:
        assert doc.manual_usage is not None  # guaranteed by __post_init__
        body = doc.manual_usage
    return f"### `{doc.name}`\n\n```\n{body}\n```\n"


def generate() -> str:
    """Build the full Markdown reference document.

    Returns:
        The complete file contents, ready to write to
        `docs/protocol-command-reference.md`.
    """
    sections = [_render_command(doc) for doc in _COMMANDS]
    return _HEADER + "\n" + "\n".join(sections)


def main() -> None:
    """Regenerate `docs/protocol-command-reference.md` on disk."""
    _OUTPUT_PATH.write_text(generate(), encoding="utf-8")
    print(f"Wrote {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
