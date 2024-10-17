#!/usr/bin/env python3
"""This file defines the how the .pipette protocol files work."""
# TODO Throw proper errors and log them
from AutoPipette import AutoPipette
from Plates import PlateTypes
from Coordinate import Coordinate


class ProtocolCommands:
    """Holds all command to gcode translations for the .pipette file format."""

    _autopipette = AutoPipette()
    _gcode_buf = ""

    def __init__(self, autopipette=AutoPipette()):
        """Initialize internal pipette object."""
        self._autopipette = autopipette

    def is_float(self, element: any) -> bool:
        """Return True element converts to a float and Flase otherwise."""
        if element is None:
            return False
        try:
            float(element)
            return True
        except ValueError:
            return False

    def init_file(self):
        """Initialize the gcode file with a header of pre-existing settings.

        Needs to be called before writing anything else to the file.
        """
        return self._autopipette.return_gcode()

    def set(self, args: str):
        """Set a variable on the pipette to a value."""
        _args = args.split()
        # args should contain a variable and a value
        if (not (len(_args) == 2)):
            err_msg = f"Wrong args:{_args} passed into set function."
            print(err_msg)
            return "; " + err_msg
        # Variable should exist in autopipette
        sections = self._autopipette.conf.keys()
        options = []
        pip_var = _args[0].upper()
        # TODO put limits on pip_val
        pip_val = int(_args[1])
        for section in sections:
            options += list(self._autopipette.conf[section].keys())
        options = list(map(str.upper, options))
        if (pip_var not in options):
            err_msg = \
                f"Variable {_args[0]} not recognized, it could not be set.\n"
            print(err_msg)
            return "; " + err_msg
        # 2nd arg speed should be a decimal.
        if (not (_args[1].isdecimal())):
            err_msg = \
                f"Second arg:{_args[1]} passed into set is not a decimal.\n"
            print(err_msg)
            return "; " + err_msg
        if (pip_var == "SPEED_FACTOR"):
            temp = self._autopipette.conf["SPEED"]["SPEED_FACTOR"]
            msg = f"; SPEED_FACTOR changed from {temp} to {pip_val}\n"
            self._autopipette.set_speed_factor(pip_val)
            return msg + self._autopipette.return_gcode()
        elif (pip_var == "VELOCITY_MAX"):
            temp = self._autopipette.conf["SPEED"]["VELOCITY_MAX"]
            msg = f"; MAX_VELOCITY changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_velocity(pip_val)
            return msg + self._autopipette.return_gcode()
        elif (pip_var == "ACCEL_MAX"):
            temp = self._autopipette.conf["SPEED"]["ACCEL_MAX"]
            msg = f"; MAX_ACCEL changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_accel(pip_val)
            return msg + self._autopipette.return_gcode()
        else:
            for section in sections:
                # If the variable we want to set is in that section,
                # set it and return
                if pip_var in self._autopipette.conf[section].keys():
                    temp = self._autopipette.conf[section][pip_var]
                    self._autopipette.conf[section][pip_var] = str(pip_val)
                    return f"; {pip_var} changed from {temp} to {pip_val}\n"
        err_msg = f"Unknown error setting {pip_var} to {pip_val}\n"
        print(err_msg)
        return "; " + err_msg

    def pipette(self, args: str):
        """Move vol amount of liquid from src to dest."""
        _args = args.split()
        # Should be 3 arguments
        arg_len = len(_args)
        if (not (arg_len == 3)):
            err_msg = \
                f"Wrong number of args:{arg_len} passed to pipette function.\n"
            print(err_msg)
            return "; " + err_msg
        # First arg should be a decimal
        if (not (_args[0].isdecimal())):
            err_msg = \
                f"First arg:{_args[0]} passed into pipette is not a decimal.\n"
            print(err_msg)
            return "; " + err_msg
        # 2nd and 3rd arg are coordinates vars or plate[0-7]
        vol_ul = float(_args[0])
        source = _args[1]
        dest = _args[2]
        if (not self._autopipette.is_location(source)):
            err_msg = \
                f"Source location:{source} does not exist.\n"
            print(err_msg)
            return "; " + err_msg
        if (not self._autopipette.is_location(dest)):
            err_msg = \
                f"Destination location:{dest} does not exist.\n"
            print(err_msg)
            return "; " + err_msg
        # Make sure there is a garbage for tips
        if (self._autopipette.garbage is None):
            err_msg = \
                "No coordinate set as Garbage.\n"
            print(err_msg)
            return "; " + err_msg
        # Make sure there is a tip box
        if (self._autopipette.tipboxes is None):
            err_msg = \
                "No coordinate set as TipBox.\n"
            print(err_msg)
            return "; " + err_msg
        self._autopipette.pipette(vol_ul, source, dest)
        return f"\n; Pipette {vol_ul} from {source} to {dest}\n" + \
            self._autopipette.return_gcode() + "\n"

    def gen_coordinate(self, args: str):
        """Generate a coordinate obj to refer to later."""
        _args = args.split()
        name_loc = _args[0]
        # If it is an existing location and the following arg isn't a number,
        # set a plate
        # Otherwise, set a coordinate.
        if (self._autopipette.is_location(name_loc) and
                (not _args[1].isdecimal())):
            plate_type = _args[1]
            # If plate type should exist
            if (plate_type not in PlateTypes.TYPES.keys()):
                err_msg = \
                    f"Plate type:{plate_type} does not exist.\n"
                print(err_msg)
                return "; " + err_msg
            # Check if num_row and num_col are passed in and call accordingly
            if (len(_args) == 2):
                self._autopipette.set_plate(name_loc, plate_type)
                return f"; Location:{name_loc} set to Plate:{plate_type}\n"
            elif (len(_args) == 4):
                # Next two args must be decimals
                if (not (_args[2].isdecimal() and _args[3].isdecimal())):
                    err_msg = f"""Arg 2:{_args[2]} and Arg 3:{_args[3]} are not decimals.\n"""
                    print(err_msg)
                    return "; " + err_msg
                num_row = int(_args[2])
                num_col = int(_args[3])
                self._autopipette.set_plate(name_loc, plate_type,
                                            num_row, num_col)
                return f"; Location:{name_loc} with rows:{num_row} cols:{num_col} set to Plate:{plate_type}\n"
            else:
                num_args = len(_args)
                err_msg = f"""Too many or too few args:{num_args} passed to gen_coordinate.\n"""
                print(err_msg)
                return "; " + err_msg
        else:
            # If the following 3 are decimals, set a location
            if (self.is_float(_args[1])
                    and self.is_float(_args[2])
                    and self.is_float(_args[3])):
                x = int(_args[1])
                y = int(_args[2])
                z = int(_args[3])
                self._autopipette.set_location(name_loc, x, y, z)
                return f"; Location:{name_loc} set to x:{x} y:{y} z:{z}\n"
            else:
                err_msg = f"""Arg 1:{_args[1]}, Arg 2:{_args[2]}, and Arg 3:{_args[3]} must be decimals\n"""
                print(err_msg)
                return "; " + err_msg

    def home(self, args: str):
        """Home a part of the pipette."""
        _args = args.split()
        # Should only be 1 arg
        if (not (len(_args) == 1)):
            err_msg = "Wrong args passed into home function.\n"
            print(err_msg)
            return "; " + err_msg
        if (_args[0] not in ["x", "y", "z", "axis", "all", "pipette"]):
            err_msg = \
                f"Arg:{_args[0]} passed into home function not recognized.\n"
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
            err_msg = \
                f"Arg:{_args[0]} passed into home function not recognized.\n"
            print(err_msg)
            return "; " + err_msg

        return self._autopipette.return_gcode()

    def move(self, args: str):
        """Move to a location or coordinate."""
        _args = args.split()
        # There should either be one arg (location) or 3 (coordinate)
        if (len(_args) == 1):
            # Check if passed location exists
            if (not self._autopipette.is_location(_args[0])):
                err_msg = \
                    f"Arg:{_args[0]} passed into move is not a location."
                print(err_msg)
                return "; " + err_msg
            coor = self._autopipette.get_location_coor(_args[0])
            self._autopipette.move_to(coor)
            return self._autopipette.return_gcode()
        elif (len(_args) == 3):
            # Check if args numbers
            if not (self.is_float(_args[0]) and
                    self.is_float(_args[1]) and
                    self.is_float(_args[2])):
                err_msg = \
                    f"Args:{_args} must all be numbers to be a coordinate."
                print(err_msg)
                return "; " + err_msg
            coor_x = float(_args[0])
            coor_y = float(_args[1])
            coor_z = float(_args[2])
            coor = Coordinate(coor_x, coor_y, coor_z)
            self._autopipette.move_to(coor)
            return self._autopipette.return_gcode()
        else:
            err_msg = \
                "Too many or too few args passed to move.\n"
            print(err_msg)
            return "; " + err_msg

    def next_tip(self, args: str):
        """Pickup the next tip in the tip box."""
        _args = args.split()
        # There should be no arguments passed in
        if len(_args) != 0:
            err_msg = "Function next_tip takes no args."
            print(err_msg)
            return "; " + err_msg
        # Check if there is a TipBox assigned to pipette
        if self._autopipette.tipboxes is None:
            err_msg = "No TipBox assigned to pipette."
            print(err_msg)
            return "; " + err_msg
        self._autopipette.next_tip()
        return self._autopipette.return_gcode()

    def eject_tip(self, args: str):
        """Eject the tip on the pipette."""
        _args = args.split()
        if len(_args) != 0:
            err_msg = "Function eject_tip takes no args."
            print(err_msg)
            return "; " + err_msg
        self._autopipette.eject_tip()
        return self._autopipette.return_gcode()

    _cmds = {
        "set": set,
        "coor": gen_coordinate,
        "home": home,
        "pipette": pipette,
        "move": move,
        "next_tip": next_tip,
        "eject_tip": eject_tip
    }

    def cmd_to_gcode(self, cmdline: str) -> str:
        """Convert a command into the appropriate gcode operations."""
        # print(cmdline)
        if (cmdline == "\n"):  # Copy newline lines to gcode file
            return "\n"
        # Split line into argumnts, 1st arg is a command
        line = cmdline.split(maxsplit=1)
        cmd = line[0]
        # Set args ot empty string if there's only a command
        if len(line) != 1:
            args = line[1]
        else:
            args = ""
        # If the first character is a semi-colon, the line is a comment.
        if (cmd[0] == ";"):
            return cmdline
        # Check if the cmd exists.
        if (cmd not in self._cmds):
            err_msg = f"Command {cmd} not found.\n"
            print(err_msg)
            return "; " + err_msg
        return self._cmds[cmd](self, args)
