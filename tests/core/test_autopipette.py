"""Unit tests for :class:`tricca_autopipette.core.autopipette.AutoPipette`.

`AutoPipette` is pure sync logic with no I/O -- every method just mutates
in-memory state and appends G-code strings to a buffer -- so these tests
exercise it directly against the repo's real default config, with no mocks.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from tricca_autopipette.core.autopipette import AutoPipette
from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import (
    NoTipboxError,
    NoWasteContainerError,
    TipAlreadyOnError,
    VolumeCapacityError,
)
from tricca_autopipette.core.pipette_models import TipState


class TestSwitchLiquid:
    def test_switches_active_liquid_and_reloads_syringe_params(
        self, autopipette: AutoPipette
    ) -> None:
        assert autopipette.active_liquid == "water"

        autopipette.switch_liquid("methanol")

        assert autopipette.active_liquid == "methanol"
        # methanol.json overrides speed_aspirate/speed_dispense from the
        # pipette defaults (100.0/200.0 in p100_vertical.json).
        assert autopipette.syringe.speed_aspirate == pytest.approx(80.0)
        assert autopipette.syringe.speed_dispense == pytest.approx(150.0)

    def test_unknown_liquid_raises_value_error(self, autopipette: AutoPipette) -> None:
        with pytest.raises(ValueError, match="not found"):
            autopipette.switch_liquid("not_a_real_liquid")

        # Failed switch must not mutate state.
        assert autopipette.active_liquid == "water"


class TestCoordinateSystem:
    def test_absolute_and_relative_emit_expected_gcode(
        self, autopipette: AutoPipette
    ) -> None:
        autopipette.set_coor_sys("absolute")
        autopipette.set_coor_sys(mode="relative")

        gcode = autopipette.get_gcode()
        assert any("G90" in line for line in gcode)
        assert any("G91" in line for line in gcode)

    def test_invalid_mode_raises_value_error(self, autopipette: AutoPipette) -> None:
        with pytest.raises(ValueError, match="Invalid coordinate system mode"):
            autopipette.set_coor_sys("diagonal")


class TestInitPipette:
    def test_marks_homed_and_emits_homing_gcode(self, autopipette: AutoPipette) -> None:
        assert autopipette.state.homed is False

        autopipette.init_pipette()

        assert autopipette.state.homed is True
        gcode = autopipette.get_gcode()
        assert any("G28" in line for line in gcode)  # home_axis
        assert any("SET_SERVO" in line for line in gcode)  # home_servo
        assert any("MANUAL_STEPPER" in line for line in gcode)  # home_pipette_stepper


class TestGCodeBuffer:
    def test_get_gcode_drains_the_buffer(self, autopipette: AutoPipette) -> None:
        autopipette.gcode_wait(500)
        autopipette.gcode_print("hello")

        first = autopipette.get_gcode()
        assert len(first) == 2

        # get_gcode() is destructive -- a second call sees nothing new.
        assert autopipette.get_gcode() == []

    def test_header_is_not_cleared_by_get_gcode(self, autopipette: AutoPipette) -> None:
        header_before = autopipette.get_header()
        autopipette.gcode_wait(100)
        autopipette.get_gcode()
        header_after = autopipette.get_header()

        assert header_before == header_after
        assert len(header_after) > 0


class TestTipHandling:
    def test_next_tip_without_tipbox_raises_no_tipbox_error(
        self, autopipette: AutoPipette
    ) -> None:
        with pytest.raises(NoTipboxError):
            autopipette.next_tip()

    def test_next_tip_attaches_and_moves(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.next_tip()

        assert pipette_with_plates.state.tip_state == TipState.ATTACHED
        gcode = pipette_with_plates.get_gcode()
        assert any("G0" in line or "G1" in line for line in gcode)

    def test_next_tip_twice_raises_tip_already_on_error(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.next_tip()

        with pytest.raises(TipAlreadyOnError):
            pipette_with_plates.next_tip()

    def test_eject_tip_detaches(self, pipette_with_plates: AutoPipette) -> None:
        pipette_with_plates.next_tip()

        pipette_with_plates.eject_tip()

        assert pipette_with_plates.state.tip_state == TipState.DETACHED

    def test_dispose_tip_without_waste_container_raises(
        self, autopipette: AutoPipette
    ) -> None:
        with pytest.raises(NoWasteContainerError):
            autopipette.dispose_tip()

    def test_dispose_tip_detaches_via_waste_container(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.next_tip()

        pipette_with_plates.dispose_tip()

        assert pipette_with_plates.state.tip_state == TipState.DETACHED


class TestAspirateDispenseVolume:
    def test_aspirate_from_plain_coordinate_raises_value_error(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.location_manager.set_coordinate(
            "home", Coordinate(x=0, y=0, z=0)
        )

        with pytest.raises(ValueError, match="Aspiration requires a plate"):
            pipette_with_plates.aspirate_volume(10.0, "home")

    def test_dispense_to_plain_coordinate_raises_value_error(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.location_manager.set_coordinate(
            "home", Coordinate(x=0, y=0, z=0)
        )

        with pytest.raises(ValueError, match="Dispensing requires a plate"):
            pipette_with_plates.dispense_volume("home", volume=10.0)

    def test_aspirate_then_dispense_updates_liquid_state(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.aspirate_volume(20.0, "plate_a")
        assert pipette_with_plates.state.has_liquid is True

        pipette_with_plates.dispense_volume("plate_a", volume=20.0)
        assert pipette_with_plates.state.has_liquid is False


class TestResolveTechnique:
    """water.json sets both gaps to 0; methanol.json sets 5/2 and 2 prewets."""

    def test_unset_takes_the_active_profile_value(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.switch_liquid("methanol")

        pre, post, prewet_cycles, prewet_vol_ul = (
            pipette_with_plates.resolve_technique()
        )

        assert pre == pytest.approx(5.0)
        assert post == pytest.approx(2.0)
        assert prewet_cycles == 2
        assert prewet_vol_ul == pytest.approx(10.0)

    def test_explicit_argument_beats_the_profile(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.switch_liquid("methanol")

        pre, post, _, _ = pipette_with_plates.resolve_technique(
            pre_air_gap_ul=12.0, post_air_gap_ul=1.0
        )

        assert pre == pytest.approx(12.0)
        assert post == pytest.approx(1.0)

    def test_explicit_zero_beats_a_non_zero_profile(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # The regression the `float | None` signatures exist to prevent: with
        # zero-defaulted floats, "--pre_air_gap_ul 0" was indistinguishable
        # from "flag omitted" and the profile's 5uL would silently win.
        pipette_with_plates.switch_liquid("methanol")

        pre, post, prewet_cycles, _ = pipette_with_plates.resolve_technique(
            pre_air_gap_ul=0.0, post_air_gap_ul=0.0, prewet_cycles=0
        )

        assert pre == pytest.approx(0.0)
        assert post == pytest.approx(0.0)
        assert prewet_cycles == 0

    def test_profile_without_technique_falls_back_to_pipette_defaults(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.switch_liquid("water")

        pre, post, prewet_cycles, _ = pipette_with_plates.resolve_technique()

        assert pre == pytest.approx(0.0)
        assert post == pytest.approx(0.0)
        assert prewet_cycles == 0

    def test_switching_liquid_changes_the_resolved_technique(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.switch_liquid("water")
        assert pipette_with_plates.resolve_technique()[0] == pytest.approx(0.0)

        pipette_with_plates.switch_liquid("methanol")
        assert pipette_with_plates.resolve_technique()[0] == pytest.approx(5.0)

    def test_aspirate_volume_uses_the_profile_when_flags_are_omitted(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.switch_liquid("methanol")

        with patch.object(
            pipette_with_plates,
            "fit_air_volumes",
            wraps=pipette_with_plates.fit_air_volumes,
        ) as spy_fit:
            pipette_with_plates.aspirate_volume(20.0, "plate_a")

        assert spy_fit.call_args.args == pytest.approx((20.0, 5.0, 2.0))


class TestFitAirVolumes:
    """The p100_vertical fixture is a 100uL syringe with a 2uL margin."""

    def test_usable_capacity_excludes_the_margin(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        assert pipette_with_plates.usable_capacity_ul() == pytest.approx(98.0)

    def test_air_that_fits_is_left_alone(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        assert pipette_with_plates.fit_air_volumes(50.0, 30.0, 2.0) == pytest.approx((
            30.0,
            2.0,
        ))

    def test_post_air_is_preserved_and_pre_air_shrunk(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # 90uL of liquid leaves 8uL of headroom: the 2uL anti-drip cushion
        # survives intact and the pre-gap absorbs the shortfall.
        pre, post = pipette_with_plates.fit_air_volumes(90.0, 30.0, 2.0)

        assert post == pytest.approx(2.0)
        assert pre == pytest.approx(6.0)

    def test_both_gaps_collapse_when_liquid_fills_the_syringe(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        assert pipette_with_plates.fit_air_volumes(98.0, 30.0, 2.0) == pytest.approx((
            0.0,
            0.0,
        ))

    def test_shrinking_a_gap_is_logged_as_a_warning(
        self, pipette_with_plates: AutoPipette, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            pipette_with_plates.fit_air_volumes(90.0, 30.0, 2.0)

        assert "pre_air_gap reduced from 30.0 μL to 6.0 μL" in caplog.text

    def test_liquid_beyond_usable_capacity_raises(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # Shrinking air cannot rescue this -- aspirating less liquid would
        # silently deliver the wrong amount, so it has to be an error.
        with pytest.raises(VolumeCapacityError, match="exceeds usable syringe"):
            pipette_with_plates.fit_air_volumes(99.0, 0.0, 0.0)

    def test_aspirate_volume_applies_the_clamp(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.aspirate_volume(
            90.0, "plate_a", pre_air_gap_ul=30.0, post_air_gap_ul=2.0
        )

        # 6uL pre-gap + 90uL liquid + 2uL post-gap == the 98uL usable
        # capacity; the unclamped 30uL pre-gap would have overrun it.
        gcode = "\n".join(pipette_with_plates.get_gcode())
        assert "MOVE=" in gcode
        assert pipette_with_plates.state.has_liquid is True


class TestPipetteTransfer:
    def test_negative_volume_raises_value_error(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        with pytest.raises(ValueError, match="Volume must be positive"):
            pipette_with_plates.pipette(vol_ul=-5.0, source="plate_a", dest="plate_a")

    def test_picks_up_tip_when_detached_and_transfers(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.DETACHED

        pipette_with_plates.pipette(vol_ul=50.0, source="plate_a", dest="plate_a")

        # keep_tip defaults to False -> tip is disposed of at the end.
        assert pipette_with_plates.state.tip_state == TipState.DETACHED
        assert pipette_with_plates.state.has_liquid is False

    def test_keep_tip_leaves_tip_attached(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        pipette_with_plates.pipette(
            vol_ul=50.0, source="plate_a", dest="plate_a", keep_tip=True
        )

        assert pipette_with_plates.state.tip_state == TipState.ATTACHED

    def test_large_volume_is_chunked_by_max_syringe_capacity(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # p100_vertical is a 100uL syringe with a 2uL capacity margin, so a
        # chunk is 98uL of usable capacity -- a 250uL transfer splits into
        # [98, 98, 54] rather than [100, 100, 50].
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        with patch.object(
            pipette_with_plates,
            "aspirate_volume",
            wraps=pipette_with_plates.aspirate_volume,
        ) as spy_aspirate:
            pipette_with_plates.pipette(
                vol_ul=250.0, source="plate_a", dest="plate_a", keep_tip=True
            )

        aspirated_volumes = [call.args[0] for call in spy_aspirate.call_args_list]
        assert aspirated_volumes == pytest.approx([98.0, 98.0, 54.0])

    def test_air_gaps_come_out_of_the_per_chunk_budget(
        self, pipette_with_plates: AutoPipette
    ) -> None:
        # 98uL usable, less a 30uL pre-gap and a 2uL post-gap, leaves 66uL of
        # liquid per chunk. Chunking on max_volume_ul alone would overflow the
        # syringe by the air overhead on every full chunk.
        pipette_with_plates.state.tip_state = TipState.ATTACHED

        with patch.object(
            pipette_with_plates,
            "aspirate_volume",
            wraps=pipette_with_plates.aspirate_volume,
        ) as spy_aspirate:
            pipette_with_plates.pipette(
                vol_ul=100.0,
                source="plate_a",
                dest="plate_a",
                pre_air_gap_ul=30.0,
                post_air_gap_ul=2.0,
                keep_tip=True,
            )

        aspirated_volumes = [call.args[0] for call in spy_aspirate.call_args_list]
        assert aspirated_volumes == pytest.approx([66.0, 34.0])
