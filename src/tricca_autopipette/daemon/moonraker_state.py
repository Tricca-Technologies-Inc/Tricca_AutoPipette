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
from dataclasses import dataclass
from typing import Any, cast

from tricca_autopipette.moonraker.moonraker_requests import MoonrakerRequests
from tricca_autopipette.moonraker.websocket_client import WebSocketClient, as_dict

logger = logging.getLogger(__name__)

#: server.database namespace used to persist tip/liquid state.
DB_NAMESPACE = "tricca_autopipette"

#: Single key tip/liquid state is stored under, as one combined dict --
#: one DB round trip instead of one per field (matching DB_KEY_TIP_PRESENCE's
#: shape below). The three field names inside that dict.
DB_KEY_TIP_LIQUID_STATE = "tip_liquid_state"
DB_KEY_TIP_STATE = "tip_state"
DB_KEY_HAS_LIQUID = "has_liquid"
DB_KEY_CURRENT_LIQUID = "current_liquid"

#: Per-tipbox consumed-position maps, keyed by location name. Klipper has no
#: notion of which tip positions are empty, so like the tip/liquid keys above
#: this is a durability layer rather than live-hardware truth.
DB_KEY_TIP_PRESENCE = "tip_presence"

#: Axes that must all be reported homed by Klipper for the interlock to pass.
REQUIRED_HOMED_AXES = frozenset({"x", "y", "z"})

#: Klipper objects that describe the plate and plunger axes (umbrella plan
#: §6.3, Tricca_Autopipette_Configs CFG-1). Klipper owns these values; tapd
#: only reads them.
PLATE_CFG_OBJECT = "gcode_macro _PLATE_CFG"
PIPETTE_CFG_OBJECT = "gcode_macro _PIPETTE_CFG"
PIPETTE_STEPPER_SECTION = "manual_stepper pipette_stepper"

#: Live objects behind plate/plunger homed state and plate positions (issue
#: #140). Klipper's own homed test is the macro flag AND the stepper still
#: enabled (``plate-macros.cfg``); a flag can outlive a motors-off that didn't
#: go through ``M84``. Objects Klipper doesn't have are simply never reported.
PLATE_STATE_OBJECT = "gcode_macro _PLATE_STATE"
PIPETTE_STATE_OBJECT = "gcode_macro _PIPETTE_STATE"
STEPPER_ENABLE_OBJECT = "stepper_enable"
GCODE_MOVE_OBJECT = "gcode_move"
SUBSCRIBED_OBJECTS: dict[str, list[str] | None] = {
    "toolhead": None,
    "print_stats": None,
    PLATE_STATE_OBJECT: None,
    PIPETTE_STATE_OBJECT: None,
    STEPPER_ENABLE_OBJECT: None,
    GCODE_MOVE_OBJECT: ["position", "axis_map"],
}


@dataclass(frozen=True)
class PlateAxis:
    """One plate drawer, as Klipper configures it.

    Attributes:
        name: Plate name (``plate1``...), the ``_PLATE_CFG.axes`` key.
        letter: G-code axis letter bound to it.
        position_min: ``[manual_stepper <name>]`` lower travel limit (mm).
        position_max: Upper travel limit (mm).
        safe_stops: Positions (mm) at which the tip may descend
            (``_PLATE_CFG.safe_stops``); empty means never tip-safe.
    """

    name: str
    letter: str
    position_min: float | None
    position_max: float | None
    safe_stops: tuple[float, ...]


@dataclass(frozen=True)
class PipetteAxis:
    """The plunger's G-code axis, as Klipper configures it.

    Attributes:
        letter: G-code axis letter (``_PIPETTE_CFG.axis``).
        stage: Config stage (``_PIPETTE_CFG.stage``), 1 or 2.
        position_min: ``[manual_stepper pipette_stepper]`` lower soft limit,
            or None (stage 1 has no limits).
        position_max: Upper soft limit, or None.
    """

    letter: str
    stage: int
    position_min: float | None
    position_max: float | None


