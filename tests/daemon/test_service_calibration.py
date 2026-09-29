"""Gravimetric calibration session (issue #26), at the service seam.

Every test runs against a scratch copy of the repo's ``config/`` tree as the
shared root and a scratch local root under ``tmp_path`` -- a commit writes a
local pipette override, and that must never land in the real ``~/.config``
or in the suite-wide temp local root other tests read from.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import CalibrateStartArgs
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths
from tricca_autopipette.core.pipette_exceptions import NotHomedError
from tricca_autopipette.core.pipette_models import TipState
from tricca_autopipette.core.plates import PlateParams
from tricca_autopipette.core.volume_converter import VolumeConverter
from tricca_autopipette.core.well import StrategyType, Well
from tricca_autopipette.daemon.service import (
    AutoPipetteService,
    CommandResult,
    RunStatus,
)

_CATEGORY_ATTRS = {
    "system": ("DIR_CONFIG_SYSTEM", "DIR_LOCAL_SYSTEM"),
    "gantry": ("DIR_CONFIG_GANTRY", "DIR_LOCAL_GANTRY"),
    "pipettes": ("DIR_CONFIG_PIPETTE", "DIR_LOCAL_PIPETTE"),
    "liquids": ("DIR_CONFIG_LIQUIDS", "DIR_LOCAL_LIQUIDS"),
    "locations": ("DIR_CONFIG_LOCATIONS", "DIR_LOCAL_LOCATIONS"),
    "plates": ("DIR_CONFIG_PLATES", "DIR_LOCAL_PLATES"),
}


@pytest.fixture
def shared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated shared/local roots, with the default system profile seeded.

    Returns:
        The scratch shared root.
    """
    shared = tmp_path / "shared"
    local = tmp_path / "local"
    shutil.copytree(DefaultPaths.DIR_CONFIG, shared)
    (local / "system").mkdir(parents=True)
    shutil.copy2(
        shared / "system" / DefaultFilenames.CONFIG_SYSTEM,
        local / "system" / DefaultFilenames.CONFIG_SYSTEM,
    )
    for category, (shared_attr, local_attr) in _CATEGORY_ATTRS.items():
        monkeypatch.setattr(DefaultPaths, shared_attr, shared / category)
        monkeypatch.setattr(DefaultPaths, local_attr, local / category)
    return shared


@pytest.fixture
def svc(shared: Path, tmp_path: Path) -> AutoPipetteService:
    """A homed service with a deck and a tip on, ready to calibrate.

    Returns:
        The service.
    """
    service = AutoPipetteService(
        config_system=DefaultPaths.DIR_LOCAL_SYSTEM / DefaultFilenames.CONFIG_SYSTEM,
        config_gantry=None,
        config_pipette=None,
        config_locations=None,
        config_liquids=None,
        connect_websocket=False,
    )
    service.gcode_manager.gcode_path = tmp_path
    service.moonraker_state = FakeMoonrakerState(homed=True)  # type: ignore[assignment]
    for name, x in (("reservoir", 100.0), ("balance", 200.0)):
        service._autopipette.location_manager.set_plate(
            name,
            PlateParams(
                plate_type="singleton",
                well_template=Well(
                    coor=Coordinate(x=x, y=100.0, z=5.0),
                    dip_top=5.0,
                    strategy_type=StrategyType.SIMPLE,
                ),
                num_row=1,
                num_col=1,
                spacing_row=0.0,
                spacing_col=0.0,
            ),
        )
    service._autopipette.state.tip_state = TipState.ATTACHED
    return service


def _start(
    svc: AutoPipetteService, volumes: list[float] | None = None
) -> CommandResult:
    return svc.calibrate_start(
        CalibrateStartArgs(source="reservoir", dest="balance", volumes_ul=volumes)
    )


