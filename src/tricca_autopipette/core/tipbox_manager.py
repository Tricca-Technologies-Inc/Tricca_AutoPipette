#!/usr/bin/env python3
"""Ordered management of multiple independent tipboxes.

A run usually needs more tips than one box holds, so several boxes sit on the
deck at once. This module owns the question of *which box supplies the next
tip*, keeping each box a separate object with its own consumption state.

That separation is the point. An earlier design merged extra boxes into the
first by splicing their well lists together (``TipBox.append_box``), which made
three things impossible: unloading a single box, reporting per-box tip counts,
and persisting consumption in a way that survives a deck rearrangement. Boxes
here are never merged -- `TipBoxManager` simply draws from them in order.

Draw order is the order boxes were registered, which `LocationManager` derives
from the order they appear in the locations config. So a box mentioned earlier
in the file is consumed earlier, and reordering the file reorders the draw.

Within a box, the order is the box's own `TraversalOrder`, so different boxes
may be consumed in different patterns.

Persistence:
    `snapshot` and `restore` move the whole manager's state through
    ``daemon/moonraker_state.py``'s Moonraker-database layer. `restore`
    deliberately refuses to apply a map whose plate dimensions differ from the
    live box, since silently reindexing consumed positions onto different
    physical wells would send the pipette to a position it believes is empty.

Typical usage:
    >>> from tricca_autopipette.core.plates import PlateParams, TipBox
    >>> from tricca_autopipette.core.well import Well
    >>> template = Well(coor=Coordinate(x=100, y=0, z=0), dip_top=10.0)
    >>> params = PlateParams(
    ...     plate_type="tipbox",
    ...     well_template=template,
    ...     num_row=8,
    ...     num_col=12,
    ...     spacing_row=9.0,
    ...     spacing_col=9.0,
    ... )
    >>> box_a = TipBox(params)
    >>> box_b = TipBox(params)
    >>> manager = TipBoxManager()
    >>> manager.register("tipbox_a", box_a)
    >>> manager.register("tipbox_b", box_b)
    >>> name, box, coor = manager.next_tip()
    >>> manager.remaining
    191
"""

from __future__ import annotations

import logging
from typing import Any, cast

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.pipette_exceptions import (
    NotALocationError,
    NoTipboxError,
    OutOfTipsError,
)
from tricca_autopipette.core.plates import PlateExhaustedError, TipBox
from tricca_autopipette.core.traversal import (
    TraversalRegistry,
    compress_to_ranges,
    rc_to_well_id,
)

logger = logging.getLogger(__name__)

#: Snapshot keys, also the shape stored in Moonraker's database.
KEY_NUM_ROW = "num_row"
KEY_NUM_COL = "num_col"
KEY_PRESENT = "present"