@dataclass(frozen=True)
class AxisConfig:
    """Read-only description of Klipper's plate and plunger axes.

    The default instance is the "not configured" state of a machine whose
    Klipper config predates the axis expansion: no plates, no P axis.

    Attributes:
        plates: Every plate in ``_PLATE_CFG.axes`` order.
        z_safe: Highest raw Z (closest to 0) at which the tip clears every
            plate; the tip is safe when raw Z <= z_safe. None if absent.
        park_tol: Tolerance (mm) for "at a tip-safe position", or None.
        pipette: The P axis, or None if ``_PIPETTE_CFG`` is absent.
    """

    plates: tuple[PlateAxis, ...] = ()
    z_safe: float | None = None
    park_tol: float | None = None
    pipette: PipetteAxis | None = None


def _optional_float(value: Any) -> float | None:  # ruff:ignore[any-type]
    return None if value is None else float(value)


def parse_axis_config(status: dict[str, Any]) -> AxisConfig:
    """Build an `AxisConfig` from a ``printer.objects.query`` status dict.

    Args:
        status: Mapping of Klipper object name to its fields. Objects Klipper
            doesn't have are simply absent, which yields "not configured" for
            that half (plates or P).

    Returns:
        The parsed description.

    Example:
        >>> parse_axis_config({})
        AxisConfig(plates=(), z_safe=None, park_tol=None, pipette=None)
    """
    settings = as_dict(as_dict(status.get("configfile")).get("settings"))

    def limits(section: str) -> tuple[float | None, float | None]:
        stepper = as_dict(settings.get(section))
        return (
            _optional_float(stepper.get("position_min")),
            _optional_float(stepper.get("position_max")),
        )

    plate_cfg = as_dict(status.get(PLATE_CFG_OBJECT))
    safe_stops = as_dict(plate_cfg.get("safe_stops"))
    plates = tuple(
        PlateAxis(
            str(name),
            str(letter),
            *limits(f"manual_stepper {name}"),
            tuple(float(p) for p in cast("list[Any]", safe_stops.get(name) or [])),
        )
        for name, letter in as_dict(plate_cfg.get("axes")).items()
    )

    pipette_cfg = as_dict(status.get(PIPETTE_CFG_OBJECT))
    pipette = (
        PipetteAxis(
            str(pipette_cfg["axis"]),
            int(pipette_cfg.get("stage", 1)),
            *limits(PIPETTE_STEPPER_SECTION),
        )
        if "axis" in pipette_cfg
        else None
    )

    return AxisConfig(
        plates=plates,
        z_safe=_optional_float(plate_cfg.get("z_safe")),
        park_tol=_optional_float(plate_cfg.get("park_tol")),
        pipette=pipette,
    )


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
        self._axis_config: AxisConfig | None = None
        #: Last-known fields of the extra-axis objects, merged push by push
        #: (Moonraker only sends fields that changed).
        self._live: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        """Subscribe to gantry, job and plate/plunger state updates.

        Also watches ``notify_klippy_ready`` so :attr:`axis_config` is re-read
        after a Klipper restart. Must be called after the underlying
        WebSocket connection is established.
        """
        self.client.register_handler("notify_status_update", self._on_status_update)
        self.client.register_handler("notify_klippy_ready", self._on_klippy_ready)
        self._axis_config = None
        # Not `request_sub_to_objs`: its allow-list drops `gcode_macro <name>`.
        request = self.mrr.gen_request(
            "printer.objects.subscribe", {"objects": SUBSCRIBED_OBJECTS}
        )
        response = self.client.send_jsonrpc(request)
        result = as_dict(response.get("result"))
        status = as_dict(result.get("status"))
        self._apply_status(status)

    def is_homed(self) -> bool:
        """Check whether Klipper currently reports x/y/z all homed.

        Returns:
            True if ``REQUIRED_HOMED_AXES`` is a subset of the live
            ``homed_axes`` reported by Klipper's ``toolhead`` object.
        """
        return self._homed_axes >= REQUIRED_HOMED_AXES

    @property
    def homed_axes(self) -> frozenset[str]:
        """Gantry axes Klipper's ``toolhead`` currently reports homed."""
        return self._homed_axes

    def _stepper_enabled(self, stepper: str) -> bool:
        steppers = as_dict(self._live.get(STEPPER_ENABLE_OBJECT, {}).get("steppers"))
        return bool(steppers.get(stepper))

    def is_plate_homed(self, plate: str) -> bool:
        """Check Klipper's live homed state for one plate (issue #140).

        Args:
            plate: Plate name (``plate1``...).

        Returns:
            True only if ``_PLATE_STATE`` flags it homed and its stepper is
            still enabled. False for a plate Klipper doesn't know.
        """
        flag = self._live.get(PLATE_STATE_OBJECT, {}).get(plate)
        return bool(flag) and self._stepper_enabled(f"manual_stepper {plate}")

    def is_plunger_homed(self) -> bool:
        """Check Klipper's live homed state for the plunger (issue #140).

        Returns:
            True only if ``_PIPETTE_STATE.homed`` is set and
            ``pipette_stepper`` is still enabled.
        """
        flag = self._live.get(PIPETTE_STATE_OBJECT, {}).get("homed")
        return bool(flag) and self._stepper_enabled(PIPETTE_STEPPER_SECTION)

    def axis_position(self, letter: str) -> float | None:
        """Live raw position of a G-code axis, e.g. a plate's (issue #140).

        Args:
            letter: G-code axis letter (``V``, ``P``...).

        Returns:
            ``gcode_move.position`` at the letter's ``axis_map`` index, or
            None while the letter isn't bound (or nothing was reported yet).
        """
        move = self._live.get(GCODE_MOVE_OBJECT, {})
        index = as_dict(move.get("axis_map")).get(letter)
        position = move.get("position")
        if not isinstance(index, int) or not isinstance(position, list):
            return None
        values = cast("list[Any]", position)
        return float(values[index]) if index < len(values) else None

    @property
    def axis_config(self) -> AxisConfig:
        """Klipper's plate and plunger axis configuration (issue #138).

        Queried from Moonraker on first read after :meth:`start` or a Klipper
        restart, then cached: it only changes when Klipper reloads its config.
        A failed query isn't cached and reads as "not configured".
        """
        if self._axis_config is None:
            request = self.mrr.printer_objects_query({
                PLATE_CFG_OBJECT: None,
                PIPETTE_CFG_OBJECT: None,
                "configfile": ["settings"],
            })
            try:
                status = self.client.send_jsonrpc(request)["result"]["status"]
                self._axis_config = parse_axis_config(as_dict(status))
            except Exception:
                logger.warning(
                    "Could not read plate/plunger axis config from Klipper",
                    exc_info=True,
                )
                return AxisConfig()
        return self._axis_config

    def _on_klippy_ready(self, params: Any) -> None:  # ruff:ignore[any-type]
        """Drop the cached axis config; Klipper may have a new config file.

        Args:
            params: Notification params (unused).
        """
        del params
        self._axis_config = None

    @property
    def print_state(self) -> str:
        """The last known Klipper ``print_stats.state`` value."""
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

    def _on_status_update(self, params: Any) -> None:  # ruff:ignore[any-type]
        """Handle a ``notify_status_update`` push from Moonraker.

        Args:
            params: Notification params, typically ``[status_dict,
                eventtime]``.
        """
        if not params:
            return
        candidate = cast("list[Any]", params)[0] if isinstance(params, list) else params
        status = as_dict(candidate)
        if status:
            self._apply_status(status)

    def _apply_status(self, status: dict[str, Any]) -> None:
        """Update cached state from a Moonraker status dict.

        Args:
            status: Mapping of object name to its updated fields, as
                returned by both ``printer.objects.subscribe``'s initial
                response and subsequent ``notify_status_update`` pushes.
        """
        toolhead = as_dict(status.get("toolhead"))
        homed_axes = toolhead.get("homed_axes")
        if isinstance(homed_axes, str):
            self._homed_axes = frozenset(homed_axes)
        elif isinstance(homed_axes, list):
            self._homed_axes = frozenset(
                str(axis) for axis in cast("list[Any]", homed_axes)
            )

        for name in (
            PLATE_STATE_OBJECT,
            PIPETTE_STATE_OBJECT,
            STEPPER_ENABLE_OBJECT,
            GCODE_MOVE_OBJECT,
        ):
            if name in status:
                self._live.setdefault(name, {}).update(as_dict(status[name]))

        print_stats = as_dict(status.get("print_stats"))
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
            Keys with no prior stored value (e.g. first run, or a value
            persisted before this combined-key format) are omitted.
        """
        try:
            response = self.client.send_jsonrpc(
                self.mrr.server_database_get_item(DB_NAMESPACE, DB_KEY_TIP_LIQUID_STATE)
            )
            value = response["result"]["value"]
        except Exception:
            logger.info("No persisted tip/liquid state (first run?)")
            return {}

        if not isinstance(value, dict):
            logger.warning("Persisted tip/liquid state is not a mapping; ignoring")
            return {}
        return cast("dict[str, Any]", value)

    def save_tip_liquid_state(
        self,
        tip_state: str,
        has_liquid: bool,
        current_liquid: str | None,
    ) -> None:
        """Persist tip/liquid state to Moonraker's database.

        One combined write rather than one per field -- matching
        ``save_tip_presence``'s shape below.

        Args:
            tip_state: ``TipState`` value (as a string) to store.
            has_liquid: Whether liquid is currently in the tip.
            current_liquid: Name of the currently active liquid profile, or
                None.
        """
        self.client.send_jsonrpc(
            self.mrr.server_database_post_item(
                DB_NAMESPACE,
                DB_KEY_TIP_LIQUID_STATE,
                {
                    DB_KEY_TIP_STATE: tip_state,
                    DB_KEY_HAS_LIQUID: has_liquid,
                    DB_KEY_CURRENT_LIQUID: current_liquid,
                },
            )
        )

    def load_tip_presence(self) -> dict[str, Any]:
        """Read persisted per-tipbox consumed-position maps.

        Returns:
            Mapping of tipbox location name to its stored record, as produced
            by ``TipBoxManager.snapshot``. Empty on the first run, or if the
            stored value is not a mapping.

        Note:
            Never raises. A tipbox with no stored state is simply treated as
            full, which is the safe direction -- the operator is told a box is
            fuller than it is, not emptier.
        """
        try:
            response = self.client.send_jsonrpc(
                self.mrr.server_database_get_item(DB_NAMESPACE, DB_KEY_TIP_PRESENCE)
            )
            value = response["result"]["value"]
        except Exception:
            logger.info("No persisted tip presence (first run?)")
            return {}

        if not isinstance(value, dict):
            logger.warning("Persisted tip presence is not a mapping; ignoring")
            return {}

        return cast("dict[str, Any]", value)

    def save_tip_presence(self, snapshot: dict[str, Any]) -> None:
        """Persist per-tipbox consumed-position maps.

        Args:
            snapshot: Mapping of tipbox location name to its record, as
                produced by ``TipBoxManager.snapshot``. Each record carries the
                plate dimensions alongside the presence map so a reshaped box
                can be detected on restore rather than silently misapplied.
        """
        self.client.send_jsonrpc(
            self.mrr.server_database_post_item(
                DB_NAMESPACE, DB_KEY_TIP_PRESENCE, snapshot
            )
        )