class TestStart:
    def test_default_targets_span_the_usable_range(
        self, svc: AutoPipetteService
    ) -> None:
        # p100_vertical: 100 uL max, 2 uL margin -> 98 uL usable.
        result = _start(svc)

        assert result.ok, result.message
        assert result.data is not None
        assert result.data["targets_ul"] == pytest.approx([9.8, 29.4, 49.0, 68.6, 88.2])
        assert result.data["step"] == "dispense"
        assert result.data["index"] == 0

    def test_makes_water_the_active_liquid(self, svc: AutoPipetteService) -> None:
        svc.switch_liquid("methanol")

        assert _start(svc).ok
        assert svc._autopipette.active_liquid == "water"

    def test_refuses_without_a_tip(self, svc: AutoPipetteService) -> None:
        svc._autopipette.state.tip_state = TipState.DETACHED

        result = _start(svc)

        assert not result.ok
        assert "tip" in result.message
        assert svc.calibrate_status().data == {"active": False}

    def test_refuses_an_unknown_location(self, svc: AutoPipetteService) -> None:
        result = svc.calibrate_start(
            CalibrateStartArgs(source="reservoir", dest="nowhere")
        )

        assert not result.ok
        assert "nowhere" in result.message

    @pytest.mark.parametrize(
        "volumes", [[50.0], [0.0, 50.0], [50.0, 98.5], [-1.0, 50.0]]
    )
    def test_refuses_targets_outside_the_usable_range(
        self, svc: AutoPipetteService, volumes: list[float]
    ) -> None:
        assert not _start(svc, volumes).ok

    def test_refuses_when_water_has_no_density(self, svc: AutoPipetteService) -> None:
        assert svc.set_config_value("liquids", "water.json", "density_g_ml", None).ok

        result = _start(svc)

        assert not result.ok
        assert "density" in result.message

    def test_refuses_when_unhomed(self, svc: AutoPipetteService) -> None:
        svc.moonraker_state.set_homed(False)  # type: ignore[union-attr]

        with pytest.raises(NotHomedError):
            _start(svc)

    def test_refused_while_a_run_is_active(self, svc: AutoPipetteService) -> None:
        svc._current = RunStatus(status="running", filename="p.pipette")

        result = _start(svc)

        assert not result.ok
        assert result.data == {"reason": "run_active"}


def _move_distances(gcode: list[str]) -> list[float]:
    """Return every MANUAL_STEPPER MOVE= distance in emission order."""
    return [
        float(tok.split("=", 1)[1])
        for line in gcode
        for tok in line.split()
        if tok.startswith("MOVE=")
    ]


class TestDispense:
    def test_records_the_travel_the_dispense_move_commanded(
        self, svc: AutoPipetteService
    ) -> None:
        _start(svc, [40.0, 80.0])
        with patch.object(svc, "output_gcode") as output:
            result = svc.calibrate_dispense()
        emitted: list[str] = [line for c in output.call_args_list for line in c.args[0]]

        assert result.ok, result.message
        assert result.data is not None
        point = result.data["points"][0]
        # The dispense is the last plunger MOVE; the calibration pairs the
        # weighed volume with exactly that travel, not with the 40 uL asked.
        assert point["travel_mm"] == pytest.approx(abs(_move_distances(emitted)[-1]))
        assert point["target_ul"] == 40.0  # ruff:ignore[float-equality-comparison]
        assert result.data["step"] == "record"
        assert result.data["index"] == 0


class TestRecord:
    def test_mass_becomes_volume_through_waters_configured_density(
        self, svc: AutoPipetteService
    ) -> None:
        assert svc.set_config_value("liquids", "water.json", "density_g_ml", 0.998).ok
        _start(svc, [50.0, 80.0])
        svc.calibrate_dispense()

        result = svc.calibrate_record(0.0493)

        assert result.ok, result.message
        assert result.data is not None
        point = result.data["points"][0]
        # 0.0493 g / 0.998 g/mL = 0.0493988 mL = 49.3988 uL
        assert point["mass_g"] == 0.0493  # ruff:ignore[float-equality-comparison]
        assert point["volume_ul"] == pytest.approx(49.398797595, abs=1e-9)
        assert result.data["step"] == "dispense"
        assert result.data["index"] == 1

    @pytest.mark.parametrize("mass", [0.0, -0.01, float("nan"), float("inf")])
    def test_refuses_a_mass_that_is_not_a_positive_number(
        self, svc: AutoPipetteService, mass: float
    ) -> None:
        _start(svc, [50.0, 80.0])
        svc.calibrate_dispense()

        result = svc.calibrate_record(mass)

        assert not result.ok
        assert result.data is not None
        assert result.data["step"] == "record"


