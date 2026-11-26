"""Tests for a pipette's deck offset.

A pipette file may set ``deck_offset: {x, y}`` when its nozzle sits beside
the head's reference nozzle (Tyson's P1000 is 36.7 mm to one side of its
P100). The offset shifts every deck target the active pipette visits, so
two pipettes share one locations file. Tipboxes are the exception: each
pipette has its own box, located in that pipette's frame.

Z is added to dip depths, not to travel height: a longer nozzle (negative
Z) needs less downward travel to reach the same depth in a well. Tipbox
dips are not shifted.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_models import DeckOffset, PipetteModel, TipState


def _set_offset(
    ap: AutoPipette, x: float = 0.0, y: float = 0.0, z: float = 0.0
) -> None:
    ap.pipette_model = ap.pipette_model.model_copy(
        update={"deck_offset": DeckOffset(x=x, y=y, z=z)}
    )


def _deepest_z(ap: AutoPipette) -> float:
    """Drain the buffer.

    Returns:
        The largest (lowest) Z any ``G1`` moves to.
    """
    zs = [
        float(w[1:])
        for line in ap.get_gcode()
        if line.startswith("G1")
        for w in line.split()[1:]
        if w.startswith("Z")
    ]
    return max(zs)


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
            "syringe": {"max_travel_mm": 60.0, "lead_mm": 2.0},
            "servo": {},
        })

        offset = model.deck_offset
        assert (offset.x, offset.y, offset.z) == (0.0, 0.0, 0.0)
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


class TestDipDepthIsShifted:
    def test_aspirate_dispense_and_waste_dips_shift_by_z(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = pipette_with_plates

        def dips(z: float) -> list[float]:
            _set_offset(ap, z=z)
            ap.state.tip_state = TipState.ATTACHED
            with patch.object(ap, "dip_z_down", wraps=ap.dip_z_down) as spy:
                ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=0)
                ap.dispense_volume("plate_a", dest_row=0, dest_col=0)
                ap.dispose_tip()
            return [c.args[1] for c in spy.call_args_list]

        base = dips(0.0)

        assert len(base) == 3
        assert dips(-1.5) == pytest.approx([d - 1.5 for d in base])

    def test_tipbox_dip_is_not_shifted(self, pipette_with_plates: AutoPipette) -> None:
        ap = pipette_with_plates
        ap.get_gcode()
        ap.next_tip()
        unshifted = _deepest_z(ap)
        ap.state.tip_state = TipState.DETACHED
        _set_offset(ap, z=-1.5)

        ap.next_tip()

        assert _deepest_z(ap) == pytest.approx(unshifted)

    def test_a_dip_shifted_above_z0_is_refused(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = pipette_with_plates
        ap.state.tip_state = TipState.ATTACHED
        _set_offset(ap, z=-1000.0)

        with pytest.raises(ValueError, match=r"[Zz]"):
            ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=0)


class TestWasteDipIsClampedAtZ0:
    """A waste dip shifted above Z0 stays at Z0 (owner decision, 2026-11-26).

    Tyson's P1000 (``deck_offset.z = -42``) over a waste container with
    ``dip_top: 0`` would otherwise target Z=-42. Dropping a tip or emptying
    the tip from the top is safe over waste, so it is clamped there; a plate
    dip above Z0 is still refused (above).
    """

    @pytest.mark.parametrize("action", ["dispose_tip", "empty_tip_to_waste"])
    def test_a_waste_dip_above_z0_goes_to_z0(
        self, pipette_with_plates: AutoPipette, action: str
    ) -> None:
        ap = pipette_with_plates
        ap.state.tip_state = TipState.ATTACHED
        _set_offset(ap, z=-1000.0)

        with patch.object(ap, "dip_z_down", wraps=ap.dip_z_down) as spy:
            getattr(ap, action)()

        assert spy.call_args.args[1] == pytest.approx(0.0)
