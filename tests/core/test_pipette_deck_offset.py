"""Tests for pipette-model deck offset.

A pipette config may declare ``deck_offset: {x, y, z}`` to shift every
deck coordinate lookup (aspirate source, dispense destination, move_loc)
by that amount.  This lets two pipettes share a single location config
even when they are physically offset on the toolhead — the P1000 sits
to the right of the P100, so its x (and possibly y, z) coordinates all
differ by a fixed amount.

Tipbox coordinates are intentionally excluded: each tipbox has its own
absolute position in the locations file and is not shared between
pipettes.

Seams under test
----------------
1. ``PipetteModel.deck_offset`` — optional nested model, all axes default
   to 0.0, parses from JSON.
2. ``AutoPipette.get_deck_coordinate()`` — applies the active pipette's
   deck_offset to a resolved location coordinate.
3. ``AutoPipette.aspirate_volume()`` uses ``get_deck_coordinate`` so the
   source well is shifted.
4. ``AutoPipette.dispense_volume()`` uses ``get_deck_coordinate`` so the
   destination well is shifted.
5. Tipbox coordinates from ``next_tip``/``return_tip`` are NOT offset.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_models import (
    DeckOffset,
    PipetteModel,
    ServoConfig,
    PipetteSyringeKinematics,
    TipState,
)
from tricca_autopipette.core.plates import PlateParams
from tricca_autopipette.core.well import StrategyType, Well


# ── helpers ──────────────────────────────────────────────────────────────────


def _well(x: float, y: float, z: float = 5.0, dip_top: float = 5.0) -> Well:
    return Well(
        coor=Coordinate(x=x, y=y, z=z),
        dip_top=dip_top,
        strategy_type=StrategyType.SIMPLE,
    )


def _plate_params(x: float, y: float) -> PlateParams:
    return PlateParams(
        plate_type="array",
        well_template=_well(x=x, y=y),
        num_row=1,
        num_col=2,
        spacing_row=0.0,
        spacing_col=9.0,
    )


def _set_offset(ap: AutoPipette, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
    """Replace the active pipette model's deck_offset."""
    ap.pipette_model = ap.pipette_model.model_copy(
        update={"deck_offset": DeckOffset(x=x, y=y, z=z)}
    )


# ── Seam 1: DeckOffset model and PipetteModel.deck_offset field ──────────────


class TestDeckOffsetModel:
    def test_all_axes_default_to_zero(self) -> None:
        offset = DeckOffset()
        assert offset.x == 0.0
        assert offset.y == 0.0
        assert offset.z == 0.0

    def test_accepts_positive_values(self) -> None:
        offset = DeckOffset(x=10.5, y=2.0, z=0.5)
        assert offset.x == 10.5

    def test_accepts_negative_values(self) -> None:
        """Negative offsets are valid — the P1000 could be left of the P100."""
        offset = DeckOffset(x=-5.0, y=0.0, z=0.0)
        assert offset.x == -5.0

    def test_pipette_model_deck_offset_defaults_to_zero_offset(self) -> None:
        model = PipetteModel(
            name="P100",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0, min_volume_ul=0.5),
            servo=ServoConfig(),
        )
        assert model.deck_offset.x == 0.0
        assert model.deck_offset.y == 0.0
        assert model.deck_offset.z == 0.0

    def test_pipette_model_accepts_deck_offset(self) -> None:
        model = PipetteModel(
            name="P1000",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0, min_volume_ul=0.5),
            servo=ServoConfig(),
            deck_offset=DeckOffset(x=14.0, y=1.5, z=0.0),
        )
        assert model.deck_offset.x == 14.0
        assert model.deck_offset.y == 1.5

    def test_round_trips_through_json(self) -> None:
        model = PipetteModel(
            name="P1000",
            syringe=PipetteSyringeKinematics(max_travel_mm=60.0, min_volume_ul=0.5),
            servo=ServoConfig(),
            deck_offset=DeckOffset(x=14.0, y=1.5, z=0.5),
        )
        reloaded = PipetteModel.model_validate_json(model.model_dump_json())
        assert reloaded.deck_offset.x == 14.0
        assert reloaded.deck_offset.y == 1.5
        assert reloaded.deck_offset.z == 0.5

    def test_missing_deck_offset_in_json_gives_zero_offset(self) -> None:
        """Existing pipette JSON without deck_offset loads cleanly."""
        import json
        raw = json.dumps({
            "name": "P100",
            "syringe": {"max_travel_mm": 60.0, "min_volume_ul": 0.5},
            "servo": {},
        })
        model = PipetteModel.model_validate_json(raw)
        assert model.deck_offset.x == 0.0
        assert model.deck_offset.y == 0.0
        assert model.deck_offset.z == 0.0


# ── Seam 2: AutoPipette.get_deck_coordinate() ────────────────────────────────


