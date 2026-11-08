"""Drawer-stop enforcement and the compile-time drawer-position model (#142)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import (
    MoveLocArgs,
    PipetteArgs,
)
from tricca_autopipette.core.pipette_exceptions import DrawerNotAtStopError
from tricca_autopipette.core.pipette_models import TipState
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis
from tricca_autopipette.daemon.service import AutoPipetteService

KLIPPER = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 120.0, 350.0)),
    ),
    z_safe=0.0,
    park_tol=0.1,
)


def plate(name: str, kind: str, x: float, **link: str) -> dict[str, Any]:
    return {
        "name": name,
        "type": kind,
        "x": x,
        "y": 10,
        "z": 5,
        "dip_top": 5,
        "num_row": 1,
        "num_col": 4,
        "spacing_col": 9,
        **link,
    }


DECK: dict[str, Any] = {
    "drawers": {
        "plate1": {"stops": {"in": 0, "load": 350}, "pipetting": ["in"]},
        "plate2": {"stops": {"work_a": 0, "load": 350}, "pipetting": ["work_a"]},
    },
    "plates": [
        plate("tipbox", "tipbox", 60, drawer="plate1", stop="in"),
        plate("waste", "waste_container", 120),
        plate("source", "array", 180),
        plate("sample_plate", "array", 240, drawer="plate2", stop="work_a"),
    ],
}


@pytest.fixture
def svc(service: AutoPipetteService) -> AutoPipetteService:
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.set_homed(True)
    service._autopipette.location_manager.apply_locations_data(DECK, replace=True)
    return service


def model(svc: AutoPipetteService) -> dict[str, float]:
    return svc._autopipette.location_manager.drawer_positions


def transfer_args(**overrides: Any) -> PipetteArgs:
    fields: dict[str, Any] = dict.fromkeys(
        PipetteArgs.__dataclass_fields__  # every optional flag omitted
    )
    fields.update(vol_ul=10.0, source="source", wiggle=False, keep_tip=False)
    fields.update(overrides)
    return PipetteArgs(**fields)


def move_to_sample(svc: AutoPipetteService) -> None:
    svc.move_loc(MoveLocArgs(name_loc="sample_plate", row=None, col=None))


class TestEnforcement:
    def test_move_loc_refused_with_drawer_elsewhere(
        self, svc: AutoPipetteService
    ) -> None:
        model(svc).update(plate2=350)

        with pytest.raises(DrawerNotAtStopError, match="'plate2' at stop 'work_a'"):
            move_to_sample(svc)

    def test_move_loc_succeeds_after_a_drawer_move_in_the_same_batch(
        self, svc: AutoPipetteService
    ) -> None:
        model(svc).update(plate2=350)
        lm = svc._autopipette.location_manager

        with svc.domain_state_snapshot(), svc.gcode_manager.batch_mode():
            with pytest.raises(DrawerNotAtStopError):
                move_to_sample(svc)
            lm.set_drawer_position("plate2", 0)  # what TAP-4's plate_move does
            move_to_sample(svc)

        assert model(svc) == {"plate2": 0}

    def test_failed_batch_rolls_the_model_back(self, svc: AutoPipetteService) -> None:
        model(svc).update(plate2=350)
        lm = svc._autopipette.location_manager

        with (
            pytest.raises(RuntimeError),
            svc.domain_state_snapshot(),
            svc.gcode_manager.batch_mode(),
        ):
            lm.set_drawer_position("plate2", 0)
            raise RuntimeError("line 2 failed")

        assert model(svc) == {"plate2": 350}

    def test_transfer_to_linked_dest_refused_before_tip_pickup(
        self, svc: AutoPipetteService
    ) -> None:
        model(svc).update(plate1=0)

        with pytest.raises(DrawerNotAtStopError, match="'sample_plate'"):
            svc.transfer(transfer_args(dest="sample_plate"))

        assert svc._autopipette.state.tip_state != TipState.ATTACHED

    def test_splits_to_linked_dest_refused(self, svc: AutoPipetteService) -> None:
        model(svc).update(plate1=0)

        with pytest.raises(DrawerNotAtStopError, match="'sample_plate'"):
            svc.transfer(transfer_args(splits="sample_plate:10"))

        assert svc._autopipette.state.tip_state != TipState.ATTACHED

    def test_next_tip_from_linked_tipbox_refused_without_consuming_a_slot(
        self, svc: AutoPipetteService
    ) -> None:
        tips = svc._autopipette.location_manager.tipbox_manager
        before = tips.remaining

        with pytest.raises(DrawerNotAtStopError, match="'tipbox'"):
            svc.next_tip()

        assert tips.remaining == before

    def test_transfer_succeeds_with_drawers_at_their_stops(
        self, svc: AutoPipetteService
    ) -> None:
        model(svc).update(plate1=0, plate2=0)

        result = svc.transfer(transfer_args(dest="sample_plate"))

        assert result.ok


class TestSeeding:
    def test_protocol_start_seeds_the_model_from_live_state(
        self, svc: AutoPipetteService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No live plate positions yet (TAP-3), so a run starts with every
        # drawer at an unknown position, whatever an earlier command left.
        model(svc).update(plate2=0)
        protocol = tmp_path / "p.pipette"
        protocol.write_text("move_loc sample_plate\n")

        def resolve(category: str, name: str) -> Path:
            del category, name
            return protocol

        monkeypatch.setattr(
            "tricca_autopipette.daemon.service.LocalConfigRoots.resolve", resolve
        )

        with pytest.raises(DrawerNotAtStopError, match="unknown position"):
            svc._run_protocol_sync("p.pipette")

    def test_connect_checks_loaded_drawers_against_klipper(
        self, svc: AutoPipetteService, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake = FakeMoonrakerState(homed=True)
        fake.axis_config = AxisConfig(
            plates=(PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),)
        )
        svc.moonraker_state = fake  # type: ignore[assignment]

        with caplog.at_level(logging.ERROR):
            svc.connect()

        assert "'plate2' is not a plate Klipper knows" in caplog.text
        lm = svc._autopipette.location_manager
        assert lm.axis_config == fake.axis_config


class TestReporting:
    def test_system_summary_reports_drawers(self, svc: AutoPipetteService) -> None:
        data = svc.system_summary().data
        assert data is not None

        assert data["drawers"]["plate2"] == {
            "stops": {"work_a": 0.0, "load": 350.0},
            "pipetting": ["work_a"],
            "position": None,
            "source": "<inline>",
        }

    def test_list_locations_reports_links(self, svc: AutoPipetteService) -> None:
        data = svc.list_locations().data
        assert data is not None
        rows: dict[str, Any] = {row["name"]: row for row in data["locations"]}

        assert rows["sample_plate"]["drawer"] == "plate2"
        assert rows["sample_plate"]["stop"] == "work_a"
        assert "drawer" not in rows["source"]
