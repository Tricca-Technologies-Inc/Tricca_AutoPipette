#!/usr/bin/env python3
"""Well addressing, traversal ordering, and well masks for plates.

This module answers one question for any rectangular plate: *in what order
should its wells be visited, and which wells are eligible at all?*

It bundles three independent pieces:

- **Addressing** -- conversion between lab-native well IDs (``"A1"``, ``"H12"``)
  and flat row-major indices into a plate's ``wells`` list, plus parsing of
  rectangular ranges (``"A1:D6"``).
- **Ordering** -- `TraversalOrder`, an orthogonal descriptor whose four fields
  combine to express any raster or serpentine walk of a grid, and
  `TraversalRegistry`, which maps readable preset names onto descriptors so
  configuration files can say ``"column_from_bottom_right"`` instead of
  spelling out the axes.
- **Masking** -- `WellMask`, an include/exclude pair over well ranges, for
  restricting a plate to a sub-region (e.g. only columns 1-6).

Ordering and masking are deliberately separate concerns: the order decides the
*sequence*, the mask decides *membership*. `TraversalOrder.indices` produces the
full sequence and callers filter it through `WellMask.allowed`, which keeps a
masked plate's relative visiting order identical to an unmasked one.

Coordinate conventions:
    - Rows are the first axis, labelled ``A``-``Z`` (row 0 is ``A``).
    - Columns are the second axis, labelled ``1``-``N`` (col 0 is ``1``).
    - A flat index is always row-major: ``index = row * num_col + col``. This
      matches the well ordering produced by `plates.PlateArray._gen_wells`, so
      an index from this module indexes directly into ``Plate.wells``.

Note:
    Row labels are single letters, capping plates at 26 rows. A 384-well plate
    has 16 rows, so this is ample; extending to ``AA``-style labels would only
    require changing `rc_to_well_id` and `well_id_to_rc`.

Typical usage:
    >>> order = TraversalRegistry.resolve("column_from_bottom_right")
    >>> seq = order.indices(num_row=8, num_col=12)
    >>> rc_to_well_id(*divmod(seq[0], 12))
    'H12'
    >>> mask = WellMask(include=["A1:D12"])
    >>> eligible = mask.allowed(8, 12)
    >>> [i for i in seq if i in eligible][0]
    47
"""

from __future__ import annotations

import re
import string
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Maximum number of rows addressable with single-letter row labels.
MAX_ADDRESSABLE_ROWS = len(string.ascii_uppercase)

#: A single well ID, e.g. ``"A1"`` or ``"h12"``.
_WELL_ID_RE = re.compile(r"^\s*([A-Za-z])\s*(\d+)\s*$")

#: Separator between the two corners of a rectangular well range.
_RANGE_SEP = ":"


def rc_to_well_id(row: int, col: int) -> str:
    """Convert a zero-based row/column pair to a well ID.

    Args:
        row: Zero-based row index (0 -> ``A``).
        col: Zero-based column index (0 -> ``1``).

    Returns:
        The well ID, e.g. ``"A1"`` for ``(0, 0)`` or ``"H12"`` for ``(7, 11)``.

    Raises:
        ValueError: If `row` or `col` is negative, or `row` exceeds the
            single-letter label range.

    Example:
        >>> rc_to_well_id(0, 0)
        'A1'
        >>> rc_to_well_id(7, 11)
        'H12'
    """
    if row < 0 or col < 0:
        raise ValueError(f"Row and column must be non-negative, got ({row}, {col})")
    if row >= MAX_ADDRESSABLE_ROWS:
        raise ValueError(
            f"Row {row} exceeds the single-letter label range "
            f"(max {MAX_ADDRESSABLE_ROWS - 1})"
        )
    return f"{string.ascii_uppercase[row]}{col + 1}"


def well_id_to_rc(well_id: str, num_row: int, num_col: int) -> tuple[int, int]:
    """Convert a well ID to a zero-based row/column pair.

    Args:
        well_id: Well ID such as ``"A1"`` or ``"h12"``. Case-insensitive, and
            surrounding whitespace is ignored.
        num_row: Number of rows in the plate, used for bounds checking.
        num_col: Number of columns in the plate, used for bounds checking.

    Returns:
        Tuple of ``(row, col)``, both zero-based.

    Raises:
        ValueError: If `well_id` is not a letter followed by a positive
            integer, or if it addresses a cell outside the plate.

    Example:
        >>> well_id_to_rc("A1", 8, 12)
        (0, 0)
        >>> well_id_to_rc("h12", 8, 12)
        (7, 11)
    """
    match = _WELL_ID_RE.match(well_id)
    if match is None:
        raise ValueError(
            f"Invalid well ID {well_id!r}: expected a letter followed by a "
            f"number, e.g. 'A1' or 'H12'"
        )

    row = string.ascii_uppercase.index(match.group(1).upper())
    col = int(match.group(2)) - 1

    if col < 0:
        raise ValueError(f"Invalid well ID {well_id!r}: columns are 1-based")
    if row >= num_row or col >= num_col:
        raise ValueError(
            f"Well {well_id!r} is outside a {num_row}x{num_col} plate "
            f"(max {rc_to_well_id(num_row - 1, num_col - 1)})"
        )
    return row, col


