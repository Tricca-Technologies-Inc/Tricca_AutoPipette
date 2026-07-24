"""Unit tests for ``AutoPipetteService``'s utility commands (Phase 1 of the

ports-and-adapters migration, UtilityCommands group -- see CLAUDE.md).
Unlike other groups, every command here is migrated, including the
read-only ones (webcam, vol_to_steps, steps_to_vol), since each does a real
domain computation/lookup rather than rendering a `rich.table.Table`.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.commands.tap_cmd_parsers import (
    GcodePrintArgs,
    TriggerArgs,
    VolToStepsArgs,
    WaitArgs,
)
from tricca_autopipette.daemon.service import AutoPipetteService


class TestWait:
    def test_non_positive_duration_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.wait(WaitArgs(ms=0.0))

        assert result.ok is False
        assert "greater than zero" in result.message

    def test_emits_a_dwell(self, service: AutoPipetteService) -> None:
        result = service.wait(WaitArgs(ms=500.0))

        assert result.ok is True
        assert "500" in result.message


class TestTrigger:
    def test_invalid_channel_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.trigger(TriggerArgs(channel="nope", state="on"))

        assert result.ok is False
        assert "Invalid channel" in result.message

    def test_invalid_state_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.trigger(TriggerArgs(channel="air", state="nope"))

        assert result.ok is False
        assert "Invalid state" in result.message

    def test_valid_channel_reports_not_yet_implemented(
        self, service: AutoPipetteService
    ) -> None:
        result = service.trigger(TriggerArgs(channel="air", state="on"))

        assert result.ok is False
        assert "not yet implemented" in result.message
        assert "air" in result.message
        assert "on" in result.message


class TestGcodePrint:
    def test_empty_message_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.gcode_print(GcodePrintArgs(msg="   "))

        assert result.ok is False
        assert "empty" in result.message

    def test_queues_a_display_message(self, service: AutoPipetteService) -> None:
        result = service.gcode_print(GcodePrintArgs(msg="Protocol started"))

        assert result.ok is True
        assert "Protocol started" in result.message


class TestWebcamUrl:
    def test_builds_a_url_from_hostname(self, service: AutoPipetteService) -> None:
        result = service.webcam_url()

        assert result.ok is True
        assert result.data is not None
        assert result.data["url"].startswith("http://")
        assert result.data["url"].endswith("/webcam/?action=stream")
        assert result.message == result.data["url"]


class TestVolToSteps:
    def test_non_positive_volume_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.vol_to_steps(VolToStepsArgs(vol=0.0))

        assert result.ok is False
        assert "greater than zero" in result.message

    def test_converts_volume_to_steps(self, service: AutoPipetteService) -> None:
        result = service.vol_to_steps(VolToStepsArgs(vol=100.0))

        assert result.ok is True
        assert result.data is not None
        assert result.data["steps"] > 0
        assert result.data["round_trip_vol"] == pytest.approx(100.0, rel=0.05)


class TestStepsToVol:
    def test_negative_steps_is_a_noop(self, service: AutoPipetteService) -> None:
        result = service.steps_to_vol(-5)

        assert result.ok is False
        assert "negative" in result.message

    def test_converts_steps_to_volume(self, service: AutoPipetteService) -> None:
        forward = service.vol_to_steps(VolToStepsArgs(vol=100.0))
        assert forward.data is not None
        steps = round(forward.data["steps"])

        result = service.steps_to_vol(steps)

        assert result.ok is True
        assert result.data is not None
        assert result.data["vol"] == pytest.approx(100.0, rel=0.05)
