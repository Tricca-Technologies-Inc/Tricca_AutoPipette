"""Unit tests for the cross-cutting decorators added in Phase 3 of the

ports-and-adapters migration (see CLAUDE.md): ``daemon/service.py``'s
``require_homed`` and ``persist_tip_liquid_state``. Per-method
``NotHomedError`` coverage lives alongside each command group's own tests
(``test_service_movement.py``/``test_service_pipette.py``); this file
covers the shared persistence behavior once rather than per method.
"""

from __future__ import annotations

from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.daemon.service import AutoPipetteService


def _set_homed(service: AutoPipetteService, homed: bool) -> None:
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.set_homed(homed)


class TestPersistTipLiquidState:
    def test_first_decorated_call_persists_a_baseline_snapshot(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        # `_last_persisted_state` starts as None, so even a soft no-op
        # first call persists once -- there's no prior snapshot to compare
        # against yet.
        assert isinstance(service_with_plates.moonraker_state, FakeMoonrakerState)
        _set_homed(service_with_plates, True)

        service_with_plates.eject_tip()  # no tip attached: a soft no-op

        assert len(service_with_plates.moonraker_state.saved_states) == 1

    def test_does_not_persist_again_when_state_is_unchanged(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        assert isinstance(service_with_plates.moonraker_state, FakeMoonrakerState)
        _set_homed(service_with_plates, True)
        service_with_plates.eject_tip()  # baseline snapshot
        assert len(service_with_plates.moonraker_state.saved_states) == 1

        service_with_plates.eject_tip()  # still no tip attached: unchanged

        assert len(service_with_plates.moonraker_state.saved_states) == 1

    def test_persists_again_after_a_real_state_change(
        self, service_with_plates: AutoPipetteService
    ) -> None:
        assert isinstance(service_with_plates.moonraker_state, FakeMoonrakerState)
        _set_homed(service_with_plates, True)
        service_with_plates.eject_tip()  # baseline snapshot
        assert len(service_with_plates.moonraker_state.saved_states) == 1

        service_with_plates.next_tip()  # actually picks up a tip

        assert len(service_with_plates.moonraker_state.saved_states) == 2
        tip_state, has_liquid, _ = service_with_plates.moonraker_state.saved_states[-1]
        assert tip_state == "attached"
        assert has_liquid is False

    def test_persists_even_when_the_wrapped_method_raises(
        self, service: AutoPipetteService
    ) -> None:
        # switch_liquid() raising ValueError for an unknown liquid must not
        # prevent the finally-block persistence from running -- the
        # decorator must not swallow or reorder the raise.
        assert isinstance(service.moonraker_state, FakeMoonrakerState)

        try:
            service.switch_liquid("not_a_real_liquid")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for an unknown liquid")

        assert len(service.moonraker_state.saved_states) == 1

    def test_switch_liquid_persists_the_new_active_liquid(
        self, service: AutoPipetteService
    ) -> None:
        assert isinstance(service.moonraker_state, FakeMoonrakerState)

        service.switch_liquid("methanol")

        assert len(service.moonraker_state.saved_states) == 1
        _, _, current_liquid = service.moonraker_state.saved_states[0]
        assert current_liquid == "methanol"