def parse_well_ranges(ranges: list[str], num_row: int, num_col: int) -> set[int]:
    """Expand well IDs and rectangular ranges into a set of flat indices.

    Each entry is either a single well (``"F3"``) or a rectangular block
    delimited by two corner wells (``"A1:D6"``). The two corners may be given in
    either order -- ``"D6:A1"`` selects the same block as ``"A1:D6"``.

    Args:
        ranges: Well IDs and/or ``start:end`` range strings.
        num_row: Number of rows in the plate.
        num_col: Number of columns in the plate.

    Returns:
        Set of flat row-major indices covered by the ranges. An empty input
        yields an empty set.

    Raises:
        ValueError: If an entry is malformed or addresses a cell outside the
            plate.

    Example:
        >>> sorted(parse_well_ranges(["A1", "A3"], 8, 12))
        [0, 2]
        >>> sorted(parse_well_ranges(["A1:B2"], 8, 12))
        [0, 1, 12, 13]
    """  # ruff: ignore[docstring-extraneous-exception]
    indices: set[int] = set()

    for entry in ranges:
        if _RANGE_SEP in entry:
            start_id, _, end_id = entry.partition(_RANGE_SEP)
            start_row, start_col = well_id_to_rc(start_id, num_row, num_col)
            end_row, end_col = well_id_to_rc(end_id, num_row, num_col)
            # Accept the corners in either order so "D6:A1" == "A1:D6".
            row_lo, row_hi = sorted((start_row, end_row))
            col_lo, col_hi = sorted((start_col, end_col))
            for row in range(row_lo, row_hi + 1):
                for col in range(col_lo, col_hi + 1):
                    indices.add(row * num_col + col)
        else:
            row, col = well_id_to_rc(entry, num_row, num_col)
            indices.add(row * num_col + col)

    return indices


def compress_to_ranges(indices: set[int], num_col: int) -> list[str]:
    """Summarize a set of flat indices as per-row well ranges.

    The inverse direction of `parse_well_ranges`, used when serializing state
    back to JSON so a saved file stays as readable as a hand-written one. Runs
    of consecutive columns within a row collapse to ``"A1:A6"``; isolated wells
    stay as ``"A1"``.

    Args:
        indices: Flat row-major indices to summarize.
        num_col: Number of columns in the plate.

    Returns:
        Sorted list of well IDs and ``start:end`` ranges covering exactly
        `indices`. Round-trips through `parse_well_ranges`.

    Example:
        >>> compress_to_ranges({0, 1, 2, 5}, 12)
        ['A1:A3', 'A6']
    """
    if not indices:
        return []

    ranges: list[str] = []
    run_start: int | None = None
    previous: int | None = None

    for index in sorted(indices):
        contiguous = (
            previous is not None
            and index == previous + 1
            # A run must not straddle a row boundary.
            and index // num_col == previous // num_col
        )
        if not contiguous:
            if run_start is not None and previous is not None:
                ranges.append(_format_run(run_start, previous, num_col))
            run_start = index
        previous = index

    if run_start is not None and previous is not None:
        ranges.append(_format_run(run_start, previous, num_col))

    return ranges


def _format_run(start: int, end: int, num_col: int) -> str:
    """Render one contiguous run of indices as a well ID or range.

    Args:
        start: First flat index of the run.
        end: Last flat index of the run (may equal `start`).
        num_col: Number of columns in the plate.

    Returns:
        A single well ID when the run has length one, else ``"start:end"``.
    """
    start_id = rc_to_well_id(*divmod(start, num_col))
    if start == end:
        return start_id
    return f"{start_id}{_RANGE_SEP}{rc_to_well_id(*divmod(end, num_col))}"


