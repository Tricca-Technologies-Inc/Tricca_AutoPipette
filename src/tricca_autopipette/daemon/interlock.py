"""Recognise Klipper interlock refusals in Moonraker error text (issue #150).

Klipper's collision interlock (Tricca_Autopipette_Configs ``plate-macros.cfg``,
umbrella plan §6.3) is the authority: it refuses a move by raising a G-code
error. tapd only recognises that text so it can report *which* guard refused,
on *which* axis, and why, instead of a generic failure. Two shapes exist:

- ``Move refused by interlock: <reason>`` -- the ``G1``/``G0`` wrapper and
  every check that reuses it (``SET_GCODE_OFFSET MOVE=1``,
  ``RESTORE_GCODE_STATE MOVE=1`` and therefore ``RESUME``, ``PLATE_MOVE``).
- ``<COMMAND> [on <stepper>] refused: <reason>`` -- command-specific guards
  (``STEPPER_BUZZ``, ``MANUAL_STEPPER``, ``HOME_PLATE``, ...).

Matching is on those stable prefixes only; the reason is carried verbatim, so
a Klipper-side rewording (e.g. D45's "mid-travel" -> "not at a tip-safe
position") needs no change here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INTERLOCK = re.compile(r"Move refused by interlock: (?P<reason>.+)")
_COMMAND = re.compile(
    r"\b(?P<rule>[A-Z][A-Z0-9_]*(?: [A-Z0-9_]+=\S+)?)"
    r"(?: on (?P<axis>\S+))? refused: (?P<reason>.+)"
)


@dataclass(frozen=True)
class InterlockRefusal:
    """One Klipper interlock refusal.

    Attributes:
        rule: The guard that refused: ``"interlock"`` for the shared move
            check, otherwise the refusing command (e.g. ``"STEPPER_BUZZ"``).
        axis: The axis or stepper named (``"Z"``, ``"plate1"``,
            ``"plunger"``, ``"stepper_z"``), or None if the text names none.
        reason: Klipper's reason text, verbatim.
        text: The whole refusal message, verbatim.
    """

    rule: str
    axis: str | None
    reason: str
    text: str


def parse_interlock_refusal(text: str) -> InterlockRefusal | None:
    """Find an interlock refusal in an error message.

    Args:
        text: A Klipper/Moonraker error message, e.g. a JSON-RPC error's
            ``message`` or ``print_stats.message``.

    Returns:
        The refusal, or None if ``text`` isn't one.

    Example:
        >>> parse_interlock_refusal("Move refused by interlock: plate1 not homed").axis
        'plate1'
        >>> parse_interlock_refusal("Must home axis first") is None
        True
    """
    if match := _INTERLOCK.search(text):
        reason = match["reason"]
        # Every reason names its axis first, except the tip-height check (Z).
        axis = "Z" if reason.startswith("tip ") else reason.split()[0]
        return InterlockRefusal("interlock", axis, reason, match[0])
    if match := _COMMAND.search(text):
        return InterlockRefusal(match["rule"], match["axis"], match["reason"], match[0])
    return None
