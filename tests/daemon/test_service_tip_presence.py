"""Tests for per-tipbox consumed-position persistence.

Klipper has no notion of which tip positions are empty, so this is a durability
layer over Moonraker's ``server.database``, in the same spirit as the existing
tip/liquid persistence. The safety-critical case is
``test_reshaped_box_is_not_restored``: reapplying a stored presence map to a
differently-shaped plate would mark the wrong physical positions empty and send
the pipette to fetch a tip that is not there.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.pipette_exceptions import (
    NotHomedError,
    TipAlreadyOnError,
)
from tricca_autopipette.core.tipbox_manager import TipBoxManager
from tricca_autopipette.daemon.service import AutoPipetteService


def _fake_state(service: AutoPipetteService) -> FakeMoonrakerState:
    """Return the service's fake state tracker, typed."""
    return cast("FakeMoonrakerState", service.moonraker_state)


def _manager(service: AutoPipetteService) -> TipBoxManager:
    return service._autopipette.location_manager.tipbox_manager


def _set_homed(service: AutoPipetteService, homed: bool) -> None:
    _fake_state(service).set_homed(homed)


class TestPersistOnConsumption:
    def test_next_tip_persists_presence(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        _set_homed(service_with_plates, True)

        service_with_plates.next_tip()

        saved = _fake_state(service_with_plates).saved_tip_presence
        assert saved, "consuming a tip must persist the new presence map"
        assert saved[-1]["tipbox"]["present"][0] is False

    def test_snapshot_carries_dimensions(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """Dimensions are what let restore detect a reconfigured box."""
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()

        record = _fake_state(service_with_plates).saved_tip_presence[-1]["tipbox"]
        assert "num_row" in record
        assert "num_col" in record

    def test_unchanged_state_is_not_rewritten(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """Avoids a Moonraker round trip per command that touches no tips."""
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        before = len(_fake_state(service_with_plates).saved_tip_presence)

        service_with_plates.eject_tip()  # detaches, but consumes no new tip

        assert len(_fake_state(service_with_plates).saved_tip_presence) == before

    def test_change_tip_persists(self, service_with_plates: AutoPipetteService) -> None:
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        before = len(_fake_state(service_with_plates).saved_tip_presence)

        service_with_plates.change_tip()

        assert len(_fake_state(service_with_plates).saved_tip_presence) > before

    def test_persists_even_when_the_command_fails(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """A tip picked up before a later failure is still physically gone."""
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        consumed_before = _manager(service_with_plates).remaining
        saves_before = len(_fake_state(service_with_plates).saved_tip_presence)

        # A second pickup fails without consuming anything, so nothing new
        # should be written -- but the call must not blow up the persistence
        # path either, since it runs in a `finally`.
        with pytest.raises(TipAlreadyOnError):
            service_with_plates.next_tip()

        assert _manager(service_with_plates).remaining == consumed_before
        assert len(_fake_state(service_with_plates).saved_tip_presence) == saves_before

    def test_without_moonraker_the_command_fails_closed(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """No Moonraker means no homed truth, so the tip path is unreachable.

        This is why the persistence decorator's ``moonraker_state is None``
        guard can never fire for a gated method -- the interlock rejects the
        call first. The guard remains for ungated callers and for safety.
        """
        _set_homed(service_with_plates, True)
        service_with_plates.moonraker_state = None

        with pytest.raises(NotHomedError):
            service_with_plates.next_tip()


class TestRestore:
    def test_restores_consumption_from_a_prior_run(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        manager = _manager(service_with_plates)
        capacity = manager.boxes["tipbox"].capacity
        stored: dict[str, Any] = {
            "tipbox": {
                "num_row": manager.boxes["tipbox"].num_row,
                "num_col": manager.boxes["tipbox"].num_col,
                "present": [False] + [True] * (capacity - 1),
            }
        }

        service_with_plates._apply_persisted_tip_presence(stored)

        assert manager.remaining == capacity - 1
        assert manager.peek_tip() == ("tipbox", 1)

    def test_reshaped_box_is_not_restored(
        self,
        service_with_plates: AutoPipetteService,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The safety case: a stale map must never be reindexed onto a plate."""
        manager = _manager(service_with_plates)
        stored: dict[str, Any] = {
            "tipbox": {"num_row": 99, "num_col": 99, "present": [False] * 9801}
        }

        service_with_plates._apply_persisted_tip_presence(stored)

        assert manager.remaining == manager.boxes["tipbox"].capacity
        assert "tipbox" in caplog.text

    def test_empty_store_leaves_boxes_full(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """First run: nothing persisted, so every box is assumed full."""
        manager = _manager(service_with_plates)

        service_with_plates._apply_persisted_tip_presence({})

        assert manager.remaining == manager.capacity

    def test_unknown_box_names_are_ignored(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """A stale DB entry for an unloaded box must not break startup."""
        manager = _manager(service_with_plates)

        service_with_plates._apply_persisted_tip_presence({
            "removed_box": {"num_row": 1, "num_col": 1, "present": [False]}
        })

        assert manager.remaining == manager.capacity

    def test_restore_seeds_the_dedup_baseline(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """Restoring must not immediately rewrite what it just read back."""
        manager = _manager(service_with_plates)
        capacity = manager.boxes["tipbox"].capacity
        stored: dict[str, Any] = {
            "tipbox": {
                "num_row": manager.boxes["tipbox"].num_row,
                "num_col": manager.boxes["tipbox"].num_col,
                "present": [False] + [True] * (capacity - 1),
            }
        }
        service_with_plates._apply_persisted_tip_presence(stored)
        _set_homed(service_with_plates, True)

        service_with_plates.eject_tip()  # consumes nothing

        assert _fake_state(service_with_plates).saved_tip_presence == []

    def test_round_trip_through_the_fake_database(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        """Consume, persist, then restore into a fresh manager."""
        _set_homed(service_with_plates, True)
        service_with_plates.next_tip()
        service_with_plates.change_tip()

        saved = _fake_state(service_with_plates).saved_tip_presence[-1]
        manager = _manager(service_with_plates)
        remaining_before = manager.remaining

        # Simulate a daemon restart: rebuild presence from the stored snapshot.
        manager.reset_all()
        assert manager.restore(saved) == []
        assert manager.remaining == remaining_before
