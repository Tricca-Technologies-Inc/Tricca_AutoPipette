"""Stage selection, seeding and gating of the stage-2 plunger (issue #147).

Klipper's axis config, plunger homed state and reported P position are faked
at the Moonraker boundary (``FakeMoonrakerState``). The stage comes only from
the discovered ``AxisConfig``: stage 1 and unconfigured machines keep today's
relative ``MANUAL_STEPPER`` moves and refuse nothing new.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import AspirateArgs, DispenseArgs
from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.core.pipette_models import (
    AbsolutePlunger,
    FluidDisplacement,
    TipState,
)
from tricca_autopipette.core.volume_converter import VolumeConverter
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PipetteAxis
from tricca_autopipette.daemon.service import AutoPipetteService

STAGE2 = AxisConfig(pipette=PipetteAxis("P", 2, -60.0, 0.0))
STAGE1 = AxisConfig(pipette=PipetteAxis("P", 1, None, None))

ASPIRATE_20 = AspirateArgs(20.0, "plate_a", None, None, 0.0, 0.0, 0, None)


def _fake(service: AutoPipetteService) -> FakeMoonrakerState:
    state = service.moonraker_state
    assert isinstance(state, FakeMoonrakerState)
    return state


@pytest.fixture
def svc(service_with_plates: AutoPipetteService) -> AutoPipetteService:
    """A gantry-homed service with a tip on and a 0.5 mm/μL curve.

    Returns:
        ``service_with_plates``, ready for syringe commands.
    """
    ap = service_with_plates._autopipette
    ap.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 50.0])
    ap.state.tip_state = TipState.ATTACHED
    _fake(service_with_plates).set_homed(True)
    return service_with_plates


def _configure(
    svc: AutoPipetteService,
    axes: AxisConfig,
    *,
    homed: bool = False,
    position: float | None = None,
) -> None:
    fake = _fake(svc)
    fake.axis_config = axes  # type: ignore[misc]
    fake.plunger_homed = homed
    if position is not None:
        fake.positions["P"] = position


class TestStageSelection:
    @pytest.mark.parametrize("axes", [AxisConfig(), STAGE1])
    def test_stage1_and_unconfigured_refuse_nothing_new(
        self, svc: AutoPipetteService, axes: AxisConfig
    ) -> None:
        _configure(svc, axes, homed=False)

        assert svc.aspirate(ASPIRATE_20).ok is True
        assert svc._autopipette.plunger is None

    def test_stage2_refuses_an_unhomed_plunger_before_any_gcode(
        self, svc: AutoPipetteService
    ) -> None:
        _configure(svc, STAGE2, homed=False)

        with pytest.raises(NotHomedError, match="plunger not homed"):
            svc.aspirate(ASPIRATE_20)
        assert svc._autopipette.get_gcode() == []

    def test_stage2_without_soft_limits_fails_closed(
        self, svc: AutoPipetteService
    ) -> None:
        _configure(svc, AxisConfig(pipette=PipetteAxis("P", 2, None, None)), homed=True)

        with pytest.raises(ValueError, match="limits"):
            svc.aspirate(ASPIRATE_20)


class TestSeeding:
    def test_a_command_starts_from_klippers_reported_position(
        self, svc: AutoPipetteService
    ) -> None:
        _configure(svc, STAGE2, homed=True, position=-10.0)
        svc._autopipette.state.has_liquid = True

        svc.dispense(DispenseArgs("plate_a", None, None, 10.0, False))

        plunger = svc._autopipette.plunger
        assert plunger is not None
        assert plunger.position_mm == pytest.approx(-5.0)

    def test_a_refused_command_leaves_no_gcode_for_the_next_one(
        self, svc: AutoPipetteService
    ) -> None:
        _configure(svc, STAGE2, homed=True, position=-1.0)
        svc._autopipette.state.has_liquid = True

        with pytest.raises(ValueError, match="outside"):
            svc.dispense(DispenseArgs("plate_a", None, None, 10.0, False))
        assert svc._autopipette.get_gcode() == []


class TestProtocols:
    @pytest.fixture(autouse=True)
    def _protocols_in_tmp(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", tmp_path)

    def _write(self, tmp_path: Path, *lines: str) -> str:
        (tmp_path / "p.pipette").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "p.pipette"

    def test_g28_p_in_the_same_batch_seeds_zero(
        self, svc: AutoPipetteService, tmp_path: Path
    ) -> None:
        _configure(svc, STAGE2, homed=False)
        name = self._write(
            tmp_path,
            "home pipette",
            "aspirate 20 plate_a --pre_air_gap 0 --post_air_gap 0 --prewet 0",
        )
        manager = svc.gcode_manager

        with patch.object(
            manager, "write_gcode_file", wraps=manager.write_gcode_file
        ) as spy:
            svc._run_protocol_sync(name)

        gcode = [g.rstrip("\n") for g in spy.call_args.args[0]]
        assert "G28 P" in gcode
        assert [g for g in gcode if g.startswith("G1 P")] == [
            f"G1 P-10.0 F{svc._autopipette.syringe.speed_aspirate * 60}"
        ]
        assert not any("MANUAL_STEPPER" in g for g in gcode)

    def test_validation_works_on_an_unhomed_machine_and_reports_limits(
        self, svc: AutoPipetteService, tmp_path: Path
    ) -> None:
        _configure(svc, STAGE2, homed=False)
        _fake(svc).set_homed(False)
        # 0.7 mm/μL: 90 μL is 63 mm, past the -60 limit but within capacity.
        svc._autopipette.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 70.0])
        name = self._write(
            tmp_path,
            "aspirate 20 plate_a --pre_air_gap 0 --post_air_gap 0 --prewet 0",
            "aspirate 90 plate_a --pre_air_gap 0 --post_air_gap 0 --prewet 0",
        )

        findings = svc.validate_protocol(name).data or {}

        errors = [f for f in findings["findings"] if f["severity"] == "error"]
        assert [f["line_number"] for f in errors] == [2]
        assert "outside" in errors[0]["message"]


class TestRollback:
    def test_snapshot_restores_the_model_and_gantry_accel(
        self, svc: AutoPipetteService
    ) -> None:
        ap = svc._autopipette
        ap.plunger = AbsolutePlunger("P", -60.0, 0.0, -7.0)
        accel = ap.gantry_accel

        with pytest.raises(RuntimeError), svc.domain_state_snapshot():
            ap.set_max_accel(accel + 1)
            ap.operate_syringe(FluidDisplacement.aspiration, 10.0)
            raise RuntimeError("compile-time failure")

        assert ap.plunger is not None
        assert ap.plunger.position_mm == pytest.approx(-7.0)
        assert ap.gantry_accel == accel
