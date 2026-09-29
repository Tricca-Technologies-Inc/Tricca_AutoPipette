"""Unit tests for ``core/gcode_commands.py``'s ``GCodeCommands``.

Expected strings are literals taken from Klipper's G-code reference
(https://www.klipper3d.org/G-Codes.html) and, for commands already emitted
before issue #30, from the exact text the old hand-built f-strings produced.
"""

from __future__ import annotations

import pytest

from tricca_autopipette.core.gcode_commands import GCodeCommands

gc = GCodeCommands()


class TestStandardGCode:
    def test_dwell(self) -> None:
        assert gc.dwell(850) == "G4 P850\n"


class TestManualStepper:
    def test_homing_move(self) -> None:
        line = gc.manual_stepper(
            "pipette_stepper",
            set_position=0,
            move=499.5,
            speed=200.0,
            accel=800.0,
            stop_on_endstop="home",
        )

        assert line == (
            "MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0 "
            "MOVE=499.5 SPEED=200.0 ACCEL=800.0 STOP_ON_ENDSTOP=home\n"
        )

    def test_string_form_stop_on_endstop(self) -> None:
        line = gc.manual_stepper("s", move=-3.0, stop_on_endstop="try_inverted_home")

        assert (
            line == "MANUAL_STEPPER STEPPER=s MOVE=-3.0 "
            "STOP_ON_ENDSTOP=try_inverted_home\n"
        )

    def test_omitted_parameters_are_not_emitted(self) -> None:
        assert gc.manual_stepper("s", set_position=0) == (
            "MANUAL_STEPPER STEPPER=s SET_POSITION=0\n"
        )

    def test_enable_and_sync_render_as_zero_or_one(self) -> None:
        assert gc.manual_stepper("s", enable=False, move=1, sync=False) == (
            "MANUAL_STEPPER STEPPER=s ENABLE=0 MOVE=1 SYNC=0\n"
        )

    def test_gcode_axis_registers_an_axis(self) -> None:
        line = gc.manual_stepper_gcode_axis(
            "s", "A", limit_velocity=50, limit_accel=100
        )

        assert line == (
            "MANUAL_STEPPER STEPPER=s GCODE_AXIS=A LIMIT_VELOCITY=50 LIMIT_ACCEL=100\n"
        )

    def test_gcode_axis_none_unregisters(self) -> None:
        assert gc.manual_stepper_gcode_axis("s", None) == (
            "MANUAL_STEPPER STEPPER=s GCODE_AXIS=\n"
        )

    def test_stepper_buzz(self) -> None:
        assert gc.stepper_buzz("s") == "STEPPER_BUZZ STEPPER=s\n"


class TestSingleLineGuarantee:
    @pytest.mark.parametrize("name", ["a\nG28", "a\rG28", ""])
    def test_empty_or_multiline_config_name_is_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="config name"):
            gc.manual_stepper(name, set_position=0)

    def test_config_name_with_a_space_is_shell_quoted(self) -> None:
        # Klipper parses extended-command parameters with posix shlex, and
        # force_move registers a manual stepper under its full section name.
        assert gc.stepper_buzz("manual_stepper pipette_stepper") == (
            "STEPPER_BUZZ STEPPER='manual_stepper pipette_stepper'\n"
        )

    def test_display_message_with_newline_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="newline"):
            gc.display_message("hi\nG28")


class TestMotionAndModes:
    def test_linear_move_xy(self) -> None:
        assert gc.linear_move(x=100.0, y=100.0, feedrate=38000.0) == (
            "G1 X100.0 Y100.0 F38000.0\n"
        )

    def test_linear_move_z_only(self) -> None:
        assert gc.linear_move(z=5.0, feedrate=12000.0) == "G1 Z5.0 F12000.0\n"

    def test_absolute_and_relative_mode(self) -> None:
        assert gc.absolute_mode() == "G90\n"
        assert gc.relative_mode() == "G91\n"

    def test_home_all(self) -> None:
        assert gc.home() == "G28\n"

    def test_home_single_axis(self) -> None:
        assert gc.home("Z") == "G28 Z\n"

    def test_home_several_axes(self) -> None:
        assert gc.home("X", "Y") == "G28 X Y\n"

    def test_speed_factor(self) -> None:
        assert gc.speed_factor(150) == "M220 S150\n"

    def test_set_velocity_limit_velocity_only(self) -> None:
        assert gc.set_velocity_limit(velocity=5000) == (
            "SET_VELOCITY_LIMIT VELOCITY=5000\n"
        )

    def test_set_velocity_limit_accel_only(self) -> None:
        assert gc.set_velocity_limit(accel=40000.0) == (
            "SET_VELOCITY_LIMIT ACCEL=40000.0\n"
        )

    def test_set_velocity_limit_all_fields(self) -> None:
        line = gc.set_velocity_limit(
            velocity=300,
            accel=3000,
            square_corner_velocity=5,
            minimum_cruise_ratio=0.5,
        )

        assert line == (
            "SET_VELOCITY_LIMIT VELOCITY=300 ACCEL=3000 "
            "SQUARE_CORNER_VELOCITY=5 MINIMUM_CRUISE_RATIO=0.5\n"
        )

    def test_set_servo(self) -> None:
        assert gc.set_servo("pipette_servo", 100) == (
            "SET_SERVO SERVO=pipette_servo ANGLE=100\n"
        )

    def test_wait_for_moves(self) -> None:
        assert gc.wait_for_moves() == "M400\n"

    def test_motors_off(self) -> None:
        assert gc.motors_off() == "M84\n"

    def test_query_endstops(self) -> None:
        assert gc.query_endstops() == "QUERY_ENDSTOPS\n"


