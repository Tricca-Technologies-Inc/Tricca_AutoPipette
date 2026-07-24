"""Shared pytest fixtures for the Tricca AutoPipette test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState
from fakes.fake_websocket_client import FakeWebSocketClient

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.json_config_manager import JsonConfigManager
from tricca_autopipette.core.location_manager import LocationManager
from tricca_autopipette.core.pipette_constants import DefaultFilenames, DefaultPaths
from tricca_autopipette.core.plates import PlateParams
from tricca_autopipette.core.well import StrategyType, Well
from tricca_autopipette.daemon.service import AutoPipetteService


@pytest.fixture
def autopipette() -> AutoPipette:
    """Build a real ``AutoPipette`` from the repo's default configs.

    Uses the actual `config/system/default_system.json` (+ default gantry,
    pipette, liquid) files — read-only, so this is safe to run against the
    real config/ tree with no fixture files or mocks needed. Locations start
    empty; use ``pipette_with_plates`` for tip/well-dependent tests.
    """
    config_manager = JsonConfigManager()
    config_manager.load_configs()
    location_manager = LocationManager()
    location_manager.load_from_json()  # default_locations.json is `{}`
    return AutoPipette(config_manager, location_manager)


def _simple_well(x: float, y: float, z: float, dip_top: float = 5.0) -> Well:
    return Well(
        coor=Coordinate(x=x, y=y, z=z),
        dip_top=dip_top,
        strategy_type=StrategyType.SIMPLE,
    )


def _add_tipbox_waste_and_plate(autopipette: AutoPipette) -> None:
    """Wire a tipbox, waste container, and a 4-well plate into ``autopipette``.

    Built directly via ``LocationManager.set_plate``/``PlateParams`` rather
    than a JSON fixture file, since these are plain in-memory objects and
    need no disk I/O. Shared by ``pipette_with_plates`` (a bare
    ``AutoPipette``) and ``service_with_plates`` (the same, wired into an
    ``AutoPipetteService``).
    """
    location_manager = autopipette.location_manager

    location_manager.set_plate(
        "tipbox",
        PlateParams(
            plate_type="tipbox",
            well_template=_simple_well(10.0, 10.0, 5.0),
            num_row=1,
            num_col=2,
            spacing_row=0.0,
            spacing_col=9.0,
        ),
    )
    location_manager.set_plate(
        "waste",
        PlateParams(
            plate_type="waste_container",
            well_template=_simple_well(50.0, 50.0, 5.0),
            num_row=1,
            num_col=1,
            spacing_row=0.0,
            spacing_col=0.0,
        ),
    )
    location_manager.set_plate(
        "plate_a",
        PlateParams(
            plate_type="array",
            well_template=_simple_well(100.0, 100.0, 5.0),
            num_row=1,
            num_col=4,
            spacing_row=0.0,
            spacing_col=9.0,
        ),
    )


@pytest.fixture
def pipette_with_plates(autopipette: AutoPipette) -> AutoPipette:
    """An ``autopipette`` with a tipbox, waste container, and a well plate."""
    _add_tipbox_waste_and_plate(autopipette)
    return autopipette


@pytest.fixture
def fake_websocket_client() -> FakeWebSocketClient:
    """A connected `FakeWebSocketClient`, for future service-layer tests."""
    return FakeWebSocketClient()


@pytest.fixture
def service(tmp_path: Path) -> AutoPipetteService:
    """A real ``AutoPipetteService``, unconnected to Moonraker.

    Built from the repo's real default configs (same as ``autopipette``
    above), with ``connect_websocket=False`` so no real ``WebSocketClient``
    or network I/O is involved (``service.client`` is None). G-code
    output is redirected to ``tmp_path`` so calling a command method doesn't
    write into the repo's real ``gcode/`` directory. ``service.moonraker_state``
    starts as a ``FakeMoonrakerState`` (unhomed) rather than the real
    ``None``-until-connected value, so gated commands' homed checks are
    directly controllable per test instead of always failing closed.
    """
    svc = AutoPipetteService(
        config_system=DefaultPaths.DIR_CONFIG_SYSTEM / DefaultFilenames.CONFIG_SYSTEM,
        config_gantry=None,
        config_pipette=None,
        config_locations=None,
        config_liquids=None,
        connect_websocket=False,
    )
    svc.gcode_manager.gcode_path = tmp_path
    svc.moonraker_state = FakeMoonrakerState(homed=False)  # type: ignore[assignment]
    return svc


@pytest.fixture
def service_with_plates(service: AutoPipetteService) -> AutoPipetteService:
    """A ``service`` whose ``AutoPipette`` has a tipbox/waste/plate wired up.

    For pipette-group command tests (aspirate/dispense/transfer/tip
    management), which need real locations to operate on.
    """
    _add_tipbox_waste_and_plate(service._autopipette)
    return service