class TestRunLock:
    def test_no_step_advances_while_a_run_is_active(
        self, svc: AutoPipetteService
    ) -> None:
        _start(svc, [50.0, 80.0])
        svc._current = RunStatus(status="running", filename="p.pipette")

        for result in (
            svc.calibrate_dispense(),
            svc.calibrate_record(0.05),
            svc.calibrate_commit(),
        ):
            assert not result.ok
            assert result.data == {"reason": "run_active"}


def _run_points(svc: AutoPipetteService, masses_g: list[float]) -> None:
    """Start on a 0.5 mm/uL curve and dispense+record one point per mass."""
    # A known current curve, so each commanded travel is exactly target / 2.
    svc._autopipette.volume_converter = VolumeConverter([0.0, 100.0], [0.0, 50.0])
    assert _start(svc, [20.0, 40.0, 80.0][: len(masses_g)]).ok
    for mass in masses_g:
        assert svc.calibrate_dispense().ok
        assert svc.calibrate_record(mass).ok


class TestPreview:
    def test_fits_measured_volume_against_commanded_travel(
        self, svc: AutoPipetteService
    ) -> None:
        # travel 10/20/40 mm; weighed 19/41/80 uL (water, 1.0 g/mL).
        _run_points(svc, [0.019, 0.041, 0.080])

        result = svc.calibrate_preview()

        assert result.ok, result.message
        assert result.data is not None
        # Least squares by hand: slope 1415/2863, intercept 110/409.
        assert result.data["fit"]["slope"] == pytest.approx(1415 / 2863, abs=1e-12)
        assert result.data["fit"]["intercept"] == pytest.approx(110 / 409, abs=1e-12)
        assert result.data["fit"]["volumes_ul"] == pytest.approx([19.0, 41.0, 80.0])
        assert result.data["fit"]["travel_mm"] == pytest.approx([10.0, 20.0, 40.0])
        # The current curve is the pipette's base curve from its config file.
        assert result.data["current"]["volumes_ul"][0] == 9.6  # ruff:ignore[float-equality-comparison]
        assert result.data["step"] == "commit"


class TestOutOfOrder:
    @pytest.mark.parametrize(
        ("step", "args"),
        [
            ("calibrate_dispense", ()),
            ("calibrate_record", (0.05,)),
            ("calibrate_preview", ()),
            ("calibrate_commit", ()),
            ("calibrate_abort", ()),
        ],
    )
    def test_every_step_needs_a_session(
        self, svc: AutoPipetteService, step: str, args: tuple[float, ...]
    ) -> None:
        result: CommandResult = getattr(svc, step)(*args)

        assert not result.ok
        assert "No calibration in progress" in result.message

    def test_record_before_dispense_is_refused(self, svc: AutoPipetteService) -> None:
        _start(svc, [40.0, 80.0])

        result = svc.calibrate_record(0.04)

        assert not result.ok
        assert "dispense" in result.message
        assert result.data is not None
        assert result.data["points"] == []

    def test_a_second_dispense_before_recording_is_refused(
        self, svc: AutoPipetteService
    ) -> None:
        _start(svc, [40.0, 80.0])
        svc.calibrate_dispense()

        result = svc.calibrate_dispense()

        assert not result.ok
        assert "record" in result.message

    def test_preview_before_every_point_is_recorded_is_refused(
        self, svc: AutoPipetteService
    ) -> None:
        _start(svc, [40.0, 80.0])
        svc.calibrate_dispense()
        svc.calibrate_record(0.04)

        assert not svc.calibrate_preview().ok

    def test_commit_before_preview_is_refused(self, svc: AutoPipetteService) -> None:
        _run_points(svc, [0.019, 0.041])

        result = svc.calibrate_commit()

        assert not result.ok
        assert "preview" in result.message
        assert not (DefaultPaths.DIR_LOCAL_PIPETTE / "p100_vertical.json").exists()

    def test_only_one_session_at_a_time(self, svc: AutoPipetteService) -> None:
        _start(svc, [40.0, 80.0])

        result = _start(svc, [10.0, 20.0])

        assert not result.ok
        assert result.data is not None
        assert result.data["targets_ul"] == [40.0, 80.0]

    def test_abort_discards_the_session(self, svc: AutoPipetteService) -> None:
        _start(svc, [40.0, 80.0])

        assert svc.calibrate_abort().ok
        assert svc.calibrate_status().data == {"active": False}


