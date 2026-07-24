"""A minimal duck-typed stand-in for ``daemon.moonraker_state.MoonrakerStateTracker``.

Exposes ``is_homed()`` -- called by ``daemon/service.py``'s ``require_homed``
decorator -- and ``save_tip_liquid_state()`` -- called by its
``persist_tip_liquid_state`` decorator -- so tests can control homed state
and assert on persisted state directly, without subscribing to a real
Moonraker connection.
"""

from __future__ import annotations


class FakeMoonrakerState:
    """Fake homed-state source, settable directly by a test."""

    def __init__(self, *, homed: bool = False) -> None:
        """Initialize with a starting homed state.

        Args:
            homed: Initial value ``is_homed()`` should report.
        """
        self._homed = homed
        self.saved_states: list[tuple[str, bool, str | None]] = []

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
