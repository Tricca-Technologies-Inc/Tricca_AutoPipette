"""Integration test for ``ControlServer``'s ``run.validate`` RPC (issue #36).

Calls ``ControlServer._call`` directly with a real ``AutoPipetteService`` --
same style as ``test_control_server_movement.py`` -- to verify ``run.validate``
routes to ``AutoPipetteService.validate_protocol`` (via the shared
``dispatch`` lock, same as the ``movement.*``/``config.*`` RPCs) and returns
its ``CommandResult``-shaped findings, without requiring a homed machine.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.control_server import ControlServer
from tricca_autopipette.daemon.service import AutoPipetteService


def _call(
    server: ControlServer, method: str, params: dict[str, object]
) -> dict[str, Any]:
    """Dispatch one control-plane RPC, returning its CommandResult-shaped dict.

    Returns:
        The RPC response as a `CommandResult`-shaped dict.
    """
    return asyncio.run(server._call(method, params))


@pytest.fixture
def protocol_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect `DefaultPaths.DIR_PROTOCOL` to an empty temp dir for the test.

    Returns:
        The empty temp dir now patched in as the protocols directory.
    """
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", tmp_path)
    return tmp_path


class TestRunValidateDispatch:
    def test_run_validate_on_an_unhomed_machine_reports_findings(
        self, service: AutoPipetteService, protocol_dir: Path
    ) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)
        assert service.moonraker_state.is_homed() is False
        (protocol_dir / "check.pipette").write_text("move_loc missing\n")
        server = ControlServer(service)

        result = _call(server, "run.validate", {"filename": "check.pipette"})

        assert result["ok"] is False
        findings = result["data"]["findings"]
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"
        assert "missing is not a named location" in findings[0]["message"]

    def test_run_validate_missing_file_raises_file_not_found(
        self, service: AutoPipetteService, protocol_dir: Path
    ) -> None:
        del protocol_dir  # exists (redirected), just empty
        server = ControlServer(service)

        with pytest.raises(FileNotFoundError):
            _call(server, "run.validate", {"filename": "does_not_exist.pipette"})