class TestCommit:
    def test_saves_the_curve_to_the_local_pipette_copy_and_applies_it(
        self, svc: AutoPipetteService, shared: Path
    ) -> None:
        shared_file = shared / "pipettes" / "p100_vertical.json"
        shared_before = shared_file.read_bytes()
        _run_points(svc, [0.019, 0.041, 0.080])
        svc.calibrate_preview()

        result = svc.calibrate_commit()

        assert result.ok, result.message
        local = json.loads(
            (DefaultPaths.DIR_LOCAL_PIPETTE / "p100_vertical.json").read_text()
        )
        assert local["syringe"]["calibration_volumes"] == pytest.approx([
            19.0,
            41.0,
            80.0,
        ])
        assert local["syringe"]["calibration_mm"] == pytest.approx([10.0, 20.0, 40.0])
        assert shared_file.read_bytes() == shared_before
        # Live: the next aspirate/dispense uses the new curve...
        assert svc._autopipette.volume_converter.vol_to_mm(80.0) == pytest.approx(
            (1415 / 2863) * 80.0 + 110 / 409
        )
        # ...without forcing a re-home, since no mechanical limit changed.
        assert not svc._homing_invalidated
        assert svc.calibrate_status().data == {"active": False}

    def test_a_pipette_defined_in_the_system_file_is_calibrated_there(
        self, svc: AutoPipetteService, shared: Path
    ) -> None:
        inline = json.loads((shared / "pipettes" / "p100_vertical.json").read_text())
        inline["name"] = "Inline"
        assert svc.set_config_value(
            "system", DefaultFilenames.CONFIG_SYSTEM, "pipette", inline
        ).ok
        svc._homing_invalidated = False
        _run_points(svc, [0.019, 0.041])
        svc.calibrate_preview()

        result = svc.calibrate_commit()

        assert result.ok, result.message
        system = json.loads(
            (DefaultPaths.DIR_LOCAL_SYSTEM / DefaultFilenames.CONFIG_SYSTEM).read_text()
        )
        syringe = system["pipette"]["syringe"]
        assert syringe["calibration_volumes"] == pytest.approx([19.0, 41.0])
        assert syringe["calibration_mm"] == pytest.approx([10.0, 20.0])
        assert not (DefaultPaths.DIR_LOCAL_PIPETTE / "p100_vertical.json").exists()

    def test_refuses_if_the_pipette_was_swapped_mid_session(
        self, svc: AutoPipetteService
    ) -> None:
        _run_points(svc, [0.019, 0.041])
        svc.calibrate_preview()
        assert svc.load_pipette("default_p100.json").ok

        result = svc.calibrate_commit()

        assert not result.ok
        assert "p100_vertical.json" in result.message
        assert not (DefaultPaths.DIR_LOCAL_PIPETTE / "p100_vertical.json").exists()
