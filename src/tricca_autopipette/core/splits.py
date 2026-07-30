"""Parsing for the ``pipette --splits`` multi-dispense specification.

A "split" is one destination of a multi-dispense: a single aspirate followed
by several metered dispenses, which saves a tip pickup and a source trip per
destination compared with running one ``pipette`` per well.

Parsing lives here rather than in ``commands/tap_cmd_parsers.py`` because the
domain layer (``core/autopipette.py``) is what validates a spec against the
actual deck, and ``commands/`` imports from ``core/`` rather than the other
way round.

Only *syntax* is checked here. Whether a destination exists, is a plate, and
has the addressed well is checked by ``AutoPipette.resolve_splits``, which is
the layer that can see the deck.

Example:
    >>> parse_splits_spec("plate_a:12@A1;plate_b:8")
    [Split(dest='plate_a', vol_ul=12.0, well_id='A1'),
     Split(dest='plate_b', vol_ul=8.0, well_id=None)]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LeftoverAction = Literal["keep", "waste"]
"""What to do with liquid still in the tip once every split has dispensed."""


@dataclass(frozen=True)
class Split:
    """One destination of a multi-dispense.

    Attributes:
        dest: Name of the destination location, which must be a plate.
        vol_ul: Volume to dispense into that destination, in microliters.
        well_id: Well ID such as ``"A1"``, or None to take the plate's next
            well according to its own traversal order.
    """

    dest: str
    vol_ul: float
    well_id: str | None


def parse_splits_spec(spec: str) -> list[Split]:
    """Parse a ``--splits`` specification string into Split entries.

    The grammar is ``DEST:VOL[@WELL]`` entries joined by ``;``. The ``@WELL``
    part is optional; omitting it lets the plate's traversal order pick the
    well, exactly as a plain ``pipette`` without ``--dest_row``/``--dest_col``
    does.

    Args:
        spec: The specification string, e.g. ``"plate_a:12@A1;plate_b:8@C3"``.

    Returns:
        The parsed splits, in the order they appear in ``spec``.

    Raises:
        ValueError: If `spec` is empty, an entry is missing its ``:``, a
            volume is not a positive number, or an entry names an empty
            destination.

    Example:
        >>> parse_splits_spec("plate_a:12@A1")
        [Split(dest='plate_a', vol_ul=12.0, well_id='A1')]
    """
    if not spec or not spec.strip():
        raise ValueError("Empty --splits specification.")

    splits: list[Split] = []
    for raw_entry in spec.split(";"):
        entry = raw_entry.strip()
        if not entry:
            continue

        if ":" not in entry:
            raise ValueError(
                f"Invalid split {entry!r}: expected 'DEST:VOL' or "
                f"'DEST:VOL@WELL', e.g. 'plate_a:12@A1'"
            )

        dest, _, rest = entry.partition(":")
        dest = dest.strip()
        if not dest:
            raise ValueError(f"Invalid split {entry!r}: empty destination name.")

        vol_str, _, well_id = rest.partition("@")
        well_id = well_id.strip()

        try:
            vol_ul = float(vol_str.strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid split {entry!r}: {vol_str.strip()!r} is not a number."
            ) from exc

        if vol_ul <= 0:
            raise ValueError(
                f"Invalid split {entry!r}: volume must be greater than zero."
            )

        splits.append(Split(dest=dest, vol_ul=vol_ul, well_id=well_id or None))

    if not splits:
        raise ValueError("Empty --splits specification.")

    return splits
