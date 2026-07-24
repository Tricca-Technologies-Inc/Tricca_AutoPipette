"""Unit tests for :mod:`tricca_autopipette.core.plates`.

Focused on ``PlateFactory.type_name_for`` -- the inverse of ``create()``,
added to fix a real round-trip bug: ``LocationManager.save_to_json`` used
to derive the saved "type" string from ``location.__class__.__name__.lower()``
(e.g. "platearray" for a ``PlateArray``), which never matches a registered
plate-type key ("array"), so ``load_from_json`` could never load a plate
``save_to_json`` had just written.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.plates import (
    InvalidPlateTypeError,
    PlateFactory,
    PlateParams,
)
from tricca_autopipette.core.well import StrategyType, Well


def _well() -> Well:
    return Well(
        coor=Coordinate(x=1.0, y=2.0, z=3.0),
        dip_top=5.0,
        strategy_type=StrategyType.SIMPLE,
    )


@pytest.mark.parametrize(
    "plate_type", ["array", "singleton", "tipbox", "waste_container"]
)
def test_type_name_for_round_trips_every_registered_type(plate_type: str) -> None:
    params = PlateParams(plate_type=plate_type, well_template=_well())
    plate = PlateFactory.create(params)

    assert PlateFactory.type_name_for(plate) == plate_type


def test_type_name_for_unregistered_type_raises() -> None:
    class NotAPlate:
        pass

    with pytest.raises(InvalidPlateTypeError):
        PlateFactory.type_name_for(NotAPlate())  # type: ignore[arg-type]