class TestGetDeckCoordinate:
    def test_zero_offset_returns_location_unchanged(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        ap = pipette_with_plates
        _set_offset(ap, x=0.0, y=0.0, z=0.0)

        # Use explicit row/col to avoid advancing the plate cursor
        raw = ap.location_manager.get_coordinate("plate_a", row=0, col=0)
        shifted = ap.get_deck_coordinate("plate_a", row=0, col=0)

        assert shifted == raw

    def test_x_offset_shifts_x(self, pipette_with_plates: AutoPipette) -> None:
        ap = pipette_with_plates
        _set_offset(ap, x=14.0)

        raw = ap.location_manager.get_coordinate("plate_a", row=0, col=0)
        shifted = ap.get_deck_coordinate("plate_a", row=0, col=0)

        assert shifted.x == pytest.approx(raw.x + 14.0)
        assert shifted.y == pytest.approx(raw.y)
        assert shifted.z == pytest.approx(raw.z)

    def test_all_axes_offset(self, pipette_with_plates: AutoPipette) -> None:
        ap = pipette_with_plates
        _set_offset(ap, x=10.0, y=2.0, z=1.0)

        raw = ap.location_manager.get_coordinate("plate_a", row=0, col=0)
        shifted = ap.get_deck_coordinate("plate_a", row=0, col=0)

        assert shifted.x == pytest.approx(raw.x + 10.0)
        assert shifted.y == pytest.approx(raw.y + 2.0)
        assert shifted.z == pytest.approx(raw.z + 1.0)

    def test_forwards_row_col_to_location_manager(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        """Row/col indexing still works through the wrapper."""
        ap = pipette_with_plates
        _set_offset(ap, x=5.0)

        raw = ap.location_manager.get_coordinate("plate_a", row=0, col=1)
        shifted = ap.get_deck_coordinate("plate_a", row=0, col=1)

        assert shifted.x == pytest.approx(raw.x + 5.0)


# ── Seam 3 & 4: aspirate/dispense use get_deck_coordinate ────────────────────


def _gcode_lines(ap: AutoPipette) -> list[str]:
    """Drain buffered G-code and return individual non-comment lines."""
    lines = ap.get_gcode()
    return [ln for ln in lines if ln and not ln.startswith(";")]


import re


def _first_xy_x(lines: list[str]) -> float:
    """Extract the X value from the first XY move G-code line."""
    first = next(ln for ln in lines if "G1" in ln and " X" in ln and " Y" in ln)
    m = re.search(r"X([\d.]+)", first)
    assert m, f"No X in: {first}"
    return float(m.group(1))


class TestAspirateDeckOffset:
    def test_source_coordinate_is_shifted(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        """The G-code move to the source well reflects the deck offset."""
        ap = pipette_with_plates
        ap.next_tip()
        _gcode_lines(ap)  # drain tip-pickup G-code before measuring aspirate

        # Aspirate from explicit well col=0, zero offset
        _set_offset(ap, x=0.0)
        ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=0)
        x_zero = _first_xy_x(_gcode_lines(ap))

        # Same well, 14mm x offset
        _set_offset(ap, x=14.0)
        ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=0)
        x_offset = _first_xy_x(_gcode_lines(ap))

        assert x_offset == pytest.approx(x_zero + 14.0, abs=0.01)


class TestDispenseDeckOffset:
    def test_dest_coordinate_is_shifted(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        """The G-code move to the destination well reflects the deck offset."""
        ap = pipette_with_plates
        ap.next_tip()
        _gcode_lines(ap)  # drain tip-pickup G-code

        # Aspirate once so there is liquid to dispense
        _set_offset(ap, x=0.0)
        ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=0)
        _gcode_lines(ap)  # discard

        # Dispense to explicit well col=1, zero offset
        ap.dispense_volume("plate_a", volume=10.0, dest_row=0, dest_col=1)
        x_zero = _first_xy_x(_gcode_lines(ap))

        # Re-aspirate then dispense to same well with 20mm x offset
        ap.aspirate_volume(10.0, "plate_a", src_row=0, src_col=0)
        _gcode_lines(ap)  # discard

        _set_offset(ap, x=20.0)
        ap.dispense_volume("plate_a", volume=10.0, dest_row=0, dest_col=1)
        x_offset = _first_xy_x(_gcode_lines(ap))

        assert x_offset == pytest.approx(x_zero + 20.0, abs=0.01)


# ── Seam 5: tipbox coordinates are NOT offset ─────────────────────────────────


class TestTipboxNotOffset:
    def test_next_tip_coordinate_is_not_shifted(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        """The move-to-tipbox G-code is unaffected by deck_offset."""
        ap = pipette_with_plates

        # Pickup first tip, zero offset
        _set_offset(ap, x=0.0)
        ap.next_tip()
        x_zero = _first_xy_x(_gcode_lines(ap))
        ap.state.tip_state = TipState.DETACHED
        ap.state.tip_origin = None

        # Pickup second tip, large offset — tipbox has 2 wells in fixture
        _set_offset(ap, x=50.0)
        ap.next_tip()
        x_offset = _first_xy_x(_gcode_lines(ap))

        # Both go to tipbox wells — only spacing differs, not the 50mm offset
        # The tipbox fixture has spacing_col=9.0 so second well differs by 9mm,
        # not 50mm.  Just assert the offset did NOT add 50mm.
        assert abs(x_offset - x_zero) < 20.0, (
            f"Tipbox X shifted by {abs(x_offset - x_zero):.1f}mm — "
            "deck_offset should not apply to tipbox coordinates"
        )
