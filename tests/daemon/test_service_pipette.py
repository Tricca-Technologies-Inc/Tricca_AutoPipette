"""Unit tests for ``AutoPipetteService``'s pipette commands (Phase 1 of the

ports-and-adapters migration, PipetteCommands group -- see CLAUDE.md).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.commands.tap_cmd_parsers import (
    AspirateArgs,
    DispenseArgs,
    PipetteArgs,
)
from tricca_autopipette.core.pipette_exceptions import (
    NotHomedError,
    NoTipboxError,
    NoWasteContainerError,
    TipAlreadyOnError,
)
from tricca_autopipette.core.pipette_models import TipState
from tricca_autopipette.core.splits import Split
from tricca_autopipette.daemon.service import AutoPipetteService


def _aspirate_args(**overrides: object) -> AspirateArgs:
    defaults: dict[str, object] = {
        "vol_ul": 20.0,
        "source": "plate_a",
        "src_row": None,
        "src_col": None,
        "pre_air_gap_ul": 0.0,
        "post_air_gap_ul": 0.0,
        "prewet_cycles": 0,
        "prewet_vol_ul": 10.0,
    }
    defaults.update(overrides)
    return AspirateArgs(**defaults)  # type: ignore[arg-type]


def _dispense_args(**overrides: object) -> DispenseArgs:
    defaults: dict[str, object] = {
        "dest": "plate_a",
        "dest_row": None,
        "dest_col": None,
        "volume": 20.0,
        "wiggle": False,
    }
    defaults.update(overrides)
    return DispenseArgs(**defaults)  # type: ignore[arg-type]


def _pipette_args(**overrides: object) -> PipetteArgs:
    defaults: dict[str, object] = {
        "vol_ul": 20.0,
        "source": "plate_a",
        "dest": "plate_a",
        "disp_vol_ul": None,
        "src_row": None,
        "src_col": None,
        "dest_row": None,
        "dest_col": None,
        "tipbox_name": None,
        "pre_air_gap_ul": 0.0,
        "post_air_gap_ul": 0.0,
        "prewet_cycles": 0,
        "prewet_vol_ul": 10.0,
        "wiggle": False,
        "keep_tip": True,
        "splits": None,
        "leftover": None,
    }
    defaults.update(overrides)
    return PipetteArgs(**defaults)  # type: ignore[arg-type]


def _set_homed(service: AutoPipetteService, homed: bool) -> None:
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.set_homed(homed)


class TestAspirate:
    def test_no_tip_attached_raises_not_homed_when_unhomed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # Phase 3's `require_homed` decorator always runs first, so an
        # unhomed call raises even for an input that would otherwise be a
        # soft "no tip attached" no-op -- see the Pipette-commands-group
        # comment in `daemon/service.py`.
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.aspirate(_aspirate_args())

    def test_no_tip_attached_is_a_noop_when_homed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.aspirate(_aspirate_args())

        assert result.ok is False
        assert "next_tip" in result.message

    def test_requires_homed_once_tip_attached(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        _set_homed(service_with_plates, False)

        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.aspirate(_aspirate_args())

    def test_succeeds_when_homed_and_tip_attached(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        result = service_with_plates.aspirate(_aspirate_args(vol_ul=20.0))

        assert result.ok is True
        assert service_with_plates._autopipette.state.has_liquid is True


class TestDispense:
    def test_requires_homed(self, service_with_plates: AutoPipetteService) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.dispense(_dispense_args())

    def test_no_liquid_is_a_noop(self, service_with_plates: AutoPipetteService) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        result = service_with_plates.dispense(_dispense_args())

        assert result.ok is False
        assert "aspirate" in result.message

    def test_succeeds_after_aspirating(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        service_with_plates.aspirate(_aspirate_args(vol_ul=20.0))

        result = service_with_plates.dispense(_dispense_args(volume=20.0))

        assert result.ok is True
        assert service_with_plates._autopipette.state.has_liquid is False


class TestTransfer:
    def test_non_positive_volume_raises_not_homed_when_unhomed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # See the aspirate no-tip-attached test above for why this now
        # raises instead of returning an ok=False no-op.
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.transfer(_pipette_args(vol_ul=0.0))

    def test_non_positive_volume_is_a_noop_when_homed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.transfer(_pipette_args(vol_ul=0.0))

        assert result.ok is False
        assert "greater than zero" in result.message

    def test_requires_homed(self, service_with_plates: AutoPipetteService) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.transfer(_pipette_args())

    def test_full_transfer_keeping_tip(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.transfer(_pipette_args(keep_tip=True))

        assert result.ok is True
        assert "plate_a" in result.message

    def test_no_tipbox_raises_no_tipbox_error(
        self, service: AutoPipetteService
    ) -> None:
        # `service` (not `service_with_plates`) has no tipbox configured.
        # `AutoPipette.pipette()` only auto-picks-up a tip when tip_state is
        # explicitly DETACHED (not the default UNKNOWN) -- force that so the
        # tip-pickup path (and thus the NoTipboxError) is actually exercised.
        _set_homed(service, True)
        service._autopipette.state.tip_state = TipState.DETACHED

        with pytest.raises(NoTipboxError):
            service.transfer(_pipette_args(source="nowhere", dest="nowhere"))

    def test_no_waste_container_raises_when_disposing_tip(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates._autopipette.location_manager.remove_location("waste")

        with pytest.raises(NoWasteContainerError):
            service_with_plates.transfer(_pipette_args(keep_tip=False))


class TestTransferSplits:
    """``--splits`` routes ``transfer`` to ``AutoPipette.pipette_splits``."""

    def test_splits_dispatch_to_pipette_splits(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        autopipette = service_with_plates._autopipette

        with patch.object(
            autopipette, "pipette_splits", wraps=autopipette.pipette_splits
        ) as spy_splits:
            result = service_with_plates.transfer(
                _pipette_args(
                    vol_ul=20.0,
                    splits="plate_a:12@A1;plate_a:8@A3",
                    keep_tip=True,
                )
            )

        assert result.ok is True
        assert spy_splits.call_count == 1
        assert spy_splits.call_args.kwargs["splits"] == [
            Split(dest="plate_a", vol_ul=12.0, well_id="A1"),
            Split(dest="plate_a", vol_ul=8.0, well_id="A3"),
        ]

    def test_message_and_gcode_comment_name_every_destination(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.transfer(
            _pipette_args(
                vol_ul=20.0, splits="plate_a:12@A1;plate_a:8@A3", keep_tip=True
            )
        )

        assert "plate_a:12.0" in result.message
        assert "plate_a:8.0" in result.message

    def test_malformed_spec_returns_not_ok_rather_than_raising(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.transfer(_pipette_args(splits="plate_a"))

        assert result.ok is False
        assert "expected 'DEST:VOL'" in result.message

    def test_leftover_omitted_on_a_short_dispense_raises(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        with pytest.raises(ValueError, match="--leftover keep or --leftover waste"):
            service_with_plates.transfer(
                _pipette_args(vol_ul=20.0, splits="plate_a:12@A1", keep_tip=True)
            )

    def test_leftover_waste_without_a_container_raises(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates._autopipette.location_manager.remove_location("waste")

        with pytest.raises(NoWasteContainerError):
            service_with_plates.transfer(
                _pipette_args(
                    vol_ul=20.0,
                    splits="plate_a:12@A1",
                    leftover="waste",
                    keep_tip=True,
                )
            )

    def test_plain_transfer_still_takes_the_single_dispense_path(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        autopipette = service_with_plates._autopipette

        with patch.object(
            autopipette, "pipette_splits", wraps=autopipette.pipette_splits
        ) as spy_splits:
            result = service_with_plates.transfer(_pipette_args(keep_tip=True))

        assert result.ok is True
        assert spy_splits.call_count == 0


class TestTipManagement:
    def test_next_tip_requires_homed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.next_tip()

    def test_next_tip_then_next_tip_raises_tip_already_on_error(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        with pytest.raises(TipAlreadyOnError):
            service_with_plates.next_tip()

    def test_eject_tip_requires_homed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.eject_tip()

    def test_eject_tip_without_tip_is_a_noop(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.eject_tip()

        assert result.ok is False
        assert "eject" in result.message

    def test_eject_tip_detaches(self, service_with_plates: AutoPipetteService) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        result = service_with_plates.eject_tip()

        assert result.ok is True

    def test_dispose_tip_requires_homed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.dispose_tip()

    def test_dispose_tip_without_tip_is_a_noop(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.dispose_tip()

        assert result.ok is False
        assert "dispose" in result.message

    def test_dispose_tip_succeeds(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        result = service_with_plates.dispose_tip()

        assert result.ok is True

    def test_dispose_tip_without_waste_container_raises(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        service_with_plates._autopipette.location_manager.remove_location("waste")

        with pytest.raises(NoWasteContainerError):
            service_with_plates.dispose_tip()

    def test_change_tip_requires_homed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        with pytest.raises(NotHomedError, match="not homed"):
            service_with_plates.change_tip()

    def test_change_tip_picks_up_first_tip_when_none_attached(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        result = service_with_plates.change_tip()

        assert result.ok is True

    def test_change_tip_disposes_and_repicks(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        result = service_with_plates.change_tip()

        assert result.ok is True
