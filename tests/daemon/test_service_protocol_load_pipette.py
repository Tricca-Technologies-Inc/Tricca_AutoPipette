"""``load_pipette`` as a protocol-file line (dual-pipette heads).

A protocol may swap the active pipette partway through, e.g. Tyson's P100
for its P1000. The run already holds the config lock, so the line goes
round it; clients still can't swap the pipette under a running protocol.
The swap invalidates homing, so the protocol must re-home before moving,
and a compile-time failure or a dry run puts the original pipette back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.daemon.service import AutoPipetteService, CommandResult

SWAP_TO = "default_pipette.json"


@pytest.fixture
def svc(
    service_with_plates: AutoPipetteService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AutoPipetteService:
    """A homed service whose protocols live in ``tmp_path``.

    Returns:
        ``service_with_plates``, homed, reading protocols from ``tmp_path``.
    """
    monkeypatch.setattr(DefaultPaths, "DIR_PROTOCOL", tmp_path)
    assert isinstance(service_with_plates.moonraker_state, FakeMoonrakerState)
    service_with_plates.moonraker_state.set_homed(True)
    return service_with_plates


def _protocol(tmp_path: Path, *lines: str) -> str:
    (tmp_path / "p.pipette").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "p.pipette"


def _locked(svc: AutoPipetteService, monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = CommandResult(ok=False, message="locked", data={"reason": "run_active"})
    monkeypatch.setattr(svc, "config_lock_refusal", lambda: refusal)


def test_a_protocol_swaps_the_pipette_under_its_own_run_lock(
    svc: AutoPipetteService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _locked(svc, monkeypatch)
    before = svc._autopipette.pipette_model

    svc._run_protocol_sync(_protocol(tmp_path, f"load_pipette {SWAP_TO}", "home all"))

    # default_pipette.json dispenses at 25 mm/s, the default p100 at 50.
    assert svc._autopipette.pipette_model != before
    assert svc._autopipette.pipette_model.syringe.speed_dispense == pytest.approx(25.0)


def test_a_client_still_cannot_swap_the_pipette_during_a_run(
    svc: AutoPipetteService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _locked(svc, monkeypatch)

    result = svc.load_pipette(SWAP_TO)

    assert result.data == {"reason": "run_active"}


def test_a_missing_pipette_file_aborts_the_run(
    svc: AutoPipetteService, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        svc._run_protocol_sync(_protocol(tmp_path, "load_pipette nope.json"))


def test_moving_after_a_swap_without_rehoming_is_refused(
    svc: AutoPipetteService, tmp_path: Path
) -> None:
    with pytest.raises(NotHomedError):
        svc._run_protocol_sync(
            _protocol(tmp_path, f"load_pipette {SWAP_TO}", "move_loc plate_a")
        )


def test_a_compile_time_failure_puts_the_original_pipette_back(
    svc: AutoPipetteService, tmp_path: Path
) -> None:
    before = svc._autopipette.pipette_model

    with pytest.raises(NotHomedError):
        svc._run_protocol_sync(
            _protocol(tmp_path, f"load_pipette {SWAP_TO}", "move_loc plate_a")
        )

    assert svc._autopipette.pipette_model == before
    assert svc._homing_invalidated is False


def test_a_dry_run_leaves_the_pipette_alone(
    svc: AutoPipetteService, tmp_path: Path
) -> None:
    before = svc._autopipette.pipette_model

    result = svc.validate_protocol(
        _protocol(tmp_path, f"load_pipette {SWAP_TO}", "home all")
    )

    assert result.ok, result.data
    assert result.data is not None
    assert not result.data["findings"]
    assert svc._autopipette.pipette_model == before
    assert svc._homing_invalidated is False