class TipBoxManager:
    """Draws tips from an ordered collection of independent tipboxes.

    Attributes:
        boxes: Registered tipboxes keyed by location name, in draw order.

    Example:
        >>> from tricca_autopipette.core.plates import PlateParams, TipBox
        >>> from tricca_autopipette.core.well import Well
        >>> template = Well(coor=Coordinate(x=100, y=0, z=0), dip_top=10.0)
        >>> params = PlateParams(
        ...     plate_type="tipbox",
        ...     well_template=template,
        ...     num_row=8,
        ...     num_col=12,
        ...     spacing_row=9.0,
        ...     spacing_col=9.0,
        ... )
        >>> box = TipBox(params)
        >>> manager = TipBoxManager()
        >>> manager.register("tipbox_a", box)
        >>> manager.next_tip()[0]
        'tipbox_a'
    """

    def __init__(self) -> None:
        """Initialize an empty manager with no tipboxes registered."""
        self.boxes: dict[str, TipBox] = {}

    # ==================== Registration ====================

    def register(self, name: str, box: TipBox) -> None:
        """Add a tipbox, or replace one already registered under this name.

        Args:
            name: Location name identifying the box. Names are unique, so
                registering an existing name replaces that box -- and with it
                its consumption state, since a re-registered box is a
                physically different one.
            box: The tipbox to draw from.

        Note:
            Registration order is draw order. Replacing a box keeps its
            original position in that order rather than moving it to the end,
            so editing a box's coordinates in a config file does not silently
            change which box is drained first.

        Example:
            Registers a freshly loaded box under the name it will be drawn
            from, e.g. ``manager.register("tipbox_a", box)``.
        """
        if name in self.boxes:
            logger.info("Replacing tipbox %r; its consumed-tip state is reset", name)
        self.boxes[name] = box

    def unregister(self, name: str) -> bool:
        """Remove a tipbox from the pool.

        Args:
            name: Location name of the box to remove.

        Returns:
            True if a box was removed, False if no box had that name.

        Note:
            The remaining boxes keep their own consumption state untouched --
            the reason boxes are never merged.

        Example:
            ``manager.unregister("tipbox_a")`` returns ``True`` when a box
            named ``"tipbox_a"`` was registered and is now removed.
        """
        return self.boxes.pop(name, None) is not None

    def clear(self) -> None:
        """Remove every registered tipbox."""
        self.boxes.clear()

    def has_boxes(self) -> bool:
        """Report whether any tipbox is registered.

        Returns:
            True if at least one box is registered.
        """
        return bool(self.boxes)

    def names(self) -> list[str]:
        """Return registered box names in draw order.

        Returns:
            List of location names, earliest-drawn first.
        """
        return list(self.boxes)

    # ==================== Drawing ====================

    @property
    def remaining(self) -> int:
        """Total tips available across all boxes.

        Returns:
            Sum of every registered box's remaining tip count.
        """
        return sum(box.remaining for box in self.boxes.values())

    @property
    def capacity(self) -> int:
        """Total tip positions across all boxes.

        Returns:
            Sum of every registered box's eligible position count.
        """
        return sum(box.capacity for box in self.boxes.values())

    def next_tip(self, name: str | None = None) -> tuple[str, TipBox, Coordinate]:
        """Consume the next tip from the first box that still has one.

        Boxes are tried in registration order, so a box is fully drained before
        the next is touched -- unless a specific box is requested by name, in
        which case only that box is drawn from.

        Args:
            name: If given, draw only from this box instead of trying every
                registered box in order.

        Returns:
            Tuple of the supplying box's name, the box itself, and the
            coordinate of the tip. The box is returned because the caller needs
            *that* box's dip distance -- boxes may sit at different heights.

        Raises:
            NoTipboxError: If no tipbox is registered at all.
            NotALocationError: If `name` is given but no box is registered
                under that name.
            OutOfTipsError: If every tried box is exhausted.

        Example:
            ``name, box, coor = manager.next_tip()`` returns the supplying
            box's name, the box itself (for its dip distance), and the
            tip's coordinate.
        """
        if not self.boxes:
            raise NoTipboxError()

        if name is not None:
            box = self.boxes.get(name)
            if box is None:
                raise NotALocationError(name)
            try:
                _index, coor = box.take_tip()
            except PlateExhaustedError:
                raise OutOfTipsError([name]) from None
            return name, box, coor

        for box_name, box in self.boxes.items():
            try:
                _index, coor = box.take_tip()
            except PlateExhaustedError:
                continue
            return box_name, box, coor

        raise OutOfTipsError(list(self.boxes))

    def peek_tip(self) -> tuple[str, int] | None:
        """Report which box and position would supply the next tip.

        Returns:
            Tuple of box name and flat well index, or None if no tips remain.
            Used by the ``tips`` report rather than by pipetting.
        """
        for name, box in self.boxes.items():
            index = box.peek_tip()
            if index is not None:
                return name, index
        return None

    # ==================== Resetting ====================

    def reset_tips(self, name: str) -> None:
        """Mark one box as full again.

        The explicit "a fresh box was loaded" signal, needed because
        consumption is persisted across daemon restarts.

        Args:
            name: Location name of the box to reset.

        Raises:
            NotALocationError: If no tipbox is registered under that name.

        Example:
            ``manager.reset_tips("tipbox_a")`` marks that one box full
            again after it was physically reloaded.
        """  # ruff: ignore[docstring-extraneous-exception]
        self._require(name).reset_tips()
        logger.info("Reset tipbox %r to full", name)

    def reset_all(self) -> None:
        """Mark every registered box as full again.

        Example:
            ``manager.reset_all()`` marks every registered box full again.
        """
        for box in self.boxes.values():
            box.reset_tips()
        logger.info("Reset %d tipbox(es) to full", len(self.boxes))

    def set_consumed(self, name: str, indices: set[int]) -> None:
        """Declare exactly which positions of a box have been used.

        Used both by the ``set_tips`` command and when a locations config
        declares a partially-used box.

        Args:
            name: Location name of the box.
            indices: Flat well indices that no longer hold a tip. Any position
                not listed is treated as holding a tip.

        Raises:
            NotALocationError: If no tipbox is registered under that name.
            ValueError: If an index falls outside the box.

        Example:
            ``manager.set_consumed("tipbox_a", {0, 1, 2})`` declares that
            positions 0, 1, and 2 of that box no longer hold a tip.
        """  # ruff: ignore[docstring-extraneous-exception]
        box = self._require(name)
        total = len(box.wells)

        out_of_range = {index for index in indices if not 0 <= index < total}
        if out_of_range:
            raise ValueError(
                f"Tip positions {sorted(out_of_range)} are outside tipbox "
                f"{name!r} ({total} wells)"
            )

        box.set_presence([index not in indices for index in range(total)])

    # ==================== Persistence ====================

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Capture every box's consumption state for persistence.

        Returns:
            Mapping of box name to a record carrying the plate dimensions
            alongside the presence map. The dimensions are what let `restore`
            detect that a box has been reconfigured.

        Example:
            ``manager.snapshot()["tipbox_a"]["num_row"]`` gives that box's
            row count, e.g. ``8`` for an 8x12 plate.
        """
        return {
            name: {
                KEY_NUM_ROW: box.num_row,
                KEY_NUM_COL: box.num_col,
                KEY_PRESENT: list(box.present),
            }
            for name, box in self.boxes.items()
        }

    def restore(self, data: dict[str, Any]) -> list[str]:
        """Reapply persisted consumption state to the registered boxes.

        A box whose stored dimensions differ from its live ones is left full
        and reported rather than restored: reindexing a presence map onto a
        differently-shaped plate would mark the wrong physical positions empty,
        sending the pipette to fetch a tip that is not there.

        Args:
            data: A mapping previously produced by `snapshot`. Entries naming
                boxes that are not registered are ignored, so a stale database
                entry for a removed box is harmless.

        Returns:
            Names of registered boxes whose stored state was rejected or
            malformed and which therefore remain full. Callers should surface
            this -- it means the operator's tip state was not what they expect.

        Example:
            ``manager.restore(saved)`` reapplies a mapping previously
            produced by `snapshot`, returning ``[]`` when every box's
            stored dimensions still match the live ones.
        """
        skipped: list[str] = []

        for name, box in self.boxes.items():
            record = data.get(name)
            if record is None:
                continue

            present = self._validate_record(name, box, record)
            if present is None:
                skipped.append(name)
                continue

            box.set_presence(present)

        return skipped

    def _validate_record(
        self, name: str, box: TipBox, record: object
    ) -> list[bool] | None:
        """Check one persisted record against the live box.

        Args:
            name: Box name, for logging.
            box: The live tipbox the record would be applied to.
            record: The stored record, of unverified shape -- it comes back
                from an external database and may predate a config change.

        Returns:
            The presence map to apply, or None if the record is unusable.
        """
        if not isinstance(record, dict):
            logger.warning("Persisted tip state for %r is malformed; ignoring", name)
            return None

        typed = cast("dict[str, Any]", record)
        stored_rows = typed.get(KEY_NUM_ROW)
        stored_cols = typed.get(KEY_NUM_COL)
        if (stored_rows, stored_cols) != (box.num_row, box.num_col):
            logger.warning(
                "Tipbox %r is now %dx%d but persisted state was %sx%s; "
                "treating the box as full",
                name,
                box.num_row,
                box.num_col,
                stored_rows,
                stored_cols,
            )
            return None

        present: object = typed.get(KEY_PRESENT)
        if not isinstance(present, list):
            logger.warning(
                "Persisted tip map for %r is not a list; treating the box as full",
                name,
            )
            return None

        flags = cast("list[Any]", present)
        if len(flags) != len(box.wells):
            logger.warning(
                "Persisted tip map for %r has %d entries but the box has %d "
                "wells; treating the box as full",
                name,
                len(flags),
                len(box.wells),
            )
            return None

        return [bool(flag) for flag in flags]

    # ==================== Reporting ====================

    def describe(self, name: str) -> dict[str, Any]:
        """Summarize one box for the ``tips`` report.

        Args:
            name: Location name of the box.

        Returns:
            Data-only description: dimensions, counts, traversal order, the
            eligible/consumed position sets, and the next position to be drawn.
            Rendering lives in ``cli/report_tables.py``.

        Raises:
            NotALocationError: If no tipbox is registered under that name.

        Example:
            ``manager.describe("tipbox_a")["remaining"]`` gives that box's
            remaining tip count, e.g. ``84`` for a 96-tip box with 12
            positions already drawn.
        """  # ruff: ignore[docstring-extraneous-exception]
        box = self._require(name)
        next_index = box.peek_tip()

        return {
            "name": name,
            "num_row": box.num_row,
            "num_col": box.num_col,
            "capacity": box.capacity,
            "remaining": box.remaining,
            "order": TraversalRegistry.name_for(box.order)
            or box.order.model_dump(mode="json"),
            "present": list(box.present),
            "eligible": sorted(box.sequence),
            "consumed_ranges": compress_to_ranges(box.consumed_indices(), box.num_col),
            "next_index": next_index,
            "next_well": (
                rc_to_well_id(*divmod(next_index, box.num_col))
                if next_index is not None
                else None
            ),
        }

    def describe_all(self) -> list[dict[str, Any]]:
        """Summarize every registered box, in draw order.

        Returns:
            List of `describe` records.
        """
        return [self.describe(name) for name in self.boxes]

    def _require(self, name: str) -> TipBox:
        """Look up a registered box or raise.

        Args:
            name: Location name of the box.

        Returns:
            The registered tipbox.

        Raises:
            NotALocationError: If no tipbox is registered under that name.
        """
        try:
            return self.boxes[name]
        except KeyError:
            raise NotALocationError(name) from None

    def __repr__(self) -> str:
        """Return string representation of the manager.

        Returns:
            String showing box count and total tips remaining.

        Example:
            ``repr(manager)`` gives e.g.
            ``'TipBoxManager(boxes=2, remaining=191/192)'`` for two
            registered 96-tip boxes with one tip already drawn.
        """
        return (
            f"TipBoxManager(boxes={len(self.boxes)}, "
            f"remaining={self.remaining}/{self.capacity})"
        )
