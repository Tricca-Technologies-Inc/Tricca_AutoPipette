"""Unit tests for ``AutoPipetteService``'s movement commands (Phase 1 of the

ports-and-adapters migration -- see CLAUDE.md). Exercises the same typed
methods that both ``commands/movement_commands.py``'s cmd2 adapter and
``ControlServer``'s ``movement.*`` RPC dispatch call into, using the real
``AutoPipette`` domain layer with an unconnected (``connect_websocket=False``)
shell and a ``FakeMoonrakerState`` standing in for live homed-axes state.
"""

from __future__ import annotations

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import (
    HomeArgs,
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
)
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import NotALocationError, NotHomedError
from tricca_autopipette.daemon.service import AutoPipetteService


class TestInit:
    def test_marks_homed_and_returns_ok(self, service: AutoPipetteService) -> None:
        result = service.init()

        assert result.ok is True
        assert service._autopipette.state.homed is True


class TestHome:
    def test_all_delegates_to_init_pipette(self, service: AutoPipetteService) -> None:
        result = service.home(HomeArgs(motors="all"))

        assert result.ok is True
        assert service._autopipette.state.homed is True

    def test_single_motor(self, service: AutoPipetteService) -> None:
        result = service.home(HomeArgs(motors="z"))

        assert result.ok is True
        assert "z" in result.message

    def test_invalid_motor_raises_value_error(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(ValueError, match="not a valid motor specification"):
            service.home(HomeArgs(motors="doesnotexist"))

    def test_does_not_require_homed(self, service: AutoPipetteService) -> None:
        # "home"/"init" are exempt from the homed interlock -- they're what
        # perform homing in the first place.
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(False)

        result = service.home(HomeArgs(motors="x"))

        assert result.ok is True


class TestMove:
    def test_requires_homed(self, service: AutoPipetteService) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service.move(MoveArgs(x=10.0, y=20.0, z=5.0))

    def test_succeeds_when_homed(self, service: AutoPipetteService) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)

        result = service.move(MoveArgs(x=10.0, y=20.0, z=5.0))

        assert result.ok is True
        assert "10.0" in result.message


class TestMoveLoc:
    def test_requires_homed(self, service: AutoPipetteService) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service.move_loc(MoveLocArgs(name_loc="anywhere", row=None, col=None))

    def test_unknown_location_raises_not_a_location_error(
        self, service: AutoPipetteService
    ) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)

        with pytest.raises(NotALocationError):
            service.move_loc(MoveLocArgs(name_loc="nope", row=None, col=None))

    def test_succeeds_for_a_known_location(self, service: AutoPipetteService) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)
        service._autopipette.location_manager.set_coordinate(
            "bench", Coordinate(x=1.0, y=2.0, z=3.0)
        )

        result = service.move_loc(MoveLocArgs(name_loc="bench", row=None, col=None))

        assert result.ok is True
        assert "bench" in result.message


class TestMoveRel:
    def test_all_zero_offsets_raises_not_homed_when_unhomed(
        self, service: AutoPipetteService
    ) -> None:
        # Phase 3's `require_homed` decorator wraps the whole method, so the
        # homed check always runs before the all-zero-offset no-op check --
        # a behavior change from the pre-Phase-3 ordering (see
        # `daemon/service.py`'s Pipette-commands-group comment), made for
        # consistency with the 6 other gated methods that always checked
        # homed first.
        with pytest.raises(NotHomedError, match="not homed"):
            service.move_rel(MoveRelArgs(x=0.0, y=0.0, z=0.0))

    def test_all_zero_offsets_is_a_noop_when_homed(
        self, service: AutoPipetteService
    ) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)

        result = service.move_rel(MoveRelArgs(x=0.0, y=0.0, z=0.0))

        assert result.ok is False
        assert "zero" in result.message

    def test_requires_homed_for_a_real_offset(
        self, service: AutoPipetteService
    ) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service.move_rel(MoveRelArgs(x=5.0, y=0.0, z=0.0))

    def test_succeeds_when_homed(self, service: AutoPipetteService) -> None:
        # NOTE: a genuinely negative offset (e.g. z=-2.0) currently raises a
        # pydantic ValidationError from `Coordinate` (which requires all
        # fields >= 0, being meant for absolute positions) -- this is a
        # pre-existing bug inherited verbatim from the original
        # `do_move_rel`, not something introduced by this migration, and out
        # of scope to fix here.
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)

        result = service.move_rel(MoveRelArgs(x=5.0, y=0.0, z=2.0))

        assert result.ok is True
        assert "X+5.00" in result.message
        assert "Z+2.00" in result.message
