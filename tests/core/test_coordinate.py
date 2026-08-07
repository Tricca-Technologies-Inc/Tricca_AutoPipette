"""Unit tests for ``core/coordinate.py``'s ``Coordinate``."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from tricca_autopipette.core.coordinate import Coordinate


class TestConstruction:
    def test_negative_x_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Coordinate(x=-1.0, y=0.0, z=0.0)

    def test_negative_y_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Coordinate(x=0.0, y=-1.0, z=0.0)

    def test_negative_z_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Coordinate(x=0.0, y=0.0, z=-1.0)

    def test_zero_is_allowed(self) -> None:
        coord = Coordinate(x=0.0, y=0.0, z=0.0)
        assert coord.x == 0.0  # ruff:ignore[float-equality-comparison]


class TestReprAndStr:
    def test_repr(self) -> None:
        coord = Coordinate(x=1.0, y=2.0, z=3.0)
        assert repr(coord) == "Coordinate(x=1.0, y=2.0, z=3.0)"

    def test_str_formats_to_two_decimal_places(self) -> None:
        coord = Coordinate(x=1.5, y=2.25, z=3.14159)
        assert str(coord) == "(1.50, 2.25, 3.14)"


class TestEqualityAndHash:
    def test_equal_coordinates_compare_equal(self) -> None:
        assert Coordinate(x=1.0, y=2.0, z=3.0) == Coordinate(x=1.0, y=2.0, z=3.0)

    def test_different_coordinates_compare_unequal(self) -> None:
        assert Coordinate(x=1.0, y=2.0, z=3.0) != Coordinate(x=1.0, y=2.0, z=4.0)

    def test_comparison_with_non_coordinate_is_not_implemented(self) -> None:
        coord = Coordinate(x=1.0, y=2.0, z=3.0)
        assert coord.__eq__("not a coordinate") is NotImplemented
        assert coord != "not a coordinate"

    def test_equal_coordinates_hash_equal(self) -> None:
        a = Coordinate(x=1.0, y=2.0, z=3.0)
        b = Coordinate(x=1.0, y=2.0, z=3.0)
        assert hash(a) == hash(b)

    def test_usable_as_a_set_member(self) -> None:
        a = Coordinate(x=1.0, y=2.0, z=3.0)
        b = Coordinate(x=1.0, y=2.0, z=3.0)
        assert len({a, b}) == 1


class TestGenerateOffset:
    def test_applies_each_axis_independently(self) -> None:
        coord = Coordinate(x=10.0, y=20.0, z=5.0)
        offset = coord.generate_offset(dx=5.0, dy=-5.0, dz=2.0)
        assert offset == Coordinate(x=15.0, y=15.0, z=7.0)

    def test_does_not_mutate_the_original(self) -> None:
        coord = Coordinate(x=10.0, y=20.0, z=5.0)
        coord.generate_offset(dx=5.0)
        assert coord == Coordinate(x=10.0, y=20.0, z=5.0)

    def test_default_offsets_are_zero(self) -> None:
        coord = Coordinate(x=10.0, y=20.0, z=5.0)
        assert coord.generate_offset() == coord

    def test_negative_result_raises(self) -> None:
        coord = Coordinate(x=1.0, y=1.0, z=1.0)
        with pytest.raises(ValueError, match="negative values"):
            coord.generate_offset(dx=-5.0)


class TestDistanceTo:
    def test_euclidean_distance(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=0.0)
        b = Coordinate(x=3.0, y=4.0, z=0.0)
        assert a.distance_to(b) == pytest.approx(5.0)

    def test_distance_to_self_is_zero(self) -> None:
        coord = Coordinate(x=1.0, y=2.0, z=3.0)
        assert coord.distance_to(coord) == pytest.approx(0.0)

    def test_includes_the_z_axis(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=0.0)
        b = Coordinate(x=0.0, y=0.0, z=5.0)
        assert a.distance_to(b) == pytest.approx(5.0)

    def test_matches_manual_computation(self) -> None:
        a = Coordinate(x=1.0, y=2.0, z=3.0)
        b = Coordinate(x=4.0, y=6.0, z=15.0)
        expected = math.sqrt((4 - 1) ** 2 + (6 - 2) ** 2 + (15 - 3) ** 2)
        assert a.distance_to(b) == pytest.approx(expected)


class TestDistanceXy:
    def test_ignores_the_z_axis(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=10.0)
        b = Coordinate(x=3.0, y=4.0, z=20.0)
        assert a.distance_xy(b) == pytest.approx(5.0)

    def test_zero_when_only_z_differs(self) -> None:
        a = Coordinate(x=1.0, y=1.0, z=0.0)
        b = Coordinate(x=1.0, y=1.0, z=99.0)
        assert a.distance_xy(b) == pytest.approx(0.0)


class TestIsAboveBelow:
    def test_is_above_true_beyond_tolerance(self) -> None:
        higher = Coordinate(x=10.0, y=10.0, z=15.0)
        lower = Coordinate(x=10.0, y=10.0, z=10.0)
        assert higher.is_above(lower) is True

    def test_is_above_false_within_tolerance(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=10.005)
        b = Coordinate(x=0.0, y=0.0, z=10.0)
        assert a.is_above(b, tolerance=0.01) is False

    def test_is_above_false_when_equal_or_lower(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=5.0)
        b = Coordinate(x=0.0, y=0.0, z=10.0)
        assert a.is_above(b) is False

    def test_is_below_true_beyond_tolerance(self) -> None:
        lower = Coordinate(x=10.0, y=10.0, z=10.0)
        higher = Coordinate(x=10.0, y=10.0, z=15.0)
        assert lower.is_below(higher) is True

    def test_is_below_false_within_tolerance(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=9.995)
        b = Coordinate(x=0.0, y=0.0, z=10.0)
        assert a.is_below(b, tolerance=0.01) is False

    def test_is_below_false_when_equal_or_higher(self) -> None:
        a = Coordinate(x=0.0, y=0.0, z=10.0)
        b = Coordinate(x=0.0, y=0.0, z=5.0)
        assert a.is_below(b) is False


class TestIsWithinBounds:
    def test_inside_bounds(self) -> None:
        coord = Coordinate(x=5.0, y=5.0, z=5.0)
        assert coord.is_within_bounds(Coordinate.origin(), Coordinate(x=10, y=10, z=10))

    def test_on_the_boundary_is_inclusive(self) -> None:
        coord = Coordinate(x=10.0, y=10.0, z=10.0)
        assert coord.is_within_bounds(Coordinate.origin(), Coordinate(x=10, y=10, z=10))

    def test_outside_any_single_axis_fails(self) -> None:
        coord = Coordinate(x=11.0, y=5.0, z=5.0)
        assert not coord.is_within_bounds(
            Coordinate.origin(), Coordinate(x=10, y=10, z=10)
        )


class TestClamp:
    def test_clamps_each_axis_independently(self) -> None:
        coord = Coordinate(x=15.0, y=5.0, z=0.0)
        clamped = coord.clamp(Coordinate(x=0, y=0, z=2), Coordinate(x=10, y=10, z=10))
        assert clamped == Coordinate(x=10.0, y=5.0, z=2.0)

    def test_value_already_within_bounds_is_unchanged(self) -> None:
        coord = Coordinate(x=5.0, y=5.0, z=5.0)
        clamped = coord.clamp(Coordinate.origin(), Coordinate(x=10, y=10, z=10))
        assert clamped == coord

    def test_does_not_mutate_the_original(self) -> None:
        coord = Coordinate(x=15.0, y=5.0, z=5.0)
        coord.clamp(Coordinate.origin(), Coordinate(x=10, y=10, z=10))
        assert coord == Coordinate(x=15.0, y=5.0, z=5.0)


class TestOrigin:
    def test_returns_zero_zero_zero(self) -> None:
        assert Coordinate.origin() == Coordinate(x=0.0, y=0.0, z=0.0)


class TestToFromTuple:
    def test_to_tuple(self) -> None:
        coord = Coordinate(x=1.0, y=2.0, z=3.0)
        assert coord.to_tuple() == (1.0, 2.0, 3.0)

    def test_from_tuple(self) -> None:
        coord = Coordinate.from_tuple((1.0, 2.0, 3.0))
        assert coord == Coordinate(x=1.0, y=2.0, z=3.0)

    def test_round_trips(self) -> None:
        original = Coordinate(x=7.5, y=8.5, z=9.5)
        assert Coordinate.from_tuple(original.to_tuple()) == original
