"""A minimal duck-typed stand-in for ``daemon.moonraker_state.MoonrakerStateTracker``.

Exposes ``is_homed()`` -- called by ``daemon/service.py``'s ``require_homed``
decorator -- plus ``save_tip_liquid_state()`` and ``save_tip_presence()`` --
called by its ``persist_tip_liquid_state`` and ``persist_tip_presence``
decorators -- so tests can control homed state and assert on persisted state
directly, without subscribing to a real Moonraker connection.
"""

from __future__ import annotations

from typing import Any


class FakeMoonrakerState:
    """Fake homed-state source, settable directly by a test."""

    def __init__(self, *, homed: bool = False) -> None:
        """Initialize with a starting homed state.

        Args:
            homed: Initial value ``is_homed()`` should report.
        """
        self._homed = homed
        self.saved_states: list[tuple[str, bool, str | None]] = []
        self.saved_tip_presence: list[dict[str, Any]] = []
        #: What ``load_tip_presence`` should return; set by a test to simulate
        #: state persisted by a previous daemon run.
        self.stored_tip_presence: dict[str, Any] = {}

    def is_homed(self) -> bool:
        """Return the fake's configured homed state."""
        return self._homed

    def set_homed(self, homed: bool) -> None:
        """Change the fake's homed state.

        Args:
            homed: New value ``is_homed()`` should report.
        """
        self._homed = homed

    def save_tip_liquid_state(
        self, tip_state: str, has_liquid: bool, current_liquid: str | None
    ) -> None:
        """Record a persisted-state call for later assertion.

        Args:
            tip_state: ``TipState`` value (as a string) that was persisted.
            has_liquid: Whether liquid was in the tip at persist time.
            current_liquid: Name of the active liquid profile, or None.
        """
        self.saved_states.append((tip_state, has_liquid, current_liquid))

    def save_tip_presence(self, snapshot: dict[str, Any]) -> None:
        """Record a persisted tip-presence call for later assertion.

        Args:
            snapshot: Per-tipbox records as produced by
                ``TipBoxManager.snapshot``.
        """
        self.saved_tip_presence.append(snapshot)

    def load_tip_presence(self) -> dict[str, Any]:
        """Return the tip presence a previous run would have persisted.

        Returns:
            Whatever a test assigned to ``stored_tip_presence``; empty by
            default, matching a first run.
        """
        return self.stored_tip_presence
