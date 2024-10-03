#!/usr/bin/env python3
"""This file defines the how the .pipette protocol files work."""
# TODO Throw proper errors and log them
from AutoPipette import AutoPipette
from decimal import Decimal


class ProtocolCommands:
    """Holds all possible commands and conversions in the .pipette file."""

    _autopipette = AutoPipette()
    _gcode_buf = ""

    def __init__(self, autopipette=AutoPipette()):
        """Initialize internal pipette object."""
        self._autopipette = autopipette

    def set(self, args: str):
        """Set a variable on the pipette to a value."""
        _args = args.split()
        # args should contain a variable and a value
        if (not (len(_args) == 2)):
            err_msg = f"Wrong args:{_args} passed into set function."
            print(err_msg)
            return "; " + err_msg
        # Variable should exist in autopipette
        if (_args[0] not in self._autopipette.vars):
            err_msg = f"Variable {_args[0]} not recognized, it could not be set.\n"
            print(err_msg)
            return "; " + err_msg
        # 2nd arg speed should be a decimal.
        if (not (_args[1].isdecimal())):
            err_msg = f"Second arg:{_args[1]} passed into set function is not a decimal.\n"
            print(err_msg)
            return "; " + err_msg
        pip_var = _args[0]
        # TODO put limits on pip_val
        pip_val = Decimal(_args[1])
        if (pip_var == "SPEED_FACTOR"):
            temp = self._autopipette.SPEED_FACTOR
            msg = f"; Autopipette SPEED_FACTOR changed from {temp} to {pip_val}\n"
            self._autopipette.set_speed_factor(pip_val)
            return msg + self._autopipette.return_gcode()
        elif (pip_var == "MAX_VELOCITY"):
            temp = self._autopipette.MAX_VELOCITY
            msg = f"; Autopipette MAX_VELOCITY changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_velocity(pip_val)
            return msg + self._autopipette.return_gcode()
        elif (pip_var == "MAX_ACCEL"):
            temp = self._autopipette.MAX_ACCEL
            msg = f"; Autopipette MAX_ACCEL changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_accel(pip_val)
            return msg + self._autopipette.return_gcode()
        else:
            temp = self._autopipette.vars[pip_var]
            self._autopipette.vars[pip_val] = pip_val
            return f"; AutoPipette {pip_var} changed from {temp} to {pip_val}\n"

    def pipette(self, args: str):
        """Move vol amount of liquid from src to dest."""
        _args = args.split()
        # Should be 3 arguments
        arg_len = len(_args)
        if (not (arg_len == 3)):
            err_msg = f"Wrong number of arguments:{arg_len} passed to pipette function.\n"
            print(err_msg)
            return "; " + err_msg
        # First arg should be a decimal
        if (not (_args[0].isdecimal())):
            err_msg = f"First arg:{_args[0]} passed into pipette is not a decimal.\n"
            print(err_msg)
            return "; " + err_msg
        # 2nd and 3rd arg are coordinates vars or plate[0-7]
        return "pipette\n"

    def gen_coordinate(self, args: str):
        """Generate a coordinate obj to refer to later."""
        return "coor\n"

    def home(self, args: str):
        """Home a part of the pipette."""
        _args = args.split()
        # Should only be 1 arg
        if (not (len(_args) == 1)):
            err_msg = "Wrong args passed into home function.\n"
            print(err_msg)
            return "; " + err_msg
        if (_args[0] not in ["x", "y", "z", "axis", "all", "pipette"]):
            err_msg = f"Arg:{_args[0]} passed into home function not recognized.\n"
        home_axis = _args[0]
        if (home_axis == "x"):
            self._autopipette.home_x()
        elif (home_axis == "y"):
            self._autopipette.home_y()
        elif (home_axis == "z"):
            self._autopipette.home_z()
        elif (home_axis == "axis"):
            self._autopipette.home_axis()
        elif (home_axis == "all"):
            self._autopipette.home_axis()
            self._autopipette.home_pipette_motors()
        elif (home_axis == "pipette"):
            self._autopipette.home_pipette_motors()
        else:
            err_msg = f"Arg:{_args[0]} passed into home function not recognized.\n"
            print(err_msg)
            return "; " + err_msg

        return self._autopipette.return_gcode()

    _cmds = {
        "set": set,
        "coor": gen_coordinate,
        "home": home,
        "pipette": pipette,
    }

    def cmd_to_gcode(self, cmdline: str) -> str:
        """Convert a command into the appropriate gcode operations."""
        # print(cmdline)
        if (cmdline == "\n"):  # Copy newline lines to gcode file
            return "\n"
        (cmd, args) = cmdline.split(maxsplit=1)
        # If the first character is a semi-colon, the line is a comment.
        if (cmd[0] == ";"):
            return cmdline
        # Check if the cmd exists.
        if (cmd not in self._cmds):
            err_msg = f"Command {cmd} not found.\n"
            print(err_msg)
            return "; " + err_msg
        return self._cmds[cmd](self, args)
