"""Homing with Klipper's plate and plunger axes (issue #146, TAP-5).

Klipper's axis config is faked at the Moonraker boundary
(``FakeMoonrakerState.axis_config``); the G-code is read back through
``GCodeManager``'s batch mode, the same buffer a protocol run uploads.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import HomeArgs
from tricca_autopipette.core.gcode_commands import GCode
from tricca_autopipette.daemon.moonraker_state import (
    AxisConfig,
    PipetteAxis,
    PlateAxis,
)
from tricca_autopipette.daemon.service import AutoPipetteService

AXES = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 350.0)),
    ),
    z_safe=5.0,
    park_tol=0.5,
    pipette=PipetteAxis("P", 1, None, None),
)


def _emitted(service: AutoPipetteService, call: Callable[[], object]) -> list[GCode]:
    service.gcode_manager.start_batch()
    call()
    gcode = service.gcode_manager.end_batch()
    return [g for g in gcode if g.strip() and not g.startswith(";")]


def _configure(service: AutoPipetteService, axes: AxisConfig = AXES) -> None:
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.axis_config = axes  # type: ignore[misc]


class TestFullHome:
    @pytest.mark.parametrize("motors", ["all", None])
    def test_bare_g28_replaces_manual_stepper_plunger_homing(
        self, service: AutoPipetteService, motors: str | None
    ) -> None:
        _configure(service)
        gcode = _emitted(
            service,
            service.init if motors is None else lambda: service.home(HomeArgs(motors)),
        )

        assert "G28\n" in gcode
        assert not any(g.startswith("MANUAL_STEPPER") for g in gcode)
        assert gcode[0] == "G90\n"
        assert any(g.startswith("SET_SERVO") for g in gcode)

    def test_unchanged_without_plunger_axis(self, service: AutoPipetteService) -> None:
        before = _emitted(service, service.init)
        _configure(service, AxisConfig(plates=AXES.plates))
        after = _emitted(service, service.init)

        assert after == before
        assert any(g.startswith("MANUAL_STEPPER") for g in before)

    def test_clears_homing_invalidated(self, service: AutoPipetteService) -> None:
        _configure(service)
        service._homing_invalidated = True
        _emitted(service, service.init)
        assert service._homing_invalidated is False


class TestHomePipette:
    def test_emits_g28_p(self, service: AutoPipetteService) -> None:
        _configure(service)
        gcode = _emitted(service, lambda: service.home(HomeArgs("pipette")))

        assert "G28 P\n" in gcode
        assert not any(g.startswith("MANUAL_STEPPER") for g in gcode)
        assert any(g.startswith("SET_SERVO") for g in gcode)

    def test_unchanged_without_plunger_axis(self, service: AutoPipetteService) -> None:
        gcode = _emitted(service, lambda: service.home(HomeArgs("pipette")))

        assert any(g.startswith("MANUAL_STEPPER") for g in gcode)
        assert not any(g.startswith("G28") for g in gcode)


class TestHomePlates:
    def test_all_plates_by_configured_letters(
        self, service: AutoPipetteService
    ) -> None:
        _configure(service)
        gcode = _emitted(service, lambda: service.home(HomeArgs("plates")))
        assert gcode == ["G28 U V\n"]

    @pytest.mark.parametrize("target", ["plate2", "PLATE2", "v", "V"])
    def test_one_plate_by_name_or_letter(
        self, service: AutoPipetteService, target: str
    ) -> None:
        _configure(service)
        gcode = _emitted(service, lambda: service.home(HomeArgs(target)))
        assert gcode == ["G28 V\n"]

    def test_does_not_clear_homing_invalidated(
        self, service: AutoPipetteService
    ) -> None:
        _configure(service)
        service._homing_invalidated = True
        _emitted(service, lambda: service.home(HomeArgs("plates")))
        assert service._homing_invalidated is True

    def test_refused_when_no_plates_configured(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(ValueError, match="No plates configured"):
            service.home(HomeArgs("plates"))

    def test_unknown_target_lists_plate_names(
        self, service: AutoPipetteService
    ) -> None:
        _configure(service)
        with pytest.raises(ValueError, match=r"Valid options:.*plate1.*plate2.*plates"):
            service.home(HomeArgs("plate9"))
