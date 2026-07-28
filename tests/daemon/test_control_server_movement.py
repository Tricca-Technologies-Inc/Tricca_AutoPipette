"""Integration tests for ``ControlServer``'s ``movement.*`` RPC dispatch.

Calls ``ControlServer._call`` directly with a real ``AutoPipetteService`` --
no real aiohttp socket/event loop needed for this, just `asyncio.run` around
the coroutine -- to verify the dispatch table (added in Phase 1 of the
ports-and-adapters migration, see CLAUDE.md) actually routes each
`movement.*` method name to the right service method with the right
dataclass built from the wire `params` dict.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.daemon.control_server import ControlServer
from tricca_autopipette.daemon.service import AutoPipetteService


def _call(
    server: ControlServer, method: str, params: dict[str, object]
) -> dict[str, Any]:
    """Dispatch one control-plane RPC, returning its CommandResult-shaped dict."""
    return asyncio.run(server._call(method, params))


class TestMovementDispatch:
    def test_movement_init(self, service: AutoPipetteService) -> None:
        server = ControlServer(service)

        result = _call(server, "movement.init", {})

        assert result["ok"] is True
        assert service._autopipette.state.homed is True

    def test_movement_home(self, service: AutoPipetteService) -> None:
        server = ControlServer(service)

        result = _call(server, "movement.home", {"motors": "axis"})

        assert result["ok"] is True
        assert "axis" in result["message"]

    def test_movement_move_requires_homed(self, service: AutoPipetteService) -> None:
        server = ControlServer(service)

        try:
            _call(server, "movement.move", {"x": 1.0, "y": 2.0, "z": 3.0})
        except NotHomedError as exc:
            assert "not homed" in str(exc)
        else:
            raise AssertionError("expected NotHomedError for an unhomed move")

    def test_movement_move_when_homed(self, service: AutoPipetteService) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)
        server = ControlServer(service)

        result = _call(server, "movement.move", {"x": 1.0, "y": 2.0, "z": 3.0})

        assert result["ok"] is True

    def test_movement_move_loc_routes_params_into_move_loc_args(
        self, service: AutoPipetteService
    ) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)
        service._autopipette.location_manager.set_coordinate(
            "bench", Coordinate(x=1, y=2, z=3)
        )
        server = ControlServer(service)

        result = _call(
            server, "movement.move_loc", {"name_loc": "bench", "row": None, "col": None}
        )

        assert result["ok"] is True
        assert "bench" in result["message"]

    def test_movement_move_rel_all_zero_is_a_noop(
        self, service: AutoPipetteService
    ) -> None:
        # `require_homed` always runs first (Phase 3), so this needs a
        # homed machine to reach the all-zero-offset no-op check at all --
        # see the equivalent test in test_service_movement.py.
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        service.moonraker_state.set_homed(True)
        server = ControlServer(service)

        result = _call(server, "movement.move_rel", {"x": 0.0, "y": 0.0, "z": 0.0})

        assert result["ok"] is False