class TraversalOrder(BaseModel):
    """The order in which a rectangular plate's wells are visited.

    Four orthogonal fields combine to express any raster or serpentine walk of
    a grid, so new orderings are data rather than code. `major` picks which axis
    advances slowest, the two direction fields pick each axis's starting edge,
    and `serpentine` reverses every other pass.

    Attributes:
        major: Which axis is traversed as the outer loop. ``"row"`` completes a
            row before moving to the next; ``"column"`` completes a column.
        row_dir: Whether rows advance ``"top_down"`` (A first) or
            ``"bottom_up"`` (the last row first).
        col_dir: Whether columns advance ``"left_right"`` (column 1 first) or
            ``"right_left"`` (the last column first).
        serpentine: If True, every second pass runs in reverse, so the walk
            boustrophedons instead of returning to the same edge each time.

    Note:
        Frozen: `TraversalRegistry` hands out shared preset instances, so an
        accidental mutation would silently retarget every plate using that
        preset. Build a variant with ``model_copy(update=...)`` instead.

        Extra fields are rejected: a misspelled key in a hand-edited config
        would otherwise be dropped, leaving the plate on the default order
        with no indication anything was wrong.

    Example:
        >>> TraversalOrder().indices(2, 3)
        [0, 1, 2, 3, 4, 5]
        >>> TraversalOrder(major="column").indices(2, 3)
        [0, 3, 1, 4, 2, 5]
        >>> TraversalOrder(serpentine=True).indices(2, 3)
        [0, 1, 2, 5, 4, 3]
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    major: Literal["row", "column"] = "row"
    row_dir: Literal["top_down", "bottom_up"] = "top_down"
    col_dir: Literal["left_right", "right_left"] = "left_right"
    serpentine: bool = False

    def indices(self, num_row: int, num_col: int) -> list[int]:
        """Produce the full visiting sequence for a plate of this size.

        Args:
            num_row: Number of rows in the plate (must be positive).
            num_col: Number of columns in the plate (must be positive).

        Returns:
            Every flat row-major index in ``[0, num_row * num_col)`` exactly
            once, ordered according to this descriptor.

        Raises:
            ValueError: If `num_row` or `num_col` is not positive.

        Example:
            >>> order = TraversalOrder(
            ...     major="column", col_dir="right_left", row_dir="bottom_up"
            ... )
            >>> order.indices(2, 3)
            [5, 2, 4, 1, 3, 0]
        """
        if num_row <= 0 or num_col <= 0:
            raise ValueError(
                f"Plate dimensions must be positive, got {num_row}x{num_col}"
            )

        rows = list(range(num_row))
        if self.row_dir == "bottom_up":
            rows.reverse()
        cols = list(range(num_col))
        if self.col_dir == "right_left":
            cols.reverse()

        # `outer` advances slowest; `inner` sweeps within each outer step.
        outer, inner = (rows, cols) if self.major == "row" else (cols, rows)

        sequence: list[int] = []
        for pass_number, outer_value in enumerate(outer):
            sweep = inner if not (self.serpentine and pass_number % 2) else inner[::-1]
            for inner_value in sweep:
                row, col = (
                    (outer_value, inner_value)
                    if self.major == "row"
                    else (inner_value, outer_value)
                )
                sequence.append(row * num_col + col)
        return sequence


class TraversalRegistry:
    """Readable preset names for `TraversalOrder` descriptors.

    Configuration files name an order (``"column_from_bottom_right"``) rather
    than spelling out four axis fields, which keeps a hand-edited protocol file
    scannable. Every preset is just a descriptor, so adding one is a single
    entry here rather than a new class.

    This class should not be instantiated; all methods are class methods.

    Class Attributes:
        _presets: Mapping of preset name to the descriptor it denotes.
    """

    _presets: ClassVar[dict[str, TraversalOrder]] = {
        # A1 -> A12 -> B1 ...  (the historical default)
        "row_major": TraversalOrder(),
        # A1 -> H1 -> A2 ...
        "column_major": TraversalOrder(major="column"),
        # H12 -> G12 -> ... -> A12 -> H11 ...
        "column_from_bottom_right": TraversalOrder(
            major="column", col_dir="right_left", row_dir="bottom_up"
        ),
        # H12 -> H11 -> ... -> H1 -> G12 ...
        "row_from_bottom_right": TraversalOrder(
            row_dir="bottom_up", col_dir="right_left"
        ),
        # A1 -> A12 -> B12 -> B1 ...
        "row_serpentine": TraversalOrder(serpentine=True),
        # A1 -> H1 -> H2 -> A2 ...
        "column_serpentine": TraversalOrder(major="column", serpentine=True),
    }

    @classmethod
    def resolve(cls, name: str) -> TraversalOrder:
        """Look up a preset descriptor by name.

        Args:
            name: Preset name; case-insensitive and whitespace-tolerant.

        Returns:
            The `TraversalOrder` the preset denotes. The returned model is
            shared between callers, which is safe because it is frozen.

        Raises:
            ValueError: If no preset by that name is registered.

        Example:
            >>> TraversalRegistry.resolve("column_major").major
            'column'
        """
        key = name.strip().lower()
        try:
            return cls._presets[key]
        except KeyError:
            raise ValueError(
                f"Unknown traversal order {name!r}. "
                f"Available: {', '.join(cls.registered())}"
            ) from None

    @classmethod
    def name_for(cls, order: TraversalOrder) -> str | None:
        """Return the preset name for a descriptor, if one matches.

        The inverse of `resolve`, used when serializing a plate so a file that
        was written with a preset name round-trips back to that name instead of
        expanding into four fields.

        Args:
            order: The descriptor to look up.

        Returns:
            The matching preset name, or None if the descriptor is a
            combination no preset covers.

        Example:
            >>> TraversalRegistry.name_for(TraversalOrder())
            'row_major'
        """
        for name, preset in cls._presets.items():
            if preset == order:
                return name
        return None

    @classmethod
    def registered(cls) -> list[str]:
        """Return the names of all registered presets.

        Returns:
            Sorted list of preset names.
        """
        return sorted(cls._presets.keys())


def coerce_traversal_order(value: object) -> TraversalOrder:
    """Build a `TraversalOrder` from a preset name or an inline descriptor.

    Configuration may express an order either way, so every model that accepts
    one funnels through this helper:

    ```json
    "order": "column_from_bottom_right"
    "order": { "major": "column", "col_dir": "right_left" }
    ```

    Args:
        value: A preset name, a mapping of descriptor fields, or an existing
            `TraversalOrder` (returned unchanged).

    Returns:
        The resolved descriptor.

    Raises:
        ValueError: If `value` is a name no preset matches, or is neither a
            string, a mapping, nor a `TraversalOrder`.

    Example:
        >>> coerce_traversal_order("column_major").major
        'column'
        >>> coerce_traversal_order({"serpentine": True}).serpentine
        True
    """
    if isinstance(value, TraversalOrder):
        return value
    if isinstance(value, str):
        return TraversalRegistry.resolve(value)
    if isinstance(value, dict):
        return TraversalOrder(**value)  # pyright: ignore[reportUnknownArgumentType]
    raise ValueError(
        f"Traversal order must be a preset name or a descriptor object, "
        f"got {type(value).__name__}"
    )


class WellMask(BaseModel):
    """A restriction of a plate to a subset of its wells.

    Masking is membership, not ordering: a masked plate visits its remaining
    wells in exactly the relative order it otherwise would. Use this to run an
    assay on part of a plate (only columns 1-6) or to exclude wells that are
    known bad.

    Attributes:
        include: Well IDs and ranges that are eligible. None (the default)
            means every well is eligible.
        exclude: Well IDs and ranges to remove, applied after `include`.

    Note:
        Extra fields are rejected, so a misspelled key surfaces as an error
        rather than silently leaving the plate unmasked.

    Example:
        >>> mask = WellMask(include=["A1:B12"], exclude=["A1"])
        >>> len(mask.allowed(8, 12))
        23
    """

    model_config = ConfigDict(extra="forbid")

    include: list[str] | None = None
    exclude: list[str] = Field(default_factory=list)

    @field_validator("include", "exclude")
    @classmethod
    def _reject_blank_entries(cls, value: list[str] | None) -> list[str] | None:
        """Reject empty or whitespace-only range entries.

        A blank entry is almost always a trailing comma or an editing slip, and
        silently ignoring it would mask more wells than the author intended.

        Args:
            value: The list of range strings being validated, or None.

        Returns:
            The value unchanged when every entry is non-blank.

        Raises:
            ValueError: If any entry is empty or whitespace-only.
        """
        if value is not None and any(not entry.strip() for entry in value):
            raise ValueError("Well range entries must not be empty")
        return value

    def allowed(self, num_row: int, num_col: int) -> set[int]:
        """Compute the eligible flat indices for a plate of this size.

        Args:
            num_row: Number of rows in the plate.
            num_col: Number of columns in the plate.

        Returns:
            Set of eligible flat row-major indices, possibly empty if the mask
            excludes everything.

        Raises:
            ValueError: If a range is malformed or falls outside the plate.

        Example:
            >>> WellMask(exclude=["A1"]).allowed(2, 3)
            {1, 2, 3, 4, 5}
        """  # ruff: ignore[docstring-extraneous-exception]
        if self.include is None:
            eligible = set(range(num_row * num_col))
        else:
            eligible = parse_well_ranges(self.include, num_row, num_col)

        return eligible - parse_well_ranges(self.exclude, num_row, num_col)

    def is_noop(self) -> bool:
        """Report whether this mask restricts anything at all.

        Returns:
            True if the mask includes everything and excludes nothing, so
            callers can skip storing or serializing it.

        Example:
            >>> WellMask().is_noop()
            True
        """
        return self.include is None and not self.exclude
