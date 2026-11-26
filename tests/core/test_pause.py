"""Tests for pauses that stop the machine itself.

A protocol is compiled to one G-code file before anything moves, so a pause
has to be in the G-code: ``M117 <reason>`` then Klipper's ``PAUSE``, which
the operator answers with Resume. Used by ``break`` and, during a run, by a
tipbox running out (Scott's c5e549e, moved from compile time to the
machine).
"""

from __future__ import annotations

import logging

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.gcode_commands import GCodeCommands
from tricca_autopipette.core.pipette_exceptions import OutOfTipsError
from tricca_autopipette.core.pipette_models import TipState


def _lines(ap: AutoPipette) -> list[str]:
    return [line.strip() for line in ap.get_gcode() if not line.startswith(";")]


def test_the_pause_builder() -> None:
    assert GCodeCommands().pause() == "PAUSE\n"


def test_pause_shows_the_reason_then_pauses(autopipette: AutoPipette) -> None:
    autopipette.get_gcode()

    autopipette.pause("Reload tips")

    assert _lines(autopipette) == ["M400", "M117 Reload tips", "PAUSE"]


def _drain(ap: AutoPipette) -> int:
    """Take every tip, dropping each.

    Returns:
        How many tips were taken.
    """
    taken = 0
    while ap.location_manager.tipbox_manager.peek_tip() is not None:
        ap.next_tip()
        ap.state.tip_state = TipState.DETACHED
        taken += 1
    return taken


def test_running_out_raises_outside_a_run(pipette_with_plates: AutoPipette) -> None:
    ap = pipette_with_plates
    _drain(ap)

    with pytest.raises(OutOfTipsError):
        ap.next_tip()


def test_running_out_in_a_run_pauses_for_a_reload(
    pipette_with_plates: AutoPipette, caplog: pytest.LogCaptureFixture
) -> None:
    ap = pipette_with_plates
    ap.pause_when_out_of_tips = True
    taken = _drain(ap)
    ap.get_gcode()

    with caplog.at_level(logging.WARNING):
        ap.next_tip()

    lines = _lines(ap)
    assert lines[:3] == [
        "M400",
        "M117 Out of tips: reload tipbox, then Resume",
        "PAUSE",
    ]
    assert "Out of tips" in caplog.text
    # The model assumes a full box after the reload, less the tip just taken.
    assert ap.location_manager.tipbox_manager.remaining == taken - 1
    assert ap.state.tip_state == TipState.ATTACHED
