"""Unit tests for ``core/well.py``: dip strategies, registry, and ``Well``."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from tricca_autopipette.core.coordinate import Coordinate
from tricca_autopipette.core.well import (
    CylinderDipStrategy,
    DipStrategy,
    SimpleDipStrategy,
    StrategyRegistry,
    StrategyType,
    Well,
    WellParams,
)


def _coord() -> Coordinate:
    return Coordinate(x=10.0, y=20.0, z=5.0)


class TestDipStrategyAbstractBody:
    """`DipStrategy`'s two abstract methods carry a real (if unreachable in

    normal use) `NotImplementedError` body -- covered here by a subclass
    that delegates to `super()` rather than overriding fully.
    """

    class _PassThrough(DipStrategy):
        def calculate_dip_distance(self, well: Well, volume: float) -> float:
            return super().calculate_dip_distance(  # pyright: ignore[reportAbstractUsage]
                well, volume
            )

        def validate_well_config(
            self, well_diameter: float | None, dip_btm: float | None
        ) -> None:
            super().validate_well_config(  # pyright: ignore[reportAbstractUsage]
                well_diameter, dip_btm
            )

    def test_calculate_dip_distance_base_raises(self) -> None:
        strategy = self._PassThrough()
        well = Well(coor=_coord(), dip_top=10.0)

        with pytest.raises(NotImplementedError):
            strategy.calculate_dip_distance(well, 100.0)

    def test_validate_well_config_base_raises(self) -> None:
        strategy = self._PassThrough()

        with pytest.raises(NotImplementedError):
            strategy.validate_well_config(8.0, 50.0)


class TestSimpleDipStrategy:
    def test_returns_dip_top_regardless_of_volume(self) -> None:
        strategy = SimpleDipStrategy()
        well = Well(coor=_coord(), dip_top=10.0)

        # Exact JSON round-trip of a literal, not a computed value.
        distance = strategy.calculate_dip_distance(well, 100.0)
        assert distance == 10.0  # ruff:ignore[float-equality-comparison]

    def test_validate_well_config_never_raises(self) -> None:
        strategy = SimpleDipStrategy()
        strategy.validate_well_config(None, None)  # must not raise
        strategy.validate_well_config(8.0, 50.0)  # must not raise


class TestCylinderDipStrategy:
    def test_calculate_dip_distance_updates_dip_curr(self) -> None:
        strategy = CylinderDipStrategy()
        well = Well(
            coor=_coord(),
            dip_top=10.0,
            dip_btm=50.0,
            strategy_type=StrategyType.CYLINDER,
            well_diameter=8.0,
        )

        distance = strategy.calculate_dip_distance(well, 100.0)

        radius_m = 8.0 / (2 * strategy.MM_TO_M)
        expected_change_mm = (
            (100.0 * strategy.LITERS_TO_CUBIC_M) / (math.pi * radius_m**2)
        ) * strategy.MM_TO_M
        assert distance == pytest.approx(10.0 + expected_change_mm)
        assert well.dip_curr == pytest.approx(distance)

    def test_result_is_clamped_to_dip_btm(self) -> None:
        strategy = CylinderDipStrategy()
        well = Well(
            coor=_coord(),
            dip_top=45.0,
            dip_btm=50.0,
            strategy_type=StrategyType.CYLINDER,
            well_diameter=8.0,
        )

        # A huge volume would overshoot dip_btm without clamping.
        distance = strategy.calculate_dip_distance(well, 1_000_000.0)

        assert distance == 50.0  # ruff:ignore[float-equality-comparison]

    def test_missing_well_diameter_raises(self) -> None:
        strategy = CylinderDipStrategy()
        well = Well(coor=_coord(), dip_top=10.0)
        well.dip_btm = 50.0  # bypass Well.__init__'s own validation

        with pytest.raises(ValueError, match="well_diameter and dip_btm"):
            strategy.calculate_dip_distance(well, 100.0)

    def test_missing_dip_btm_raises(self) -> None:
        strategy = CylinderDipStrategy()
        well = Well(coor=_coord(), dip_top=10.0)
        well.well_diameter = 8.0  # bypass Well.__init__'s own validation

        with pytest.raises(ValueError, match="well_diameter and dip_btm"):
            strategy.calculate_dip_distance(well, 100.0)

    def test_validate_well_config_requires_diameter(self) -> None:
        strategy = CylinderDipStrategy()
        with pytest.raises(ValueError, match="requires well_diameter"):
            strategy.validate_well_config(None, 50.0)

    def test_validate_well_config_requires_dip_btm(self) -> None:
        strategy = CylinderDipStrategy()
        with pytest.raises(ValueError, match="requires dip_btm"):
            strategy.validate_well_config(8.0, None)

    def test_validate_well_config_passes_with_both(self) -> None:
        strategy = CylinderDipStrategy()
        strategy.validate_well_config(8.0, 50.0)  # must not raise


class TestStrategyRegistry:
    def test_get_strategy_returns_singleton_per_type(self) -> None:
        assert isinstance(
            StrategyRegistry.get_strategy(StrategyType.SIMPLE), SimpleDipStrategy
        )
        assert isinstance(
            StrategyRegistry.get_strategy(StrategyType.CYLINDER), CylinderDipStrategy
        )
        # Same instance every time (registry, not a factory).
        assert StrategyRegistry.get_strategy(
            StrategyType.SIMPLE
        ) is StrategyRegistry.get_strategy(StrategyType.SIMPLE)

    def test_get_strategy_type_reverse_lookup_first_entry(self) -> None:
        assert (
            StrategyRegistry.get_strategy_type(SimpleDipStrategy())
            == StrategyType.SIMPLE
        )

    def test_get_strategy_type_reverse_lookup_later_entry(self) -> None:
        """Exercises the loop continuing past a non-matching first entry."""
        assert (
            StrategyRegistry.get_strategy_type(CylinderDipStrategy())
            == StrategyType.CYLINDER
        )

    def test_get_strategy_type_unknown_strategy_raises(self) -> None:
        class _NotRegistered(DipStrategy):
            def calculate_dip_distance(self, well: Well, volume: float) -> float:
                return 0.0

            def validate_well_config(
                self, well_diameter: float | None, dip_btm: float | None
            ) -> None:
                pass

        with pytest.raises(ValueError, match="Unknown strategy"):
            StrategyRegistry.get_strategy_type(_NotRegistered())


class TestWellParams:
    def test_simple_strategy_needs_no_extra_params(self) -> None:
        params = WellParams(coor=_coord(), dip_top=10.0)
        assert params.strategy_type == StrategyType.SIMPLE

    def test_cylinder_strategy_valid_with_both_params(self) -> None:
        params = WellParams(
            coor=_coord(),
            dip_top=10.0,
            dip_btm=50.0,
            strategy_type=StrategyType.CYLINDER,
            well_diameter=8.0,
        )
        assert params.well_diameter == 8.0  # ruff:ignore[float-equality-comparison]

    def test_cylinder_strategy_missing_diameter_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires well_diameter"):
            WellParams(
                coor=_coord(),
                dip_top=10.0,
                dip_btm=50.0,
                strategy_type=StrategyType.CYLINDER,
            )

    def test_cylinder_strategy_missing_dip_btm_rejected(self) -> None:
        with pytest.raises(ValidationError, match="requires dip_btm"):
            WellParams(
                coor=_coord(),
                dip_top=10.0,
                strategy_type=StrategyType.CYLINDER,
                well_diameter=8.0,
            )

    def test_non_positive_dip_top_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WellParams(coor=_coord(), dip_top=0.0)


class TestWellStrategyTypeProperty:
    def test_reports_configured_strategy(self) -> None:
        well = Well(
            coor=_coord(),
            dip_top=10.0,
            dip_btm=50.0,
            strategy_type=StrategyType.CYLINDER,
            well_diameter=8.0,
        )
        assert well.strategy_type == StrategyType.CYLINDER

    def test_defaults_to_simple(self) -> None:
        well = Well(coor=_coord(), dip_top=10.0)
        assert well.strategy_type == StrategyType.SIMPLE


class TestWellConstructionValidation:
    def test_cylinder_without_diameter_raises_at_construction(self) -> None:
        with pytest.raises(ValueError, match="requires well_diameter"):
            Well(coor=_coord(), dip_top=10.0, strategy_type=StrategyType.CYLINDER)

    def test_get_dip_distance_delegates_to_strategy(self) -> None:
        well = Well(
            coor=_coord(),
            dip_top=10.0,
            dip_btm=50.0,
            strategy_type=StrategyType.CYLINDER,
            well_diameter=8.0,
        )
        assert well.get_dip_distance(0.0) == pytest.approx(10.0)
