#!/usr/bin/env python3
"""Holds the various plate classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.traversal import (
    TraversalOrder,
    WellMask,
    coerce_traversal_order,
)
from tricca_autopipette.core.well import Well


class PlateError(Exception):
    """Base exception for plate-related errors."""

    pass


class PlateExhaustedError(PlateError):
    """Raised when a plate configured with ``on_exhaust="error"`` runs out.

    Only plates that opt in raise this; the default is to wrap back to the
    first well, preserving the historical behavior. Tipboxes opt in, because
    revisiting a consumed tip position cross-contaminates the run.

    Attributes:
        total: Number of eligible wells the plate had.

    Example:
        >>> plate.next()  # after every eligible well has been visited
        PlateExhaustedError: All 96 well(s) have been visited.
    """

    def __init__(self, total: int) -> None:
        """Initialize error with the plate's eligible well count.

        Args:
            total: Number of eligible wells in the plate.
        """
        self.total = total
        super().__init__(f"All {total} well(s) have been visited.")


class InvalidPlateTypeError(PlateError):
    """Raised when an invalid plate type is specified."""

    def __init__(self, plate_type: str, valid_types: list[str]) -> None:
        """Initialize error with plate type and valid options.

        Args:
            plate_type: The invalid plate type that was requested.
            valid_types: List of valid registered plate types.
        """
        valid = ", ".join(valid_types)
        super().__init__(f"Invalid plate type '{plate_type}'. Valid types: {valid}")


class SmartDefaultModel(BaseModel):
    """Base model that uses defaults for explicit `None` values."""

    @field_validator("*", mode="before")
    @classmethod
    def _replace_none_with_default(cls, value: object, info: ValidationInfo) -> object:
        """Replace None values with field defaults.

        Args:
            value: The field value to validate.
            info: Pydantic validation context information.

        Returns:
            The original value if not None, otherwise the field's default value.
        """
        if value is not None or info.field_name is None:
            return value

        field = cls.model_fields[info.field_name]
        return field.get_default()


class PlateParams(SmartDefaultModel):
    """Data validation class for plate configuration.

    Attributes:
        plate_type: Type of plate to create (must be registered).
        well_template: Template well to use for creating all wells.
        num_row: Number of rows in the plate.
        num_col: Number of columns in the plate.
        spacing_row: Spacing between rows in mm.
        spacing_col: Spacing between columns in mm.
        order: Order in which wells are visited. Accepts a preset name (e.g.
            ``"column_from_bottom_right"``) or an inline descriptor; defaults
            to row-major, which is the historical behavior.
        mask: Optional restriction to a subset of wells. None means all wells
            are eligible.
        on_exhaust: What `Plate.next` does once every eligible well has been
            visited -- ``"wrap"`` returns to the first well (the historical
            behavior, and usually what a source plate wants), ``"error"``
            raises. Tipboxes default to ``"error"``, since silently reusing a
            tip cross-contaminates the run.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plate_type: str
    well_template: Well
    num_row: int = Field(default=1, ge=1)
    num_col: int = Field(default=1, ge=1)
    spacing_row: float = Field(default=0.0, ge=0)
    spacing_col: float = Field(default=0.0, ge=0)
    # A plain default rather than a factory: TraversalOrder is frozen, so one
    # shared instance is safe, and SmartDefaultModel's None-to-default pass
    # resolves it via FieldInfo.get_default(), which does not call factories.
    order: TraversalOrder = TraversalOrder()
    mask: WellMask | None = None
    on_exhaust: Literal["wrap", "error"] = "wrap"

    @field_validator("plate_type")
    @classmethod
    def validate_plate_type(cls, v: str) -> str:
        """Ensure plate is a valid registered type.

        Args:
            v: The plate type string to validate.

        Returns:
            Normalized (lowercase, stripped) plate type string.

        Raises:
            ValueError: If plate type is not registered.
        """
        normalized = v.strip().lower()
        if normalized not in PlateFactory.registered():
            raise ValueError(
                f"Invalid plate type '{v}'. "
                f"Valid types: {', '.join(PlateFactory.registered())}"
            )
        return normalized

    @field_validator("order", mode="before")
    @classmethod
    def resolve_order(cls, v: object) -> TraversalOrder:
        """Accept a preset name as well as a descriptor for `order`.

        Config files name an order for readability; this normalizes both forms
        to a `TraversalOrder`, mirroring how `validate_plate_type` normalizes
        the plate type string.

        Args:
            v: A preset name, an inline descriptor mapping, an existing
                `TraversalOrder`, or None for the default row-major order.

        Returns:
            The resolved traversal descriptor.

        Raises:
            ValueError: If the name matches no registered preset, or the value
                is not a name, mapping, or `TraversalOrder`.

        Note:
            None is handled here rather than relying on `SmartDefaultModel`,
            since both are "before" validators and their relative order is an
            implementation detail of pydantic.
        """
        if v is None:
            return TraversalOrder()
        return coerce_traversal_order(v)


