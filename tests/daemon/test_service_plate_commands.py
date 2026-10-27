"""Plate commands: ``plate_move``, ``plates_in``, ``plates`` (issue #143, TAP-4).

Klipper is faked at the Moonraker boundary (``FakeMoonrakerState``: axis
config, homed plates, live axis positions); G-code is read back through
``GCodeManager``'s batch mode, the same buffer a protocol run uploads.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import HomeArgs, PlateMoveArgs
from tricca_autopipette.core.gcode_commands import GCode
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.daemon.moonraker_state import AxisConfig, PlateAxis
from tricca_autopipette.daemon.service import AutoPipetteService

GOLDEN = (
    Path(__file__).parents[1] / "fixtures" / "gcode" / "plate_commands_emission.gcode"
)

AXES = AxisConfig(
    plates=(
        PlateAxis("plate1", "U", 0.0, 350.0, (0.0, 350.0)),
        PlateAxis("plate2", "V", 0.0, 350.0, (0.0, 120.0, 350.0)),
    ),
    z_safe=0.0,
    park_tol=0.1,
)

DECK: dict[str, Any] = {
    "drawers": {
        "plate2": {
            "stops": {"work_a": 0, "work_b": 120, "cover": 300, "load": 350},
            "pipetting": ["work_a", "work_b"],
        },
    },
    "plates": [
        {
            "name": "sample_plate",
            "type": "array",
            "x": 100,
            "y": 10,
            "z": 5,
            "dip_top": 5,
            "num_row": 1,
            "num_col": 4,
            "spacing_col": 9,
            "drawer": "plate2",
            "stop": "work_b",
        },
    ],
}


@pytest.fixture
def fake(service: AutoPipetteService) -> FakeMoonrakerState:
    state = service.moonraker_state
    assert isinstance(state, FakeMoonrakerState)
    return state


@pytest.fixture
def svc(service: AutoPipetteService, fake: FakeMoonrakerState) -> AutoPipetteService:
    # Plates configured, gantry and every plate homed, drawers block loaded.
    fake.axis_config = AXES  # type: ignore[misc]
    fake.set_homed(True)
    fake.homed_plates = {"plate1", "plate2"}
    lm = service._autopipette.location_manager
    lm.set_axis_config(AXES)
    lm.apply_locations_data(DECK, source="deck.json")
    return service


def emitted(service: AutoPipetteService, call: Callable[[], object]) -> list[GCode]:
    service.gcode_manager.start_batch()
    try:
        call()
    finally:
        gcode = service.gcode_manager.end_batch()
    return [g for g in gcode if g.strip() and not g.startswith(";")]


def move(plate: str, target: str, speed: float | None = None) -> PlateMoveArgs:
    return PlateMoveArgs(plate=plate, target=target, speed=speed)


def model(service: AutoPipetteService) -> dict[str, float]:
    return service._autopipette.location_manager.drawer_positions


class TestPlateMove:
    def test_to_a_named_stop(self, svc: AutoPipetteService) -> None:
        gcode = emitted(svc, lambda: svc.plate_move(move("plate2", "work_b")))
        assert gcode == ["PLATE_MOVE PLATE=plate2 POS=120.0\n"]

    def test_to_raw_mm_with_speed(self, svc: AutoPipetteService) -> None:
        gcode = emitted(svc, lambda: svc.plate_move(move("plate1", "42.5", 25)))
        assert gcode == ["PLATE_MOVE PLATE=plate1 POS=42.5 SPEED=25\n"]

    @pytest.mark.parametrize("target", ["V", "v", "PLATE2"])
    def test_axis_letter_and_name_are_case_insensitive(
        self, svc: AutoPipetteService, target: str
    ) -> None:
        gcode = emitted(svc, lambda: svc.plate_move(move(target, "load")))
        assert gcode == ["PLATE_MOVE PLATE=plate2 POS=350.0\n"]

    def test_updates_the_drawer_model(self, svc: AutoPipetteService) -> None:
        emitted(svc, lambda: svc.plate_move(move("plate2", "cover")))
        assert model(svc) == {"plate2": 300.0}

    @pytest.mark.parametrize(
        ("plate", "target", "match"),
        [
            ("plate9", "0", r"Unknown plate 'plate9'.*plate1 \(U\), plate2 \(V\)"),
            ("plate2", "lid", r"Unknown stop 'lid'.*cover, load, work_a, work_b"),
            ("plate1", "load", r"plate1 has no named stops"),
            ("plate2", "350.5", r"outside .*0 to 350"),
            ("plate2", "-1", r"outside .*0 to 350"),
            ("plate2", "nan", r"outside|not a number"),
        ],
    )
    def test_bad_input_refused_before_any_gcode(
        self, svc: AutoPipetteService, plate: str, target: str, match: str
    ) -> None:
        gcode: list[GCode] = []
        with pytest.raises(ValueError, match=match):
            gcode = emitted(svc, lambda: svc.plate_move(move(plate, target)))
        assert gcode == []
        assert "plate2" not in model(svc)

    @pytest.mark.parametrize("speed", [0, -5, float("inf")])
    def test_bad_speed_refused(self, svc: AutoPipetteService, speed: float) -> None:
        with pytest.raises(ValueError, match="speed"):
            svc.plate_move(move("plate2", "load", speed))

    def test_refused_when_the_plate_is_not_homed(
        self, svc: AutoPipetteService, fake: FakeMoonrakerState
    ) -> None:
        fake.homed_plates = {"plate1"}
        with pytest.raises(NotHomedError, match="plate2 not homed"):
            svc.plate_move(move("plate2", "load"))
        assert "plate2" not in model(svc)

    def test_not_configured(self, service: AutoPipetteService) -> None:
        with pytest.raises(ValueError, match="No plates configured"):
            service.plate_move(move("plate1", "0"))


class TestPlatesIn:
    def test_emits_plates_in_and_models_every_plate_in(
        self, svc: AutoPipetteService
    ) -> None:
        gcode = emitted(svc, svc.plates_in)
        assert gcode == ["PLATES_IN\n"]
        assert model(svc) == {"plate1": 0.0, "plate2": 0.0}

    def test_needs_every_plate_homed(
        self, svc: AutoPipetteService, fake: FakeMoonrakerState
    ) -> None:
        fake.homed_plates = {"plate2"}
        with pytest.raises(NotHomedError, match="plate1 not homed"):
            svc.plates_in()

    def test_not_configured(self, service: AutoPipetteService) -> None:
        with pytest.raises(ValueError, match="No plates configured"):
            service.plates_in()


class TestHomingUpdatesTheModel:
    @pytest.mark.parametrize(
        ("motors", "expected"),
        [("plates", {"plate1": 0.0, "plate2": 0.0}), ("v", {"plate2": 0.0})],
    )
    def test_plate_homing_leaves_plates_in(
        self, svc: AutoPipetteService, motors: str, expected: dict[str, float]
    ) -> None:
        emitted(svc, lambda: svc.home(HomeArgs(motors)))
        assert model(svc) == expected

    def test_full_home_homes_the_plates_too(self, svc: AutoPipetteService) -> None:
        emitted(svc, svc.init)
        assert model(svc) == {"plate1": 0.0, "plate2": 0.0}

    def test_no_plates_leaves_the_model_alone(
        self, service: AutoPipetteService
    ) -> None:
        emitted(service, service.init)
        assert model(service) == {}


class TestLivePositions:
    def test_only_homed_plates_with_a_live_position_count(
        self, svc: AutoPipetteService, fake: FakeMoonrakerState
    ) -> None:
        fake.positions = {"U": 350.0, "V": 120.0}
        fake.homed_plates = {"plate2"}
        assert svc._live_drawer_positions() == {"plate2": 120.0}

    def test_dispatch_seeds_the_model_so_a_linked_location_is_usable(
        self, svc: AutoPipetteService, fake: FakeMoonrakerState
    ) -> None:
        fake.positions = {"V": 120.0}
        svc._seed_drawer_model()
        svc._autopipette.location_manager.check_drawer("sample_plate")


class TestPlatesStatus:
    def test_reports_each_plate(
        self, svc: AutoPipetteService, fake: FakeMoonrakerState
    ) -> None:
        fake.homed_plates = {"plate2"}
        fake.positions = {"U": 200.0, "V": 120.05}

        result = svc.plates()

        assert result.ok
        assert result.data == {
            "plates": [
                {
                    "name": "plate1",
                    "letter": "U",
                    "homed": False,
                    "position": 200.0,
                    "stop": None,
                    "tip_safe": False,
                },
                {
                    "name": "plate2",
                    "letter": "V",
                    "homed": True,
                    "position": 120.05,
                    "stop": "work_b",
                    "tip_safe": True,
                },
            ]
        }

    @pytest.mark.parametrize(("pos", "stop"), [(0.0, "in"), (350.0, "out")])
    def test_ends_of_travel_read_in_and_out_without_a_named_stop(
        self, svc: AutoPipetteService, fake: FakeMoonrakerState, pos: float, stop: str
    ) -> None:
        fake.positions = {"U": pos}
        data = svc.plates().data
        assert data is not None
        assert data["plates"][0]["stop"] == stop
        assert data["plates"][0]["tip_safe"] is True

    def test_not_configured(self, service: AutoPipetteService) -> None:
        result = service.plates()
        assert not result.ok
        assert "No plates configured" in result.message


class TestProtocolFile:
    def _protocol(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str
    ) -> None:
        protocol = tmp_path / "p.pipette"
        protocol.write_text(text)

        def resolve(category: str, name: str) -> Path:
            del category, name
            return protocol

        monkeypatch.setattr(
            "tricca_autopipette.daemon.service.LocalConfigRoots.resolve", resolve
        )

    def test_plate_lines_dispatch_and_feed_the_drawer_model(
        self, svc: AutoPipetteService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._protocol(
            tmp_path,
            monkeypatch,
            "plates_in\nplate_move V work_b --speed 30\nmove_loc sample_plate\n",
        )
        # move_loc would raise DrawerNotAtStopError had plate_move not
        # updated the compile-time model.
        svc._run_protocol_sync("p.pipette")

    def test_a_refused_plate_line_aborts_the_batch(
        self, svc: AutoPipetteService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._protocol(tmp_path, monkeypatch, "plate_move plate2 lid\n")
        with pytest.raises(ValueError, match="Unknown stop"):
            svc._run_protocol_sync("p.pipette")

    def test_validate_follows_the_model_on_an_unhomed_machine(
        self,
        svc: AutoPipetteService,
        fake: FakeMoonrakerState,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake.set_homed(False)
        fake.homed_plates = set()
        self._protocol(
            tmp_path,
            monkeypatch,
            "plate_move plate2 load\nmove_loc sample_plate\n"
            "plate_move plate2 work_b\nmove_loc sample_plate\n",
        )

        data = svc.validate_protocol("p.pipette").data
        assert data is not None
        errors = [f for f in data["findings"] if f["severity"] == "error"]

        assert [f["line_number"] for f in errors] == [2]
        assert "at 350 mm" in errors[0]["message"]


def test_plate_emissions_match_the_golden_file(svc: AutoPipetteService) -> None:
    """Every plate-command emission, byte for byte (issue #143).

    The golden was written by hand from the Klipper <-> tapd contract
    (umbrella §6.3; ``plate-macros.cfg``'s ``PLATE_MOVE``/``PLATES_IN``
    parameters), not captured from the code.
    """
    gcode = emitted(
        svc,
        lambda: (
            svc.plate_move(move("plate2", "work_b")),
            svc.plate_move(move("plate2", "load", 50)),
            svc.plate_move(move("U", "12.5")),
            svc.plate_move(move("plate1", "0", 25.5)),
            svc.plates_in(),
        ),
    )
    assert "".join(gcode) == GOLDEN.read_text(encoding="utf-8")
