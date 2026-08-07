"""Unit tests for the gap-fill areas of ``core/pipette_models.py``.

Most of this module is exercised incidentally by config-loading tests
(``test_json_config_manager.py``) and ``autopipette`` fixtures; this file
covers what those never happen to touch: ``PipetteState.has_tip``'s
getter/setter, and the calibration-data validation shared (as duplicated
logic) by ``PipetteSyringeKinematics`` and ``LiquidProfile``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tricca_autopipette.core.pipette_models import (
    LiquidProfile,
    PipetteState,
    PipetteSyringeKinematics,
    TipState,
)


class TestPipetteStateHasTip:
    def test_true_when_attached(self) -> None:
        state = PipetteState(tip_state=TipState.ATTACHED)
        assert state.has_tip is True

    def test_false_when_detached(self) -> None:
        state = PipetteState(tip_state=TipState.DETACHED)
        assert state.has_tip is False

    def test_false_when_unknown(self) -> None:
        """UNKNOWN is treated as False for safety."""
        state = PipetteState(tip_state=TipState.UNKNOWN)
        assert state.has_tip is False

    def test_setter_true_sets_attached(self) -> None:
        state = PipetteState()
        state.has_tip = True
        assert state.tip_state == TipState.ATTACHED

    def test_setter_false_sets_detached(self) -> None:
        state = PipetteState()
        state.has_tip = False
        assert state.tip_state == TipState.DETACHED


class TestSyringeCalibrationValidation:
    def test_both_omitted_is_valid(self) -> None:
        PipetteSyringeKinematics()  # must not raise

    def test_both_provided_is_valid(self) -> None:
        PipetteSyringeKinematics(
            calibration_volumes=[0.0, 100.0], calibration_steps=[0.0, 48.0]
        )  # must not raise

    def test_volumes_without_steps_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be provided together"):
            PipetteSyringeKinematics(calibration_volumes=[0.0, 100.0])

    def test_steps_without_volumes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be provided together"):
            PipetteSyringeKinematics(calibration_steps=[0.0, 48.0])

    def test_mismatched_lengths_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must have the same length"):
            PipetteSyringeKinematics(
                calibration_volumes=[0.0, 100.0, 200.0], calibration_steps=[0.0, 48.0]
            )

    def test_fewer_than_two_points_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 2 points"):
            PipetteSyringeKinematics(
                calibration_volumes=[100.0], calibration_steps=[48.0]
            )


class TestLiquidCalibrationValidation:
    def test_both_omitted_is_valid(self) -> None:
        LiquidProfile(name="water")  # must not raise

    def test_both_provided_is_valid(self) -> None:
        LiquidProfile(
            name="water",
            calibration_volumes=[0.0, 100.0],
            calibration_steps=[0.0, 48.0],
        )  # must not raise

    def test_volumes_without_steps_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be provided together"):
            LiquidProfile(name="water", calibration_volumes=[0.0, 100.0])

    def test_steps_without_volumes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be provided together"):
            LiquidProfile(name="water", calibration_steps=[0.0, 48.0])

    def test_mismatched_lengths_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must have the same length"):
            LiquidProfile(
                name="water",
                calibration_volumes=[0.0, 100.0, 200.0],
                calibration_steps=[0.0, 48.0],
            )

    def test_fewer_than_two_points_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 2 points"):
            LiquidProfile(
                name="water", calibration_volumes=[100.0], calibration_steps=[48.0]
            )
