#!/usr/bin/env python3
r"""Typed builders for Klipper's documented built-in G-code commands.

Every G-code line this project sends to the machine is built here, the same
"pure builder, no I/O" shape as ``moonraker/moonraker_requests.py``'s
``MoonrakerRequests`` and ``daemon/control_requests.py``'s
``ControlRequests``: each method returns one newline-terminated line of
G-code and does nothing else.

Example:
    >>> gc = GCodeCommands()
    >>> gc.dwell(500)
    'G4 P500\n'
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Literal, NewType

#: One or more newline-terminated G-code lines. ``GCodeBuffer.add`` only
#: accepts this type, so a hand-built f-string next to a builder call is a
#: pyright error; the deliberate escape hatch is an explicit ``GCode(...)``
#: cast, visible at the call site.
GCode = NewType("GCode", str)

#: ``MANUAL_STEPPER``'s documented ``STOP_ON_ENDSTOP`` values. Klipper's
#: numeric aliases (``1`` = ``home``, ``-1`` = ``inverted_home``, ``2`` =
#: ``try_home``, ``-2`` = ``try_inverted_home``) are deliberately not
#: accepted: Klipper logs a deprecation warning on every numeric call
#: (``klippy/extras/manual_stepper.py``), and issue #29 moved every caller off
#: them.
StopOnEndstop = Literal[
    "probe",
    "home",
    "inverted_probe",
    "inverted_home",
    "try_probe",
    "try_inverted_probe",
    "try_home",
    "try_inverted_home",
]

ParamValue = str | float | bool | None


def _config_name(name: str) -> str:
    """Render a Klipper config name as exactly one parameter value.

    Klipper splits G-code into lines before parsing, then parses an
    extended command's parameters with posix ``shlex`` -- so a newline
    would inject a whole second G-code line, while a space (e.g.
    ``manual_stepper pipette_stepper``, the name ``STEPPER_BUZZ`` knows a
    manual stepper by) just needs shell quoting. ``shlex.quote`` leaves an
    ordinary name untouched, so existing emissions are unchanged.

    Args:
        name: The config name (stepper, servo, pin, LED, ...).

    Returns:
        ``name``, shell-quoted only if it needs to be.

    Raises:
        ValueError: If ``name`` is empty or contains a line break.
    """
    if not name or "\n" in name or "\r" in name:
        raise ValueError(
            f"Invalid Klipper config name {name!r}: must be non-empty, one line"
        )
    return shlex.quote(name)


def _line(command: str, **params: ParamValue) -> GCode:
    """Format ``COMMAND KEY=VALUE ...`` as one newline-terminated line.

    ``None`` parameters are omitted, booleans render as ``1``/``0``, and
    everything else via ``str()`` -- the same text the pre-builder f-strings
    produced, so existing emissions stay byte-identical.

    Args:
        command: The G-code command word.
        **params: Parameters in emission order; keys are emitted verbatim.

    Returns:
        The formatted G-code line.
    """
    parts = [command]
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = int(value)
        parts.append(f"{key}={value}")
    return GCode(" ".join(parts) + "\n")


def _template_params(
    params: Mapping[str, float | str] | None,
) -> dict[str, ParamValue]:
    """Prefix display-template parameters with ``PARAM_``.

    Klipper only passes ``PARAM_*`` parameters to a display template and
    silently drops the rest, so callers name them bare and this adds it.

    Args:
        params: Template parameters keyed by bare name, or ``None``.

    Returns:
        The same parameters keyed ``PARAM_<NAME>``.
    """
    return {f"PARAM_{key.upper()}": value for key, value in (params or {}).items()}


def _load_cell_line(command: str, load_cell: str | None) -> GCode:
    """Format a ``LOAD_CELL_*`` command with its optional ``LOAD_CELL=``.

    Args:
        command: The ``LOAD_CELL_*`` command word.
        load_cell: The load cell's config name, or ``None`` for the default.

    Returns:
        The formatted G-code line.
    """
    return _line(
        command, LOAD_CELL=None if load_cell is None else _config_name(load_cell)
    )


class GCodeCommands:
    r"""Pure builders for Klipper G-code, one method per command.

    Example:
        >>> gc = GCodeCommands()
        >>> gc.dwell(100)
        'G4 P100\n'
    """

    def dwell(self, milliseconds: float) -> GCode:
        r"""Build ``G4``: pause for a fixed time.

        Args:
            milliseconds: Duration to wait, in milliseconds.

        Returns:
            ``G4 P<milliseconds>``.

        Example:
            >>> GCodeCommands().dwell(850)
            'G4 P850\n'
        """
        return GCode(f"G4 P{milliseconds}\n")

    def display_message(self, message: str) -> GCode:
        r"""Build ``M117``: show a message on the controller display.

        Args:
            message: Text to display.

        Returns:
            ``M117 <message>``.

        Raises:
            ValueError: If ``message`` contains a newline, which would end
                the ``M117`` line early and run the rest as G-code.

        Example:
            >>> GCodeCommands().display_message("hello")
            'M117 hello\n'
        """
        if "\n" in message or "\r" in message:
            raise ValueError(f"M117 message must not contain a newline: {message!r}")
        return GCode(f"M117 {message}\n")

    def linear_move(
        self,
        *,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        feedrate: float | None = None,
    ) -> GCode:
        r"""Build ``G1``: a linear toolhead move.

        Omitted axes don't move. Whether ``x``/``y``/``z`` are absolute or
        relative depends on the last ``G90``/``G91``.

        Args:
            x: X target, in mm.
            y: Y target, in mm.
            z: Z target, in mm.
            feedrate: Move speed, in mm/**min** (G-code's ``F`` unit).

        Returns:
            ``G1 [X<x>] [Y<y>] [Z<z>] [F<feedrate>]``.

        Example:
            >>> GCodeCommands().linear_move(z=5.0, feedrate=600)
            'G1 Z5.0 F600\n'
        """
        words = [
            f"{letter}{value}"
            for letter, value in (("X", x), ("Y", y), ("Z", z), ("F", feedrate))
            if value is not None
        ]
        return GCode(" ".join(["G1", *words]) + "\n")

    def absolute_mode(self) -> GCode:
        r"""Build ``G90``: interpret subsequent coordinates as absolute.

        Returns:
            ``G90``.

        Example:
            >>> GCodeCommands().absolute_mode()
            'G90\n'
        """
        return GCode("G90\n")

    def relative_mode(self) -> GCode:
        r"""Build ``G91``: interpret subsequent coordinates as offsets.

        Returns:
            ``G91``.

        Example:
            >>> GCodeCommands().relative_mode()
            'G91\n'
        """
        return GCode("G91\n")

    def home(self, *axes: Literal["X", "Y", "Z"]) -> GCode:
        r"""Build ``G28``: home the given gantry axes, or all of them.

        Args:
            *axes: Axes to home; none means all.

        Returns:
            ``G28 [X] [Y] [Z]``.

        Example:
            >>> GCodeCommands().home()
            'G28\n'
            >>> GCodeCommands().home("X")
            'G28 X\n'
        """
        return GCode(" ".join(["G28", *axes]) + "\n")

    def speed_factor(self, percent: float) -> GCode:
        r"""Build ``M220``: override the speed factor.

        Args:
            percent: Speed override percentage (100 = normal).

        Returns:
            ``M220 S<percent>``.

        Example:
            >>> GCodeCommands().speed_factor(100)
            'M220 S100\n'
        """
        return GCode(f"M220 S{percent}\n")

    def set_velocity_limit(
        self,
        *,
        velocity: float | None = None,
        accel: float | None = None,
        square_corner_velocity: float | None = None,
        minimum_cruise_ratio: float | None = None,
    ) -> GCode:
        r"""Build ``SET_VELOCITY_LIMIT``: change the toolhead's motion limits.

        Parameter names follow Klipper's ``toolhead.py``
        (``VELOCITY``/``ACCEL``), not ``[printer]``'s config keys.

        Args:
            velocity: Max velocity, in mm/s.
            accel: Max acceleration, in mm/s².
            square_corner_velocity: Max 90° corner velocity, in mm/s.
            minimum_cruise_ratio: Fraction of a move spent cruising (0-1).

        Returns:
            The ``SET_VELOCITY_LIMIT`` line.

        Example:
            >>> GCodeCommands().set_velocity_limit(velocity=300)
            'SET_VELOCITY_LIMIT VELOCITY=300\n'
        """
        return _line(
            "SET_VELOCITY_LIMIT",
            VELOCITY=velocity,
            ACCEL=accel,
            SQUARE_CORNER_VELOCITY=square_corner_velocity,
            MINIMUM_CRUISE_RATIO=minimum_cruise_ratio,
        )

    def wait_for_moves(self) -> GCode:
        r"""Build ``M400``: wait for all queued moves to finish.

        Returns:
            ``M400``.

        Example:
            >>> GCodeCommands().wait_for_moves()
            'M400\n'
        """
        return GCode("M400\n")

    def motors_off(self) -> GCode:
        r"""Build ``M84``: disable all steppers (``M18`` is Klipper's alias).

        Returns:
            ``M84``.

        Example:
            >>> GCodeCommands().motors_off()
            'M84\n'
        """
        return GCode("M84\n")

    def query_endstops(self) -> GCode:
        r"""Build ``QUERY_ENDSTOPS``: report every endstop's state.

        Klipper's docs mark ``M119`` as the deprecated spelling of this.

        Returns:
            ``QUERY_ENDSTOPS``.

        Example:
            >>> GCodeCommands().query_endstops()
            'QUERY_ENDSTOPS\n'
        """
        return GCode("QUERY_ENDSTOPS\n")

    # ------------------------------------------------------------------
    # Servo and output pins
    # ------------------------------------------------------------------

    def set_servo(self, servo: str, angle: float) -> GCode:
        r"""Build ``SET_SERVO``: move a ``[servo]`` to an angle.

        The angle range belongs to that servo's config; Klipper enforces it.

        Args:
            servo: The ``[servo <name>]`` config name.
            angle: Target angle, in degrees.

        Returns:
            ``SET_SERVO SERVO=<servo> ANGLE=<angle>``.

        Example:
            >>> GCodeCommands().set_servo("pipette_servo", 130)
            'SET_SERVO SERVO=pipette_servo ANGLE=130\n'
        """
        return _line("SET_SERVO", SERVO=_config_name(servo), ANGLE=angle)

    def set_pin(
        self, pin: str, value: float, *, cycle_time: float | None = None
    ) -> GCode:
        r"""Build ``SET_PIN``: drive an ``[output_pin]`` to a value.

        Args:
            pin: The ``[output_pin <name>]`` config name.
            value: Output value (0/1 for digital, 0-``scale`` for PWM).
            cycle_time: PWM cycle time in seconds; only valid for pins
                configured with ``pwm: True``.

        Returns:
            ``SET_PIN PIN=<pin> VALUE=<value> [CYCLE_TIME=<cycle_time>]``.

        Example:
            >>> GCodeCommands().set_pin("air", 1)
            'SET_PIN PIN=air VALUE=1\n'
        """
        return _line(
            "SET_PIN", PIN=_config_name(pin), VALUE=value, CYCLE_TIME=cycle_time
        )

    def set_pin_template(
        self,
        pin: str,
        template: str,
        params: Mapping[str, float | str] | None = None,
    ) -> GCode:
        r"""Build ``SET_PIN ... TEMPLATE=``: drive a pin from a display template.

        Args:
            pin: The ``[output_pin <name>]`` config name.
            template: The ``[display_template <name>]`` to assign; ``""``
                clears any assigned template.
            params: Template parameters, keyed *without* the ``PARAM_``
                prefix (added here -- Klipper silently ignores unprefixed
                ones). Values are Python literals, so a string value must
                carry its own quotes.

        Returns:
            The ``SET_PIN`` line.

        Example:
            >>> GCodeCommands().set_pin_template("air", "pulse", {"duty": 0.5})
            'SET_PIN PIN=air TEMPLATE=pulse PARAM_DUTY=0.5\n'
        """
        return _line(
            "SET_PIN",
            PIN=_config_name(pin),
            TEMPLATE=template,
            **_template_params(params),
        )

    # ------------------------------------------------------------------
    # LEDs and fans
    # ------------------------------------------------------------------

    def set_led(
        self,
        led: str,
        *,
        red: float | None = None,
        green: float | None = None,
        blue: float | None = None,
        white: float | None = None,
        index: int | None = None,
        transmit: bool | None = None,
        sync: bool | None = None,
    ) -> GCode:
        r"""Build ``SET_LED``: set an LED (chain)'s colour.

        Omitted colour channels default to 0 in Klipper.

        Args:
            led: The LED's config name (``[neopixel <name>]`` etc.).
            red: Red level, 0.0-1.0.
            green: Green level, 0.0-1.0.
            blue: Blue level, 0.0-1.0.
            white: White level, 0.0-1.0 (RGBW LEDs only).
            index: 1-based chip in a daisy chain; ``None`` sets them all.
            transmit: ``False`` to defer the update to the next ``SET_LED``.
            sync: ``False`` to apply immediately without resetting the
                idle timeout.

        Returns:
            The ``SET_LED`` line.

        Example:
            >>> GCodeCommands().set_led("status", red=1, green=0, blue=0)
            'SET_LED LED=status RED=1 GREEN=0 BLUE=0\n'
        """
        return _line(
            "SET_LED",
            LED=_config_name(led),
            RED=red,
            GREEN=green,
            BLUE=blue,
            WHITE=white,
            INDEX=index,
            TRANSMIT=transmit,
            SYNC=sync,
        )

    def set_led_template(
        self,
        led: str,
        template: str,
        params: Mapping[str, float | str] | None = None,
        *,
        index: int | None = None,
    ) -> GCode:
        r"""Build ``SET_LED_TEMPLATE``: drive an LED from a display template.

        Args:
            led: The LED's config name.
            template: The ``[display_template <name>]`` to assign; ``""``
                clears it.
            params: Template parameters, keyed without the ``PARAM_``
                prefix (see ``set_pin_template``).
            index: 1-based chip in a daisy chain; ``None`` sets them all.

        Returns:
            The ``SET_LED_TEMPLATE`` line.

        Example:
            >>> GCodeCommands().set_led_template("status", "glow")
            'SET_LED_TEMPLATE LED=status TEMPLATE=glow\n'
        """
        return _line(
            "SET_LED_TEMPLATE",
            LED=_config_name(led),
            TEMPLATE=template,
            **_template_params(params),
            INDEX=index,
        )

    def set_fan_speed(self, fan: str, speed: float) -> GCode:
        r"""Build ``SET_FAN_SPEED``: set a ``[fan_generic]``'s speed.

        Not ``M106``/``M107``, which drive a 3D printer's part-cooling fan
        -- a concept this machine doesn't have.

        Args:
            fan: The ``[fan_generic <name>]`` config name.
            speed: Fan speed, 0.0-1.0.

        Returns:
            ``SET_FAN_SPEED FAN=<fan> SPEED=<speed>``.

        Example:
            >>> GCodeCommands().set_fan_speed("enclosure", 0.5)
            'SET_FAN_SPEED FAN=enclosure SPEED=0.5\n'
        """
        return _line("SET_FAN_SPEED", FAN=_config_name(fan), SPEED=speed)

    def set_fan_speed_template(
        self,
        fan: str,
        template: str,
        params: Mapping[str, float | str] | None = None,
    ) -> GCode:
        r"""Build ``SET_FAN_SPEED ... TEMPLATE=``: drive a fan from a template.

        Args:
            fan: The ``[fan_generic <name>]`` config name.
            template: The ``[display_template <name>]`` to assign; ``""``
                clears it.
            params: Template parameters, keyed without the ``PARAM_``
                prefix (see ``set_pin_template``).

        Returns:
            The ``SET_FAN_SPEED`` line.

        Example:
            >>> GCodeCommands().set_fan_speed_template("enclosure", "")
            'SET_FAN_SPEED FAN=enclosure TEMPLATE=\n'
        """
        return _line(
            "SET_FAN_SPEED",
            FAN=_config_name(fan),
            TEMPLATE=template,
            **_template_params(params),
        )

    def set_temperature_fan_target(
        self,
        temperature_fan: str,
        *,
        target: float | None = None,
        min_speed: float | None = None,
        max_speed: float | None = None,
    ) -> GCode:
        r"""Build ``SET_TEMPERATURE_FAN_TARGET``: retarget a temperature fan.

        Args:
            temperature_fan: The ``[temperature_fan <name>]`` config name.
            target: Target temperature, in °C; ``None`` restores the
                config's value.
            min_speed: Minimum fan speed, 0.0-1.0.
            max_speed: Maximum fan speed, 0.0-1.0.

        Returns:
            The ``SET_TEMPERATURE_FAN_TARGET`` line.

        Example:
            >>> GCodeCommands().set_temperature_fan_target("chamber", target=30)
            'SET_TEMPERATURE_FAN_TARGET TEMPERATURE_FAN=chamber TARGET=30\n'
        """
        return _line(
            "SET_TEMPERATURE_FAN_TARGET",
            TEMPERATURE_FAN=_config_name(temperature_fan),
            TARGET=target,
            MIN_SPEED=min_speed,
            MAX_SPEED=max_speed,
        )

    # ------------------------------------------------------------------
    # Sensors: load cell, ADC
    # ------------------------------------------------------------------

    def load_cell_diagnostic(self, load_cell: str | None = None) -> GCode:
        r"""Build ``LOAD_CELL_DIAGNOSTIC``: report load-cell sample health.

        Args:
            load_cell: The ``[load_cell <name>]`` config name; ``None`` for
                the default (unnamed) load cell.

        Returns:
            ``LOAD_CELL_DIAGNOSTIC [LOAD_CELL=<load_cell>]``.

        Example:
            >>> GCodeCommands().load_cell_diagnostic()
            'LOAD_CELL_DIAGNOSTIC\n'
        """
        return _load_cell_line("LOAD_CELL_DIAGNOSTIC", load_cell)

    def load_cell_calibrate(self, load_cell: str | None = None) -> GCode:
        r"""Build ``LOAD_CELL_CALIBRATE``: start guided load-cell calibration.

        Args:
            load_cell: The ``[load_cell <name>]`` config name; ``None`` for
                the default load cell.

        Returns:
            ``LOAD_CELL_CALIBRATE [LOAD_CELL=<load_cell>]``.

        Example:
            >>> GCodeCommands().load_cell_calibrate("tip")
            'LOAD_CELL_CALIBRATE LOAD_CELL=tip\n'
        """
        return _load_cell_line("LOAD_CELL_CALIBRATE", load_cell)

    def load_cell_tare(self, load_cell: str | None = None) -> GCode:
        r"""Build ``LOAD_CELL_TARE``: zero the load cell at its current load.

        Args:
            load_cell: The ``[load_cell <name>]`` config name; ``None`` for
                the default load cell.

        Returns:
            ``LOAD_CELL_TARE [LOAD_CELL=<load_cell>]``.

        Example:
            >>> GCodeCommands().load_cell_tare()
            'LOAD_CELL_TARE\n'
        """
        return _load_cell_line("LOAD_CELL_TARE", load_cell)

    def load_cell_read(self, load_cell: str | None = None) -> GCode:
        r"""Build ``LOAD_CELL_READ``: report the current load.

        Args:
            load_cell: The ``[load_cell <name>]`` config name; ``None`` for
                the default load cell.

        Returns:
            ``LOAD_CELL_READ [LOAD_CELL=<load_cell>]``.

        Example:
            >>> GCodeCommands().load_cell_read()
            'LOAD_CELL_READ\n'
        """
        return _load_cell_line("LOAD_CELL_READ", load_cell)

    def load_cell_test_tap(
        self, *, taps: int | None = None, timeout: float | None = None
    ) -> GCode:
        r"""Build ``LOAD_CELL_TEST_TAP``: wait for test taps on the load cell.

        Args:
            taps: Number of taps to wait for.
            timeout: Seconds to wait for each tap.

        Returns:
            ``LOAD_CELL_TEST_TAP [TAPS=<taps>] [TIMEOUT=<timeout>]``.

        Example:
            >>> GCodeCommands().load_cell_test_tap(taps=3)
            'LOAD_CELL_TEST_TAP TAPS=3\n'
        """
        return _line("LOAD_CELL_TEST_TAP", TAPS=taps, TIMEOUT=timeout)

    def query_adc(
        self, name: str | None = None, *, pullup: float | None = None
    ) -> GCode:
        r"""Build ``QUERY_ADC``: report an analog input's last value.

        Args:
            name: The ADC's config name; ``None`` lists the available ones.
            pullup: Pullup resistance, in ohms, to also report the
                equivalent resistance.

        Returns:
            ``QUERY_ADC [NAME=<name>] [PULLUP=<pullup>]``.

        Example:
            >>> GCodeCommands().query_adc()
            'QUERY_ADC\n'
        """
        return _line(
            "QUERY_ADC",
            NAME=None if name is None else _config_name(name),
            PULLUP=pullup,
        )

    # ------------------------------------------------------------------
    # Manual stepper
    # ------------------------------------------------------------------

    def manual_stepper(
        self,
        stepper: str,
        *,
        enable: bool | None = None,
        set_position: float | None = None,
        move: float | None = None,
        speed: float | None = None,
        accel: float | None = None,
        stop_on_endstop: StopOnEndstop | None = None,
        sync: bool | None = None,
    ) -> GCode:
        r"""Build ``MANUAL_STEPPER``: drive a ``[manual_stepper]`` directly.

        Covers both documented forms -- the plain move and the endstop-
        checked homing move (``STOP_ON_ENDSTOP``). Klipper itself rejects
        ``STOP_ON_ENDSTOP`` without ``MOVE`` and out-of-range positions,
        so neither is re-checked here. Parameters are emitted in a fixed
        order (``ENABLE SET_POSITION MOVE SPEED ACCEL STOP_ON_ENDSTOP
        SYNC``); Klipper parses them by name, so order is cosmetic.

        Args:
            stepper: The ``[manual_stepper <name>]`` config name.
            enable: Enable (``True``) or disable (``False``) the stepper.
            set_position: Declare the current position, in mm.
            move: Target position, in mm.
            speed: Move speed, in mm/s.
            accel: Move acceleration, in mm/s².
            stop_on_endstop: Stop early on endstop trigger (see
                ``StopOnEndstop``).
            sync: ``False`` to not wait for the move before the next one.

        Returns:
            The ``MANUAL_STEPPER`` line.

        Example:
            >>> GCodeCommands().manual_stepper("s", set_position=0)
            'MANUAL_STEPPER STEPPER=s SET_POSITION=0\n'
        """
        return _line(
            "MANUAL_STEPPER",
            STEPPER=_config_name(stepper),
            ENABLE=enable,
            SET_POSITION=set_position,
            MOVE=move,
            SPEED=speed,
            ACCEL=accel,
            STOP_ON_ENDSTOP=stop_on_endstop,
            SYNC=sync,
        )

    def manual_stepper_gcode_axis(
        self,
        stepper: str,
        axis: str | None,
        *,
        limit_velocity: float | None = None,
        limit_accel: float | None = None,
        instantaneous_corner_velocity: float | None = None,
    ) -> GCode:
        r"""Build ``MANUAL_STEPPER ... GCODE_AXIS=``: bind a stepper to a G1 axis.

        Once bound, ``G1 <axis>...`` moves the stepper along with the
        toolhead. Klipper validates the axis letter itself.

        Args:
            stepper: The ``[manual_stepper <name>]`` config name.
            axis: Axis letter to register, or ``None`` to unregister.
            limit_velocity: Max velocity along that axis, in mm/s.
            limit_accel: Max acceleration along that axis, in mm/s².
            instantaneous_corner_velocity: Max instantaneous velocity
                change at a corner, in mm/s.

        Returns:
            The ``MANUAL_STEPPER`` line.

        Example:
            >>> GCodeCommands().manual_stepper_gcode_axis("s", None)
            'MANUAL_STEPPER STEPPER=s GCODE_AXIS=\n'
        """
        return _line(
            "MANUAL_STEPPER",
            STEPPER=_config_name(stepper),
            GCODE_AXIS=axis or "",
            LIMIT_VELOCITY=limit_velocity,
            LIMIT_ACCEL=limit_accel,
            INSTANTANEOUS_CORNER_VELOCITY=instantaneous_corner_velocity,
        )

    def stepper_buzz(self, stepper: str) -> GCode:
        r"""Build ``STEPPER_BUZZ``: oscillate a stepper to verify wiring.

        Args:
            stepper: The stepper's full config section name (e.g.
                ``stepper_x``, or ``manual_stepper pipette_stepper`` --
                quoted automatically).

        Returns:
            ``STEPPER_BUZZ STEPPER=<stepper>``.

        Example:
            >>> GCodeCommands().stepper_buzz("stepper_x")
            'STEPPER_BUZZ STEPPER=stepper_x\n'
        """
        return _line("STEPPER_BUZZ", STEPPER=_config_name(stepper))
