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
from tricca_autopipette.core.volume_converter import VolumeConverter
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


class TestSeeCalibration:
    def test_unknown_liquid_raises(self, service: AutoPipetteService) -> None:
        with pytest.raises(ValueError, match="not found"):
            service.see_calibration("no_such_liquid")

    def test_defaults_to_the_active_liquid(self, service: AutoPipetteService) -> None:
        autopipette = service._autopipette

        result = service.see_calibration(None)

        assert result.ok is True
        assert result.data is not None
        assert result.data["liquid"] == autopipette.active_liquid

    def test_falls_back_to_pipette_default_when_liquid_has_no_override(
        self, service: AutoPipetteService
    ) -> None:
        # None of the default liquid profiles override calibration -- see
        # config/liquids/*.json -- so every one of them reports the
        # pipette's base curve.
        result = service.see_calibration("water")

        assert result.ok is True
        assert result.data is not None
        assert result.data["source"] == "pipette default"
        syringe = service._autopipette.syringe
        assert result.data["volumes_ul"] == syringe.calibration_volumes
        assert result.data["travel_mm"] == syringe.calibration_steps

    def test_uses_the_liquid_override_when_present(
        self, service: AutoPipetteService
    ) -> None:
        autopipette = service._autopipette
        liquid = autopipette.system_config.liquids["methanol"]
        liquid.calibration_volumes = [0.0, 100.0]
        liquid.calibration_steps = [0.0, 50.0]

        result = service.see_calibration("methanol")

        assert result.ok is True
        assert result.data is not None
        assert result.data["source"] == "liquid override"
        assert result.data["volumes_ul"] == [0.0, 100.0]
        assert result.data["travel_mm"] == [0.0, 50.0]

    def test_slope_and_intercept_match_a_fresh_fit(
        self, service: AutoPipetteService
    ) -> None:
        result = service.see_calibration("water")

        assert result.data is not None
        volumes = result.data["volumes_ul"]
        travel = result.data["travel_mm"]
        expected_slope, expected_intercept = VolumeConverter(
            volumes, travel
        ).get_fit_coefficients()

        assert result.data["slope"] == pytest.approx(expected_slope)
        assert result.data["intercept"] == pytest.approx(expected_intercept)

    def test_does_not_mutate_the_currently_active_converter(
        self, service: AutoPipetteService
    ) -> None:
        """Regression test: inspecting a non-active liquid must not swap

        out `autopipette.volume_converter`, which reflects whichever
        liquid is actually active -- a live run must keep using the
        active liquid's real converter regardless of what's been
        inspected via `see_calibration`.
        """
        autopipette = service._autopipette
        original_converter = autopipette.volume_converter
        liquid = autopipette.system_config.liquids["methanol"]
        liquid.calibration_volumes = [0.0, 100.0]
        liquid.calibration_steps = [0.0, 999.0]

        service.see_calibration("methanol")

        assert autopipette.volume_converter is original_converter