class Plate(ABC):
    """Base class for plate types that manage wells for pipetting.

    Wells are always generated and stored row-major in `wells`, so a flat index
    is ``row * num_col + col`` regardless of configuration. The *visiting* order
    is a separate concern held in `sequence`: a list of flat indices, produced
    by the configured `TraversalOrder` and filtered by the optional `WellMask`.
    `curr` is a cursor into `sequence`, not into `wells`.

    With the defaults (row-major order, no mask) `sequence` is the identity, so
    `curr` and the flat well index coincide -- which is what keeps existing
    behavior and the `current_row`/`current_col` examples below unchanged.

    Attributes:
        start_coor: Starting coordinate for the first well.
        well_template: Template well used to create all wells.
        num_row: Number of rows in the plate.
        num_col: Number of columns in the plate.
        spacing_row: Spacing between rows in mm.
        spacing_col: Spacing between columns in mm.
        order: The configured traversal order.
        mask: The configured well mask, or None if unrestricted.
        on_exhaust: ``"wrap"`` or ``"error"`` -- what `next` does at the end.
        sequence: Flat well indices in visiting order.
        curr: Cursor into `sequence`.
        wells: List of all wells in the plate, row-major.
    """

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize plate by creating all wells and its visiting sequence.

        Args:
            plate_params: Validated plate configuration parameters.

        Raises:
            ValueError: If the mask excludes every well, leaving the plate with
                nothing to visit.
        """
        self.start_coor = plate_params.well_template.coor
        self.well_template = plate_params.well_template
        self.num_row = plate_params.num_row
        self.num_col = plate_params.num_col
        self.spacing_row = plate_params.spacing_row
        self.spacing_col = plate_params.spacing_col
        self.order = plate_params.order
        self.mask = plate_params.mask
        self.on_exhaust = plate_params.on_exhaust
        self.curr = 0

        self.wells = self._gen_wells(
            self.start_coor,
            self.well_template,
            self.num_row,
            self.num_col,
            self.spacing_row,
            self.spacing_col,
        )

        self.sequence = self._build_sequence()

    def _build_sequence(self) -> list[int]:
        """Compute the flat well indices to visit, in order.

        Returns:
            Flat row-major indices ordered by `order` and filtered by `mask`.

        Raises:
            ValueError: If `mask` leaves no eligible wells. A plate that can
                never yield a coordinate is a configuration mistake worth
                catching at load time rather than mid-protocol.
        """
        sequence = self.order.indices(self.num_row, self.num_col)

        if self.mask is not None and not self.mask.is_noop():
            eligible = self.mask.allowed(self.num_row, self.num_col)
            sequence = [index for index in sequence if index in eligible]
            if not sequence:
                raise ValueError(
                    f"Well mask excludes every well of this "
                    f"{self.num_row}x{self.num_col} plate"
                )

        return sequence

    def __repr__(self) -> str:
        """Return string representation for debugging.

        Returns:
            String showing plate type, dimensions, and well count.
        """
        return (
            f"{self.__class__.__name__}("
            f"rows={self.num_row}, cols={self.num_col}, "
            f"wells={self.total_wells})"
        )

    def __iter__(self) -> Iterator[Well]:
        """Make plate iterable over wells.

        Returns:
            Iterator over Well instances in row-major order.

        Example:
            >>> plate = PlateArray(params)
            >>> for well in plate:
            ...     print(well.coor)
        """
        return iter(self.wells)

    def __len__(self) -> int:
        """Return number of wells.

        Returns:
            Total well count.
        """
        return len(self.wells)

    def __getitem__(self, index: int) -> Well:
        """Get well by index.

        Args:
            index: Well index (supports negative indexing).

        Returns:
            Well at the specified index.

        Note:
            Supports negative indexing like standard Python lists.
            Index out of range will raise IndexError from the underlying list.

        Example:
            >>> plate = PlateArray(params)
            >>> well = plate[0]  # First well
            >>> well = plate[-1]  # Last well
        """
        return self.wells[index]

    @abstractmethod
    def _gen_wells(
        self,
        start_coor: Coordinate,
        well_template: Well,
        num_row: int,
        num_col: int,
        spacing_row: float,
        spacing_col: float,
    ) -> list[Well]:
        """Generate all the wells for the plate.

        Args:
            start_coor: Starting coordinate for the first well.
            well_template: Template well to copy for each position.
            num_row: Number of rows to generate.
            num_col: Number of columns to generate.
            spacing_row: Spacing between rows in mm.
            spacing_col: Spacing between columns in mm.

        Returns:
            List of Well objects positioned according to plate layout.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement _gen_wells")

    def _is_valid_position(self, row: int, col: int) -> bool:
        """Check if row/col position is within plate bounds.

        Args:
            row: Zero-indexed row number.
            col: Zero-indexed column number.

        Returns:
            True if position is valid, False otherwise.
        """
        return 0 <= row < self.num_row and 0 <= col < self.num_col

    @property
    def current_index(self) -> int:
        """The flat well index the cursor currently points at.

        Returns:
            Zero-based index into `wells`. Equals `curr` for a default
            row-major, unmasked plate.

        Note:
            Clamped to the last position in `sequence` so a cursor left past
            the end by an ``on_exhaust="error"`` plate still reports a real
            well rather than raising from a property.

        Example:
            >>> plate = PlateArray(params)  # 8x12 plate, default order
            >>> plate.curr = 12
            >>> plate.current_index
            12
        """
        if self.curr >= len(self.sequence):
            return self.sequence[-1]
        return self.sequence[self.curr]

    @property
    def current_row(self) -> int:
        """The current row index based on current well position.

        Returns:
            Zero-indexed row number of the current well.

        Example:
            >>> plate = PlateArray(params)  # 8x12 plate
            >>> plate.curr = 0
            >>> plate.current_row
            0
            >>> plate.curr = 12  # Second row, first column
            >>> plate.current_row
            1
            >>> plate.curr = 95  # Last well (H12)
            >>> plate.current_row
            7
        """
        return self.current_index // self.num_col

    @property
    def current_col(self) -> int:
        """The current column index based on current well position.

        Returns:
            Zero-indexed column number of the current well.

        Example:
            >>> plate = PlateArray(params)  # 8x12 plate
            >>> plate.curr = 0
            >>> plate.current_col
            0
            >>> plate.curr = 12  # Second row, first column
            >>> plate.current_col
            0
            >>> plate.curr = 95  # Last well (H12)
            >>> plate.current_col
            11
        """
        return self.current_index % self.num_col

    @abstractmethod
    def get_coor(self, row: int, col: int) -> Coordinate:
        """Return coordinate at specific row and column.

        Args:
            row: Zero-indexed row number.
            col: Zero-indexed column number.

        Returns:
            Coordinate at the specified position, or None if out of bounds.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_coor")

    def get_well(self, row: int, col: int) -> Well | None:
        """Get well at specific row and column.

        Args:
            row: Zero-indexed row number.
            col: Zero-indexed column number.

        Returns:
            Well at the specified position, or None if out of bounds.

        Example:
            >>> plate = PlateArray(params)
            >>> well = plate.get_well(0, 0)
            >>> well.coor
            Coordinate(x=10.0, y=20.0, z=5.0)
        """
        if not self._is_valid_position(row, col):
            return None

        index = col + self.num_col * row
        return self.wells[index]

    @abstractmethod
    def get_dip_distance(self, vol: float | None) -> float:
        """Return the distance needed to dip into current well.

        Args:
            vol: Volume of liquid being aspirated/dispensed in microliters.

        Returns:
            Dip distance in mm from the top of the well.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_dip_distance")

    @abstractmethod
    def next(self) -> Coordinate:
        """Return the next coordinate, wrapping to start if at end.

        Returns:
            Coordinate of the next well in the iteration sequence.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement next")

    @property
    def total_wells(self) -> int:
        """The total number of wells.

        Returns:
            Total count of wells in the plate.
        """
        return len(self.wells)

    def reset(self) -> None:
        """Reset the current well index to the beginning."""
        self.curr = 0


class PlateFactory:
    """Factory for creating and managing plate types.

    This factory uses a registry pattern to allow dynamic registration
    of plate types and creation of plate instances.

    Attributes:
        _registry: Class-level registry mapping plate type names to classes.
    """

    _registry: ClassVar[dict[str, type[Plate]]] = {}

    @classmethod
    def register[PlateT: Plate](
        cls, plate_type: str
    ) -> Callable[[type[PlateT]], type[PlateT]]:
        """Decorator to register new plate types.

        Args:
            plate_type: The name to register the plate type under.

        Returns:
            Decorator function that registers the plate class.

        Note:
            The decorated class must be a subclass of Plate (enforced by type
            hints). The decorator is generic in that subclass so the decorated
            name keeps its own type -- otherwise ``TipBox`` would be seen as a
            bare ``Plate`` and its tip-specific methods would be invisible to
            type checkers.

        Example:
            >>> @PlateFactory.register("custom")
            >>> class CustomPlate(Plate):
            ...     pass
        """

        def decorator(subclass: type[PlateT]) -> type[PlateT]:
            key = plate_type.strip().lower()
            if key in cls._registry:
                raise ValueError(f"Plate type '{key}' already registered")

            cls._registry[key] = subclass
            return subclass

        return decorator

    @classmethod
    def create(cls, plate_params: PlateParams) -> Plate:
        """Create a plate instance from validated parameters.

        Args:
            plate_params: Validated plate configuration.

        Returns:
            Instance of the requested plate type.

        Raises:
            InvalidPlateTypeError: If plate type is not registered.

        Note:
            The plate_type is already normalized and validated by PlateParams,
            so no additional validation is needed here.
        """
        key = plate_params.plate_type  # Already normalized by validator

        try:
            plate_class = cls._registry[key]
        except KeyError:
            raise InvalidPlateTypeError(key, cls.registered()) from None

        return plate_class(plate_params)

    @classmethod
    def registered(cls) -> list[str]:
        """Return list of registered plate type names.

        Returns:
            Sorted list of registered plate type names.
        """
        return sorted(cls._registry.keys())

    @classmethod
    def type_name_for(cls, plate: Plate) -> str:
        """Return the registered plate-type name for a plate instance.

        The inverse of :meth:`create`. Needed anywhere a plate must be
        serialized back to the type string ``PlateParams.plate_type``
        expects (e.g. ``LocationManager.save_to_json``) -- ``type(plate)``
        alone isn't that string (e.g. ``PlateArray`` registers as
        ``"array"``, not ``"platearray"``).

        Args:
            plate: A plate instance, normally one created via :meth:`create`.

        Returns:
            The registry key whose class is exactly ``type(plate)``.

        Raises:
            InvalidPlateTypeError: If ``type(plate)`` isn't a registered
                plate class.
        """
        for key, plate_class in cls._registry.items():
            if plate_class is type(plate):
                return key
        raise InvalidPlateTypeError(type(plate).__name__, cls.registered())


@PlateFactory.register("array")
class PlateArray(Plate):
    """Standard rectangular array of wells.

    Wells are arranged in a grid pattern with configurable spacing.
    Coordinates are calculated from a starting position with wells
    arranged left-to-right, top-to-bottom.
    """

    def _gen_wells(
        self,
        start_coor: Coordinate,
        well_template: Well,
        num_row: int,
        num_col: int,
        spacing_row: float,
        spacing_col: float,
    ) -> list[Well]:
        """Generate wells in a rectangular grid pattern.

        Args:
            start_coor: Starting coordinate for the first well.
            well_template: Template well to copy for each position.
            num_row: Number of rows to generate.
            num_col: Number of columns to generate.
            spacing_row: Spacing between rows in mm.
            spacing_col: Spacing between columns in mm.

        Returns:
            List of Well objects positioned in a rectangular grid.
        """
        wells: list[Well] = []

        for row in range(num_row):
            for col in range(num_col):
                x = start_coor.x - (col * spacing_col)
                y = start_coor.y + (row * spacing_row)
                z = start_coor.z

                new_well = Well(
                    coor=Coordinate(x=x, y=y, z=z),
                    dip_top=well_template.dip_top,
                    dip_btm=well_template.dip_btm,
                    strategy_type=well_template.strategy_type,
                    well_diameter=well_template.well_diameter,
                )
                wells.append(new_well)

        return wells

    def get_coor(self, row: int, col: int) -> Coordinate:
        """Return coordinate at specific row and column.

        Args:
            row: Zero-indexed row number.
            col: Zero-indexed column number.

        Returns:
            Coordinate at the specified position, or None if out of bounds.

        Raises:
            ValueError: If row and/or col is invalid
        """
        if not self._is_valid_position(row, col):
            raise ValueError(f"row:{row} and col:{col} is invalid.")

        index = col + self.num_col * row
        return self.wells[index].coor

    def get_dip_distance(self, vol: float | None) -> float:
        """Return the distance needed to dip into current well.

        Args:
            vol: Volume of liquid being aspirated/dispensed in microliters.

        Returns:
            Dip distance in mm from the top of the well.
        """
        if vol is None:
            vol = 0
        return self.wells[self.current_index].get_dip_distance(vol)

    def next(self) -> Coordinate:
        """Return the next coordinate in the plate's traversal order.

        Advances the cursor through `sequence`. Once every eligible well has
        been visited, behavior depends on `on_exhaust`: ``"wrap"`` restarts at
        the first well, ``"error"`` raises.

        Returns:
            Coordinate of the next well in the configured traversal order.

        Raises:
            PlateExhaustedError: If every well has been visited and
                `on_exhaust` is ``"error"``.

        Example:
            >>> plate = PlateArray(params)  # default row-major order
            >>> plate.next()  # A1, then A2, A3, ...
            Coordinate(x=10.0, y=20.0, z=5.0)
        """
        if self.curr >= len(self.sequence):
            if self.on_exhaust == "error":
                raise PlateExhaustedError(len(self.sequence))
            self.curr = 0

        coor = self.wells[self.sequence[self.curr]].coor
        self.curr += 1
        # Wrapping plates never park past the end, so `current_*` keeps
        # describing the well that will be handed out next.
        if self.on_exhaust == "wrap" and self.curr >= len(self.sequence):
            self.curr = 0
        return coor


@PlateFactory.register("singleton")
class PlateSingleton(PlateArray):
    """Single-well plate that always returns the same coordinate.

    This plate type is useful for representing containers with a single
    access point, such as reagent bottles or bulk containers.
    """

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize with forced single well configuration.

        Args:
            plate_params: Plate configuration (dimensions will be overridden).
        """
        # Create a copy with singleton dimensions to avoid mutating the caller's object
        singleton_params = plate_params.model_copy(
            update={
                "num_row": 1,
                "num_col": 1,
                "spacing_row": 0.0,
                "spacing_col": 0.0,
            }
        )
        super().__init__(singleton_params)

    def next(self) -> Coordinate:
        """Return the single coordinate without incrementing.

        Returns:
            Always returns the same coordinate (the only well).
        """
        return self.wells[0].coor


