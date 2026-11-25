"""Tests for a pipette's deck offset.

A pipette file may set ``deck_offset: {x, y}`` when its nozzle sits beside
the head's reference nozzle (Tyson's P1000 is 36.7 mm to one side of its
P100). The offset shifts every deck target the active pipette visits, so
two pipettes share one locations file. Tipboxes are the exception: each
pipette has its own box, located in that pipette's frame.

There is deliberately no Z offset: dip depths are absolute (a plate's
``dip_top``/``dip_btm``), so shifting only the travel height would leave
the dip where the other nozzle needs it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_models import DeckOffset, PipetteModel, TipState


def _set_offset(ap: AutoPipette, x: float = 0.0, y: float = 0.0) -> None:
    ap.pipette_model = ap.pipette_model.model_copy(
        update={"deck_offset": DeckOffset(x=x, y=y)}
    )


def _xy_moves(ap: AutoPipette) -> list[tuple[float, float]]:
    """Drain the buffer.

    Returns:
        (X, Y) of every ``G1`` that carries both, in order.
    """
    moves: list[tuple[float, float]] = []
    for line in ap.get_gcode():
        if not line.startswith("G1"):
            continue
        words = {w[0]: w[1:] for w in line.split()[1:]}
        if "X" in words and "Y" in words:
            moves.append((float(words["X"]), float(words["Y"])))
    return moves


class TestModel:
    def test_defaults_to_no_offset(self) -> None:
        model = PipetteModel.model_validate({
            "name": "p",
            "syringe": {"max_travel_mm": 60.0},
            "servo": {},
        })

        assert (model.deck_offset.x, model.deck_offset.y) == (0.0, 0.0)
        assert model.tipbox is None

    def test_a_non_finite_offset_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DeckOffset(x=float("inf"))


class TestDeckTargetsAreShifted:
    def test_deck_coordinate_shifts_x_and_y_only(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = pipette_with_plates
        raw = ap.location_manager.get_coordinate("plate_a", row=0, col=0)
        _set_offset(ap, x=36.7, y=3.0)

        shifted = ap.get_deck_coordinate("plate_a", row=0, col=0)

        assert shifted == Coordinate(x=raw.x + 36.7, y=raw.y + 3.0, z=raw.z)

    def test_aspirate_and_dispense_go_to_the_shifted_wells(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = pipette_with_plates
        ap.state.tip_state = TipState.ATTACHED
        raw = ap.location_manager.get_coordinate("plate_a", row=0, col=1)
        _set_offset(ap, x=10.0)
        ap.get_gcode()

        ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=1)
        ap.dispense_volume("plate_a", dest_row=0, dest_col=1)

        assert set(_xy_moves(ap)) == {(raw.x + 10.0, raw.y)}

    def test_waste_is_shifted(self, pipette_with_plates: AutoPipette) -> None:
        ap = pipette_with_plates
        ap.state.tip_state = TipState.ATTACHED
        ap.dispose_tip()
        unshifted = _xy_moves(ap)[0]
        ap.state.tip_state = TipState.ATTACHED
        _set_offset(ap, x=20.0)

        ap.dispose_tip()

        assert _xy_moves(ap)[0] == (unshifted[0] + 20.0, unshifted[1])

    def test_tipboxes_are_not_shifted(self, pipette_with_plates: AutoPipette) -> None:
        ap = pipette_with_plates
        box = ap.location_manager.get_coordinate("tipbox", row=0, col=0)
        _set_offset(ap, x=50.0)

        assert ap.get_deck_coordinate("tipbox", row=0, col=0) == box