class TestPinsLedsFans:
    def test_set_pin_value(self) -> None:
        assert gc.set_pin("air", 1) == "SET_PIN PIN=air VALUE=1\n"

    def test_set_pin_value_with_cycle_time(self) -> None:
        assert gc.set_pin("air", 0.5, cycle_time=0.01) == (
            "SET_PIN PIN=air VALUE=0.5 CYCLE_TIME=0.01\n"
        )

    def test_set_pin_template_prefixes_template_params(self) -> None:
        # Klipper silently ignores template parameters not named PARAM_*.
        assert gc.set_pin_template("air", "pulse", {"duty": 0.25}) == (
            "SET_PIN PIN=air TEMPLATE=pulse PARAM_DUTY=0.25\n"
        )

    def test_set_pin_template_empty_name_clears_template(self) -> None:
        assert gc.set_pin_template("air", "") == "SET_PIN PIN=air TEMPLATE=\n"

    def test_set_led(self) -> None:
        line = gc.set_led(
            "status", red=1, green=0.5, blue=0, index=2, transmit=False, sync=False
        )

        assert line == (
            "SET_LED LED=status RED=1 GREEN=0.5 BLUE=0 INDEX=2 TRANSMIT=0 SYNC=0\n"
        )

    def test_set_led_rgbw(self) -> None:
        assert gc.set_led("status", red=0, green=0, blue=0, white=1) == (
            "SET_LED LED=status RED=0 GREEN=0 BLUE=0 WHITE=1\n"
        )

    def test_set_led_template(self) -> None:
        assert gc.set_led_template("status", "glow", {"level": 2}, index=1) == (
            "SET_LED_TEMPLATE LED=status TEMPLATE=glow PARAM_LEVEL=2 INDEX=1\n"
        )

    def test_set_fan_speed(self) -> None:
        assert gc.set_fan_speed("enclosure", 0.8) == (
            "SET_FAN_SPEED FAN=enclosure SPEED=0.8\n"
        )

    def test_set_fan_speed_template(self) -> None:
        assert gc.set_fan_speed_template("enclosure", "ramp") == (
            "SET_FAN_SPEED FAN=enclosure TEMPLATE=ramp\n"
        )

    def test_set_temperature_fan_target(self) -> None:
        line = gc.set_temperature_fan_target("chamber", target=30, max_speed=0.9)

        assert line == (
            "SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET=30 "
            "MAX_SPEED=0.9\n"
        )


class TestSensors:
    def test_load_cell_commands_without_a_name(self) -> None:
        assert gc.load_cell_diagnostic() == "LOAD_CELL_DIAGNOSTIC\n"
        assert gc.load_cell_calibrate() == "LOAD_CELL_CALIBRATE\n"
        assert gc.load_cell_tare() == "LOAD_CELL_TARE\n"
        assert gc.load_cell_read() == "LOAD_CELL_READ\n"

    def test_load_cell_commands_with_a_name(self) -> None:
        assert gc.load_cell_tare("tip_sensor") == (
            "LOAD_CELL_TARE LOAD_CELL=tip_sensor\n"
        )
        assert gc.load_cell_read("tip_sensor") == (
            "LOAD_CELL_READ LOAD_CELL=tip_sensor\n"
        )

    def test_load_cell_test_tap(self) -> None:
        assert gc.load_cell_test_tap(taps=3, timeout=30) == (
            "LOAD_CELL_TEST_TAP TAPS=3 TIMEOUT=30\n"
        )

    def test_query_adc(self) -> None:
        assert gc.query_adc() == "QUERY_ADC\n"
        assert gc.query_adc("thermistor", pullup=4700) == (
            "QUERY_ADC NAME=thermistor PULLUP=4700\n"
        )
