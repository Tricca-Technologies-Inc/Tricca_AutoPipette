"""Tests for pipette-model-bound tipbox routing.

A pipette config may declare which tipbox it draws from via the ``tipbox``
field on ``PipetteModel``.  When set, ``AutoPipette.next_tip()`` routes to
that specific box automatically — no protocol-level ``tipbox_name`` argument
needed.  This lets two pipettes share a single location config (both tipboxes
always loaded) while keeping tip consumption completely independent.

Seams under test
----------------
1. ``PipetteModel.tipbox`` — optional field, defaults None, parses from JSON.
2. ``AutoPipette.next_tip()`` routing — when ``pipette_model.tipbox`` is set
   the matching box is used; when None the existing draw-in-order default is
   preserved; an explicit ``tipbox_name`` argument always wins.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import OutOfTipsError
from tricca_autopipette.core.pipette_models import (
    PipetteModel,
    PipetteSyringeKinematics,
    ServoConfig,
    TipState,
)
from tricca_autopipette.core.plates import PlateParams
from tricca_autopipette.core.well import StrategyType, Well

# ── helpers ──────────────────────────────────────────────────────────────────


def _well(x: float = 100.0, y: float = 10.0) -> Well:
    return Well(
        coor=Coordinate(x=x, y=y, z=5.0),
        dip_top=5.0,
        strategy_type=StrategyType.SIMPLE,
    )


def _tipbox_params(y: float, cols: int = 2) -> PlateParams:
    """Build a small tipbox at a distinct y.

    Returns:
        Its ``PlateParams``.
    """
    return PlateParams(
        plate_type="tipbox",
        well_template=_well(x=100.0, y=y),
        num_row=1,
        num_col=cols,
        spacing_row=0.0,
        spacing_col=9.0,
    )


# ── Seam 1: PipetteModel.tipbox field ────────────────────────────────────────


class TestPipetteModelTipboxField:
    def test_defaults_to_none(self) -> None:
        """Existing pipette configs with no tipbox field load unchanged."""
        model = PipetteModel(
            name="P100",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0),
            servo=ServoConfig(),
        )
        assert model.tipbox is None

    def test_accepts_string_name(self) -> None:
        model = PipetteModel(
            name="P100",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0),
            servo=ServoConfig(),
            tipbox="tipbox_p100",
        )
        assert model.tipbox == "tipbox_p100"

    def test_accepts_none_explicitly(self) -> None:
        model = PipetteModel(
            name="P100",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0),
            servo=ServoConfig(),
            tipbox=None,
        )
        assert model.tipbox is None

    def test_round_trips_through_json(self) -> None:
        model = PipetteModel(
            name="P100",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0, min_volume_ul=0.5),
            servo=ServoConfig(),
            tipbox="tipbox_p100",
        )
        reloaded = PipetteModel.model_validate_json(model.model_dump_json())
        assert reloaded.tipbox == "tipbox_p100"

    def test_missing_from_json_gives_none(self) -> None:
        """A JSON object without the key parses fine and gives None."""
        import json

        raw = json.dumps({
            "name": "P100",
            "syringe": {"max_travel_mm": 60.0},
            "servo": {},
        })
        model = PipetteModel.model_validate_json(raw)
        assert model.tipbox is None


# ── Seam 2: AutoPipette.next_tip() routing ────────────────────────────────────


@pytest.fixture
def autopipette_two_boxes(autopipette: AutoPipette) -> AutoPipette:
    """Add two named tipboxes and a waste container.

    Returns:
        The same autopipette.
    """
    lm = autopipette.location_manager
    lm.set_plate("tipbox_p100", _tipbox_params(y=10.0, cols=3))
    lm.set_plate("tipbox_p1000", _tipbox_params(y=100.0, cols=2))
    lm.set_plate(
        "waste",
        PlateParams(
            plate_type="waste_container",
            well_template=_well(x=200.0, y=200.0),
            num_row=1,
            num_col=1,
            spacing_row=0.0,
            spacing_col=0.0,
        ),
    )
    return autopipette


def _set_pipette_tipbox(ap: AutoPipette, tipbox: str | None) -> None:
    """Swap the active pipette model's tipbox field, preserving everything else."""
    old = ap.pipette_model
    ap.pipette_model = old.model_copy(update={"tipbox": tipbox})


