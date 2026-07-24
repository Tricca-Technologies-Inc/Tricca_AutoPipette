"""Live Klipper/Moonraker state tracking for the ``tapd`` daemon.

Replaces two things the pre-daemon architecture tracked as local, in-memory
guesses with values sourced from Moonraker itself:

- Homed-axes state: read from Klipper's ``toolhead`` object via
  ``printer.objects.subscribe`` instead of a manually-set boolean, so it can
  never go stale relative to the physical machine (Klipper itself clears
  ``homed_axes`` on restart/e-stop/fault).
- Print-job completion: read from ``print_stats.state`` transitions instead
  of inferring completion from a subprocess exit code.

Tip/liquid state has no Moonraker-native equivalent (Klipper has no concept
of "is a pipette tip attached"), so it is merely persisted through
Moonraker's ``server.database`` API for durability across daemon restarts,
via :meth:`MoonrakerStateTracker.load_tip_liquid_state` /
:meth:`save_tip_liquid_state`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from tricca_autopipette.moonraker.moonraker_requests import MoonrakerRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient

logger = logging.getLogger(__name__)

#: server.database namespace used to persist tip/liquid state.
DB_NAMESPACE = "tricca_autopipette"
DB_KEY_TIP_STATE = "tip_state"
DB_KEY_HAS_LIQUID = "has_liquid"
DB_KEY_CURRENT_LIQUID = "current_liquid"

#: Axes that must all be reported homed by Klipper for the interlock to pass.
REQUIRED_HOMED_AXES = frozenset({"x", "y", "z"})


def _as_dict(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """Narrow a loosely-typed JSON value to a dict, defaulting to empty.

    Args:
        value: Value to narrow, typically from a JSON-RPC response or
            notification payload of otherwise unknown shape.

    Returns:
        ``value`` if it is a dict, otherwise an empty dict.
    """
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return {}


class MoonrakerStateTracker:
    """Tracks live homed-axes and print-job state via Moonraker subscriptions.

    Attributes:
        client: WebSocket client already connected to Moonraker.
        mrr: Request builder used to construct subscribe/query/database
            requests.
    """

    def __init__(self, client: WebSocketClient, mrr: MoonrakerRequests) -> None:
        """Initialize the tracker against an already-constructed client.

        Args:
            client: WebSocket client connected (or connecting) to Moonraker.
            mrr: Moonraker request builder.
        """
        self.client = client
        self.mrr = mrr
        self._homed_axes: frozenset[str] = frozenset()
        self._print_state: str = "standby"
        self._print_state_callbacks: list[Callable[[str], None]] = []

    def start(self) -> None:
        """Subscribe to ``toolhead`` and ``print_stats`` status updates.

        Must be called after the underlying WebSocket connection is
        established.
        """
        self.client.register_handler("notify_status_update", self._on_status_update)
        request = self.mrr.request_sub_to_objs(["toolhead", "print_stats"])
        response = self.client.send_jsonrpc(request)
        result = _as_dict(response.get("result"))
        status = _as_dict(result.get("status"))
        self._apply_status(status)

    def is_homed(self) -> bool:
        """Check whether Klipper currently reports x/y/z all homed.

        Returns:
            True if ``REQUIRED_HOMED_AXES`` is a subset of the live
            ``homed_axes`` reported by Klipper's ``toolhead`` object.
        """
        return self._homed_axes >= REQUIRED_HOMED_AXES

    @property
    def print_state(self) -> str:
        """Return the last known Klipper ``print_stats.state`` value."""
        return self._print_state

    def on_print_state_change(self, callback: Callable[[str], None]) -> None:
        """Register a callback invoked whenever ``print_stats.state`` changes.

        Args:
            callback: Called with the new state string. Invoked from the
                WebSocket client's background thread, not the caller's event
                loop — callers that need to touch asyncio state must
                marshal back via ``asyncio.run_coroutine_threadsafe``.
        """
        self._print_state_callbacks.append(callback)

    def _on_status_update(self, params: Any) -> None:  # noqa: ANN401
        """Handle a ``notify_status_update`` push from Moonraker.

        Args:
            params: Notification params, typically ``[status_dict,
                eventtime]``.
        """
        if not params:
            return
        candidate = cast("list[Any]", params)[0] if isinstance(params, list) else params
        status = _as_dict(candidate)
        if status:
            self._apply_status(status)

    def _apply_status(self, status: dict[str, Any]) -> None:
        """Update cached state from a Moonraker status dict.

        Args:
            status: Mapping of object name to its updated fields, as
                returned by both ``printer.objects.subscribe``'s initial
                response and subsequent ``notify_status_update`` pushes.
        """
        toolhead = _as_dict(status.get("toolhead"))
        homed_axes = toolhead.get("homed_axes")
        if isinstance(homed_axes, str):
            self._homed_axes = frozenset(homed_axes)
        elif isinstance(homed_axes, list):
            self._homed_axes = frozenset(
                str(axis) for axis in cast("list[Any]", homed_axes)
            )

        print_stats = _as_dict(status.get("print_stats"))
        new_state = print_stats.get("state")
        if isinstance(new_state, str) and new_state != self._print_state:
            self._print_state = new_state
            for callback in self._print_state_callbacks:
                callback(new_state)

    # ==================== Tip/liquid persistence ====================

    def load_tip_liquid_state(self) -> dict[str, Any]:
        """Read persisted tip/liquid state from Moonraker's database.

        Returns:
            Mapping of the keys that had a stored value (``tip_state``,
            ``has_liquid``, ``current_liquid``) to their stored value.
            Keys with no prior stored value (e.g. first run) are omitted.
        """
        result: dict[str, Any] = {}
        for key in (DB_KEY_TIP_STATE, DB_KEY_HAS_LIQUID, DB_KEY_CURRENT_LIQUID):
            try:
                response = self.client.send_jsonrpc(
                    self.mrr.server_database_get_item(DB_NAMESPACE, key)
                )
                result[key] = response["result"]["value"]
            except Exception:
                logger.info("No persisted value for '%s' (first run?)", key)
        return result

    def save_tip_liquid_state(
        self,
        tip_state: str,
        has_liquid: bool,
        current_liquid: str | None,
    ) -> None:
        """Persist tip/liquid state to Moonraker's database.

        Args:
            tip_state: ``TipState`` value (as a string) to store.
            has_liquid: Whether liquid is currently in the tip.
            current_liquid: Name of the currently active liquid profile, or
                None.
        """
        for key, value in (
            (DB_KEY_TIP_STATE, tip_state),
            (DB_KEY_HAS_LIQUID, has_liquid),
            (DB_KEY_CURRENT_LIQUID, current_liquid),
        ):
            self.client.send_jsonrpc(
                self.mrr.server_database_post_item(DB_NAMESPACE, key, value)
            )
