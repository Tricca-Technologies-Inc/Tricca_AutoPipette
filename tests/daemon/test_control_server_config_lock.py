"""The config run-lock at the control plane (issue #33, slice b)."""

from __future__ import annotations

import asyncio
from typing import Any

from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.daemon.control_server import ControlServer
from tricca_autopipette.daemon.service import AutoPipetteService, RunStatus


def test_run_status_reports_the_config_lock(service: AutoPipetteService) -> None:
    server = ControlServer(service)
    assert asyncio.run(server._call("run.status", {}))["config_locked"] is False

    service._current = RunStatus(status="running", filename="a.pipette")

    assert asyncio.run(server._call("run.status", {}))["config_locked"] is True


def test_run_status_reports_effective_homing_and_connection(
    service: AutoPipetteService,
) -> None:
    server = ControlServer(service)
    assert asyncio.run(server._call("run.status", {}))["homed"] is None
    client = FakeWebSocketClient(connected=True)
    service.client = client  # type: ignore[assignment]
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    assert asyncio.run(server._call("run.status", {}))["homed"] is False
    service.moonraker_state.set_homed(True)
    assert asyncio.run(server._call("run.status", {}))["homed"] is True
    service._homing_invalidated = True
    assert asyncio.run(server._call("run.status", {}))["homed"] is False
    client.set_connected(False)
    assert asyncio.run(server._call("run.status", {}))["homed"] is None


def test_refusal_does_not_wait_for_the_run_to_release_the_dispatch_lock(
    service: AutoPipetteService,
) -> None:
    """A run holds the dispatch lock for its whole replay (maybe a breakpoint)."""
    server = ControlServer(service)
    service._current = RunStatus(status="running", filename="a.pipette")

    async def call_while_replaying() -> Any:
        async with service._lock:
            return await asyncio.wait_for(
                server._call("config.unload_liquid", {"liquid_name": "methanol"}),
                timeout=1,
            )

    result = asyncio.run(call_while_replaying())

    assert result["ok"] is False
    assert result["data"] == {"reason": "run_active"}
