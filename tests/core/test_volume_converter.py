"""Unit tests for :class:`tricca_autopipette.core.volume_converter.VolumeConverter`."""

from __future__ import annotations

import pytest

from tricca_autopipette.core.volume_converter import VolumeConverter


class TestDefaultCalibration:
    def test_vol_to_steps_is_monotonically_increasing(self) -> None:
        converter = VolumeConverter()
        assert converter.vol_to_steps(0.0) < converter.vol_to_steps(100.0)
        assert converter.vol_to_steps(100.0) < converter.vol_to_steps(300.0)

    def test_steps_to_vol_is_approximate_inverse_of_vol_to_steps(self) -> None:
        converter = VolumeConverter()

        steps = converter.vol_to_steps(100.0)
        recovered_volume = converter.steps_to_vol(steps)

        assert recovered_volume == pytest.approx(100.0, rel=0.05)

    def test_get_calibration_points_round_trips_default_data(self) -> None:
        converter = VolumeConverter()
        volumes, steps = converter.get_calibration_points()

        assert 100.0 in volumes
        assert len(volumes) == len(steps)

    def test_get_fit_coefficients_matches_vol_to_steps(self) -> None:
        converter = VolumeConverter()
        slope, intercept = converter.get_fit_coefficients()

        assert slope * 100.0 + intercept == pytest.approx(converter.vol_to_steps(100.0))


class TestCustomCalibration:
    def test_custom_calibration_curve_is_used_instead_of_default(self) -> None:
        volumes = [0.0, 50.0, 100.0, 200.0]
        steps = [0.0, 25.0, 50.0, 100.0]
        converter = VolumeConverter(x=volumes, y=steps)

        # Roughly 2 steps per uL on this custom curve, vs. the shallower
        # default curve (100uL ~= 39.25 steps).
        assert converter.vol_to_steps(100.0) == pytest.approx(50.0, rel=0.1)

    def test_steps_to_vol_raises_when_no_positive_root_exists(self) -> None:
        converter = VolumeConverter()

        with pytest.raises(ValueError, match="No valid volume found"):
            converter.steps_to_vol(-1_000_000.0)

    def test_get_calibration_points_returns_custom_data_not_defaults(self) -> None:
        """Regression test: this used to always return the class defaults.

        ``VolumeConverter.__init__`` never stored its ``x``/``y`` args, so
        ``get_calibration_points`` had no way to report anything but the
        hardcoded ``_consts`` table, regardless of what the instance was
        actually fit from.
        """
        volumes = [0.0, 50.0, 100.0, 200.0]
        steps = [0.0, 25.0, 50.0, 100.0]
        converter = VolumeConverter(x=volumes, y=steps)

        assert converter.get_calibration_points() == (volumes, steps)

    def test_get_fit_coefficients_on_custom_curve(self) -> None:
        converter = VolumeConverter(x=[0.0, 100.0], y=[10.0, 60.0])
        slope, intercept = converter.get_fit_coefficients()

        assert slope == pytest.approx(0.5)
        assert intercept == pytest.approx(10.0)
