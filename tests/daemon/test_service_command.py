"""``AutoPipetteService.command``: one typed command line, from the kiosk.

The kiosk's command entry sends one line, and the daemon runs it through
the same dispatch a protocol line goes through, so the same parsers, homed
gates and bounds apply. Only an allowlist of motion, tip and pipetting
commands may run this way. Config edits, file writes, raw G-code and
triggers stay ``tap`` and protocol-file only, and nothing runs while a
protocol does.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.commands.tap_cmd_parsers import VolToMmArgs
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus


def test_runs_an_allowed_command(service: AutoPipetteService) -> None:
    result = service.command("vol_to_mm 10")

    assert result.ok is True
    assert result.message == service.vol_to_mm(VolToMmArgs(vol=10.0)).message


@pytest.mark.parametrize(
    "line",
    [
        "gcode_print hi",
        "set_config gantry default.json speed_xy 1",
        "save_locations x.json",
        "trigger air on",
        "break",
    ],
)
def test_refuses_a_command_outside_the_allowlist(
    service: AutoPipetteService, line: str
) -> None:
    result = service.command(line)

    assert result.ok is False
    assert "can't be run from the kiosk" in result.message


def test_refuses_more_than_one_line(service: AutoPipetteService) -> None:
    result = service.command("vol_to_mm 10\nvol_to_mm 20")

    assert result.ok is False
    assert "one command" in result.message


def test_bad_arguments_come_back_as_a_refusal(service: AutoPipetteService) -> None:
    result = service.command("vol_to_mm abc")

    assert result.ok is False
    assert "vol_to_mm" in result.message


def test_an_empty_line_is_refused(service: AutoPipetteService) -> None:
    assert service.command("   ").ok is False


def test_the_homed_gate_still_applies(service: AutoPipetteService) -> None:
    with pytest.raises(NotHomedError):
        service.command("move 10 10 10")


def test_nothing_runs_while_a_protocol_does(service: AutoPipetteService) -> None:
    service._current = RunStatus(status="running", filename="a.pipette")

    result = service.command("vol_to_mm 10")

    assert result.ok is False
    assert result.data == {"reason": "run_active"}
