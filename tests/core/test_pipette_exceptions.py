"""Unit tests for ``core/pipette_exceptions.py``: message/attribute shape."""

from __future__ import annotations

from tricca_autopipette.core.pipette_exceptions import (
    AutoPipetteError,
    MissingConfigError,
    NotADipStrategyError,
    NotALocationError,
    NotHomedError,
    NoTipboxError,
    NoWasteContainerError,
    OutOfTipsError,
    ProtocolAbortedError,
    TipAlreadyOnError,
    VolumeCapacityError,
)


class TestBaseException:
    def test_is_a_plain_exception(self) -> None:
        assert issubclass(AutoPipetteError, Exception)


class TestTipAlreadyOnError:
    def test_message(self) -> None:
        err = TipAlreadyOnError()
        assert str(err) == "Tip already attached. Eject current tip first."
        assert isinstance(err, AutoPipetteError)


class TestNotALocationError:
    def test_message_and_attribute(self) -> None:
        err = NotALocationError("bench")
        assert err.location == "bench"
        assert str(err) == "bench is not a named location."


class TestNoTipboxError:
    def test_message(self) -> None:
        assert str(NoTipboxError()) == "No tipbox configured."


class TestOutOfTipsError:
    def test_message_names_the_checked_boxes(self) -> None:
        err = OutOfTipsError(["box_a", "box_b"])
        assert err.boxes == ["box_a", "box_b"]
        assert str(err) == (
            "No tips remaining in box_a, box_b. Reload and run reset_tips."
        )

    def test_message_falls_back_when_no_boxes_configured(self) -> None:
        err = OutOfTipsError([])
        assert str(err) == (
            "No tips remaining in any configured tipbox. Reload and run reset_tips."
        )


class TestMissingConfigError:
    def test_message_and_attributes(self) -> None:
        err = MissingConfigError("SPEED", "/path/to/config.conf")
        assert err.section == "SPEED"
        assert err.conf_path == "/path/to/config.conf"
        assert str(err) == "Missing section 'SPEED' in config: /path/to/config.conf"


class TestNotADipStrategyError:
    def test_message_with_valid_strategies(self) -> None:
        err = NotADipStrategyError("invalid", ["simple", "cylinder"])
        assert err.strategy == "invalid"
        assert err.valid_strategies == ["simple", "cylinder"]
        assert str(err) == (
            "Invalid dip strategy 'invalid'. Valid options: ['simple', 'cylinder']"
        )

    def test_message_without_valid_strategies(self) -> None:
        err = NotADipStrategyError("invalid")
        assert err.valid_strategies is None
        assert str(err) == "Invalid dip strategy 'invalid'."

    def test_message_with_empty_valid_strategies_list(self) -> None:
        """An empty list is falsy, same code path as None."""
        err = NotADipStrategyError("invalid", [])
        assert str(err) == "Invalid dip strategy 'invalid'."


class TestNoWasteContainerError:
    def test_message(self) -> None:
        assert str(NoWasteContainerError()) == "No waste container configured."


class TestVolumeCapacityError:
    def test_message_and_attributes(self) -> None:
        err = VolumeCapacityError(150.0, 98.0)
        assert err.volume_ul == 150.0  # ruff:ignore[float-equality-comparison]
        assert err.usable_ul == 98.0  # ruff:ignore[float-equality-comparison]
        assert str(err) == (
            "Cannot aspirate 150.0 μL: exceeds usable syringe capacity of 98.0 μL."
        )


class TestProtocolAbortedError:
    def test_is_an_autopipette_error(self) -> None:
        assert issubclass(ProtocolAbortedError, AutoPipetteError)

    def test_can_carry_a_custom_message(self) -> None:
        assert str(ProtocolAbortedError("user aborted")) == "user aborted"


class TestNotHomedError:
    def test_message_and_attribute(self) -> None:
        err = NotHomedError("move")
        assert err.command_name == "move"
        assert str(err) == (
            "Command 'move' blocked — pipette not homed. "
            "Run 'init' or 'home all' first."
        )