@PlateFactory.register("tipbox")
class TipBox(PlateArray):
    """Plate containing disposable pipette tips, tracking which remain.

    Unlike a sample plate, a tipbox's positions are *consumed*: once a tip is
    picked up, that position is empty until the box is physically reloaded. The
    box therefore keeps a presence map alongside its traversal sequence, and
    `take_tip` skips positions already consumed rather than blindly advancing.

    A box is assumed **full** when constructed. Persisted state is layered on
    afterwards by `TipBoxManager.restore`, and `reset_tips` is the explicit
    "I swapped in a fresh box" signal.

    Multiple boxes are combined by registering them with a `TipBoxManager`,
    which draws from them in order. Boxes are never merged into one another --
    an earlier design spliced their well lists together, which destroyed any
    record of which tip came from which box and made unloading one impossible.

    Attributes:
        present: Per-position tip presence, indexed by flat well index.
    """

    def __init__(self, plate_params: PlateParams) -> None:
        """Initialize a full tipbox.

        Args:
            plate_params: Plate configuration. `on_exhaust` is forced to
                ``"error"`` -- wrapping would hand back a used tip.
        """
        super().__init__(plate_params.model_copy(update={"on_exhaust": "error"}))
        self.present: list[bool] = [True] * len(self.wells)

    @property
    def capacity(self) -> int:
        """Number of tip positions this box can hold.

        Returns:
            Count of eligible (unmasked) positions, which is the number of tips
            a full box supplies.
        """
        return len(self.sequence)

    @property
    def remaining(self) -> int:
        """Number of tips still available.

        Returns:
            Count of eligible positions that still hold a tip.

        Example:
            >>> box.remaining
            84
        """
        return sum(1 for index in self.sequence if self.present[index])

    def peek_tip(self) -> int | None:
        """Return the flat index of the next available tip without taking it.

        Returns:
            Flat well index of the next tip in traversal order, or None if the
            box is empty.
        """
        for cursor in range(self.curr, len(self.sequence)):
            index = self.sequence[cursor]
            if self.present[index]:
                return index
        return None

    def take_tip(self) -> tuple[int, Coordinate]:
        """Consume the next available tip.

        Advances past any positions already consumed, marks the chosen position
        empty, and leaves the cursor just after it. Never wraps.

        Returns:
            Tuple of the flat well index and the coordinate of the tip taken.

        Raises:
            PlateExhaustedError: If no tips remain in this box.

        Example:
            >>> index, coor = box.take_tip()
            >>> box.present[index]
            False
        """
        while self.curr < len(self.sequence):
            index = self.sequence[self.curr]
            self.curr += 1
            if self.present[index]:
                self.present[index] = False
                return index, self.wells[index].coor

        raise PlateExhaustedError(self.capacity)

    def reset_tips(self) -> None:
        """Mark every position as holding a tip and rewind the cursor.

        The explicit "a fresh box has been loaded" signal, needed because
        consumption is persisted across daemon restarts.

        Example:
            >>> box.reset_tips()
            >>> box.remaining == box.capacity
            True
        """
        self.present = [True] * len(self.wells)
        self.curr = 0

    def set_presence(self, present: list[bool]) -> None:
        """Replace the presence map wholesale.

        Used when restoring persisted state or when an operator declares a
        partially-used box. The cursor is rewound to the start so the next
        `take_tip` scans from the beginning and finds the first tip that is
        actually present.

        Args:
            present: One flag per well, indexed by flat well index.

        Raises:
            ValueError: If `present` is not exactly one flag per well. A
                mismatched map would silently misalign consumed positions onto
                different physical wells.

        Example:
            >>> box.set_presence([False] * 12 + [True] * 84)
            >>> box.remaining
            84
        """
        if len(present) != len(self.wells):
            raise ValueError(
                f"Presence map has {len(present)} entries but this tipbox has "
                f"{len(self.wells)} wells"
            )
        self.present = list(present)
        self.curr = 0

    def consumed_indices(self) -> set[int]:
        """Return the eligible positions whose tips have been used.

        Returns:
            Set of flat well indices that are in the traversal sequence but no
            longer hold a tip. Masked-out positions are excluded, since they
            were never available in the first place.
        """
        return {index for index in self.sequence if not self.present[index]}


@PlateFactory.register("waste_container")
class WasteContainer(PlateSingleton):
    """Single location for disposing used tips and waste.

    A waste container has a single disposal point and doesn't track
    volume or liquid levels.
    """

    pass