class TestNextTipRouting:
    def test_no_tipbox_on_model_draws_first_registered_box(
        self, autopipette_two_boxes: AutoPipette
    ) -> None:
        """When pipette_model.tipbox is None the existing draw-order default holds."""
        ap = autopipette_two_boxes
        _set_pipette_tipbox(ap, None)

        ap.next_tip()

        # tip_origin records which box supplied the tip
        assert ap.state.tip_origin is not None
        assert ap.state.tip_origin[0] == "tipbox_p100"

    def test_tipbox_on_model_routes_to_named_box(
        self, autopipette_two_boxes: AutoPipette
    ) -> None:
        """When pipette_model.tipbox is set, that box is drawn from."""
        ap = autopipette_two_boxes
        _set_pipette_tipbox(ap, "tipbox_p1000")

        ap.next_tip()

        assert ap.state.tip_origin is not None
        assert ap.state.tip_origin[0] == "tipbox_p1000"

    def test_explicit_tipbox_name_arg_beats_model_tipbox(
        self, autopipette_two_boxes: AutoPipette
    ) -> None:
        """An explicit tipbox_name argument overrides the model's tipbox."""
        ap = autopipette_two_boxes
        _set_pipette_tipbox(ap, "tipbox_p1000")

        ap.next_tip(tipbox_name="tipbox_p100")

        assert ap.state.tip_origin is not None
        assert ap.state.tip_origin[0] == "tipbox_p100"

    def test_model_tipbox_does_not_drain_other_box(
        self, autopipette_two_boxes: AutoPipette
    ) -> None:
        """Routing to p1000 box leaves p100 box untouched."""
        ap = autopipette_two_boxes
        _set_pipette_tipbox(ap, "tipbox_p1000")
        lm = ap.location_manager

        ap.next_tip()
        # eject so we can pick up again
        ap.state.tip_state = TipState.DETACHED

        # p100 box still has all 3 tips
        p100 = lm.tipbox_manager.boxes["tipbox_p100"]
        assert p100.remaining == 3

    def test_model_tipbox_exhausted_raises_out_of_tips(
        self, autopipette_two_boxes: AutoPipette
    ) -> None:
        """OutOfTipsError names only the bound box, not all boxes."""
        from tricca_autopipette.core.pipette_models import TipState

        ap = autopipette_two_boxes
        _set_pipette_tipbox(ap, "tipbox_p1000")

        # drain the 2-tip p1000 box
        for _ in range(2):
            ap.next_tip()
            ap.state.tip_state = TipState.DETACHED
            ap.state.tip_origin = None

        with pytest.raises(OutOfTipsError):
            ap.next_tip()

    def test_switching_pipette_tipbox_mid_session_preserves_both_counts(
        self, autopipette_two_boxes: AutoPipette
    ) -> None:
        """Switching which box is active never resets either box's consumption."""
        from tricca_autopipette.core.pipette_models import TipState

        ap = autopipette_two_boxes
        lm = ap.location_manager

        # draw one from p100
        _set_pipette_tipbox(ap, "tipbox_p100")
        ap.next_tip()
        ap.state.tip_state = TipState.DETACHED
        ap.state.tip_origin = None

        # switch to p1000, draw one from it
        _set_pipette_tipbox(ap, "tipbox_p1000")
        ap.next_tip()
        ap.state.tip_state = TipState.DETACHED
        ap.state.tip_origin = None

        # switch back — p100 should still show 2 remaining (not 3)
        _set_pipette_tipbox(ap, "tipbox_p100")
        p100 = lm.tipbox_manager.boxes["tipbox_p100"]
        p1000 = lm.tipbox_manager.boxes["tipbox_p1000"]
        assert p100.remaining == 2  # started at 3, one drawn
        assert p1000.remaining == 1  # started at 2, one drawn
