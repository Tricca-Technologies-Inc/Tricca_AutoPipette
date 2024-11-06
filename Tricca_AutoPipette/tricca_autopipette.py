#!/usr/bin/env python3
"""Holds class and methods for running Tricca AutoPipette Shell."""
import requests
from cmd2 import Cmd, Cmd2ArgumentParser, with_argparser
import sys
from autopipette import AutoPipette
from pathlib import Path
from datetime import datetime
from plates import PlateTypes
from coordinate import Coordinate
from tap_cmd_parsers import TAPCmdParsers


def main():
    """Entry point for the program."""
    argparser = Cmd2ArgumentParser()
    argparser.add_argument("ip", type=str,
                           help="ip address of the autopipette")
    args = argparser.parse_args()
    # Remove other processed parser commands to avoid cmd2 from using them
    sys.exit(TriccaAutoPipetteShell(ip=args.ip).cmdloop())


class TriccaAutoPipetteShell(Cmd):
    """Terminal to control pipette."""

    intro = r"""
 ______    _                 _       _       ___ _           _   _
/_  __/___(_)__________ _   /_\ _  _| |_ ___| _ (_)_ __  ___| |_| |_ ___
 / / / __/ / __/ __/ _ `/  / _ \ || |  _/ _ \  _/ | '_ \/ -_)  _|  _/ -_)
/_/ /_/ /_/\__/\__/\_,_/  /_/ \_\_,_|\__\___/_| |_| .__/\___|\__|\__\___|
                                                  |_|
"""
    prompt: str = "autopipette >> "
    _autopipette: AutoPipette = None
    GCODE_PATH: Path = Path(__file__).parent.parent / 'gcode/'
    PROTOCOL_PATH: Path = Path(__file__).parent.parent / 'protocols/'
    ip: str = ""
    _append_gcode: bool = False
    _gcode_buf: str = ""

    def __init__(self,
                 autopipette: AutoPipette = AutoPipette(),
                 ip: str = "0.0.0.0"):
        """Initialize self, AutoPipette and ProtocolCommands objects."""
        super().__init__(allow_cli_args=False,
                         persistent_history_file='.tap_shell_history',
                         startup_script='.init_pipette',
                         auto_load_commands=False)
        self.ip = ip
        self._autopipette = autopipette
        self.debug = True
        delattr(Cmd, 'do_set')

    def preloop(self):
        """Execute before entering main loop."""
        self.poutput("Loading commands...")
        # Example of how to load other commands
        # self.register_command_set(CommandSetPipette())
        self.poutput("Initializing Pipette...")
        self.init_pipette()

    def output_gcode(self, gcode: str):
        """Direct gcode output."""
        if self._append_gcode:
            self._gcode_buf += gcode + "\n"
        else:
            now = datetime.now()
            filename = now.strftime("%Y-%m-%d-%H-%M-%S-%f.gcode")
            file_path = self.GCODE_PATH / "temp/" / filename
            with open(file_path, 'w') as file:
                file.write(gcode + "\n")
            self.send_gcode_file(file_path)
            # Delete temp file
            file_path.unlink()

    def send_gcode_cmd(self, cmd: str):
        """Send a line of gcode to the pipette.

        Args:
            cmd (str): The cmd to send to the pipette.
        """
        response = requests.post(
            "http://" + self.ip + ":7125/printer/gcode/script",
            json={"script": cmd})
        if response.status_code == 200:
            # print("Command sent successfully")
            pass
        else:
            print(f"Failed to send command: \
                {response.status_code}, {response.text}")

    def send_gcode_file(self, file_path: str):
        """Send a gcode file and execute it.

        Args:
            file_path (str): File to upload to the pipette.
        """
        # Set the base URL of your Moonraker server
        base_url = 'http://' + self.ip + ':7125'

        # Step 1: Upload the File
        upload_url = f'{base_url}/server/files/upload'
        with open(file_path, 'rb') as file:
            files = {'file': ('myfile.gcode', file, 'application/octet-stream')}
            upload_response = requests.post(upload_url, files=files)

            if upload_response.status_code != 201:
                self.poutput(f"File upload failed or unexpected response: \
                {upload_response.text}, \
                Upload Code{upload_response.status_code}")

            uploaded_file_path = upload_response.json()['item']['path']
            # Step 2: Start the Print
            print_url = \
                f'{base_url}/printer/print/start?filename={uploaded_file_path}'
            print_response = requests.post(print_url)
            # Check if print started successfully
            if print_response.status_code == 200:
                pass
            else:
                self.poutput(f"Failed to start print:{print_response.text}")

    def init_pipette(self):
        """Initialize the pipette."""
        self.output_gcode(self._autopipette.return_header())

    @with_argparser(TAPCmdParsers.parser_home)
    def do_home(self, args):
        """Home a subset of motors on the pipette."""
        motors: str = args.motors
        if motors == "x":
            self._autopipette.home_x()
        elif motors == "y":
            self._autopipette.home_y()
        elif motors == "z":
            self._autopipette.home_z()
        elif motors == "pipette":
            self._autopipette.home_pipette_motors()
        elif motors == "axis":
            self._autopipette.home_axis()
        elif motors == "all":
            self._autopipette.home_axis()
            self._autopipette.home_pipette_motors()
        elif motors == "servo":
            self._autopipette.home_servo()
        else:
            self._autopipette.home_axis()
            self._autopipette.home_pipette_motors()
        self.output_gcode(self._autopipette.return_gcode())

    @with_argparser(TAPCmdParsers.parser_set)
    def do_set(self, args):
        """Set a variable on the pipette to a value."""
        pip_var: str = args.pip_var
        pip_val: float = args.pip_val
        # Variable should exist in autopipette
        sections = self._autopipette.conf.keys()
        options = []
        pip_var = pip_var.upper()
        # TODO put limits on pip_val
        for section in sections:
            options += list(self._autopipette.conf[section].keys())
        options = list(map(str.upper, options))
        if (pip_var not in options):
            err_msg = \
                f"Variable {pip_var} not recognized, it could not be set.\n"
            self.poutput(err_msg)
            return
        if (pip_var == "SPEED_FACTOR"):
            temp = self._autopipette.conf["SPEED"]["SPEED_FACTOR"]
            msg = f"; SPEED_FACTOR changed from {temp} to {pip_val}\n"
            self._autopipette.set_speed_factor(pip_val)
            self.output_gcode(msg + self._autopipette.return_gcode())
        elif (pip_var == "VELOCITY_MAX"):
            temp = self._autopipette.conf["SPEED"]["VELOCITY_MAX"]
            msg = f"; MAX_VELOCITY changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_velocity(pip_val)
            self.output_gcode(msg + self._autopipette.return_gcode())
        elif (pip_var == "ACCEL_MAX"):
            temp = self._autopipette.conf["SPEED"]["ACCEL_MAX"]
            msg = f"; MAX_ACCEL changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_accel(pip_val)
            self.output_gcode(msg + self._autopipette.return_gcode())
        else:
            for section in sections:
                # If the variable we want to set is in that section,
                # set it and return
                if pip_var in self._autopipette.conf[section].keys():
                    temp = self._autopipette.conf[section][pip_var]
                    self._autopipette.conf[section][pip_var] = str(pip_val)
                    self.poutput(
                        f"{pip_var} changed from {temp} to {pip_val}\n")

    @with_argparser(TAPCmdParsers.parser_coor)
    def do_coor(self, args):
        """Generate a coordinate obj to refer to later."""
        name_loc: str = args.name_loc
        x: float = args.x
        y: float = args.y
        z: float = args.z
        # If the following 3 are decimals, set a location
        self._autopipette.set_location(name_loc, x, y, z)
        self.output_gcode(f"; Location:{name_loc} set to x:{x} y:{y} z:{z}\n")

    @with_argparser(TAPCmdParsers.parser_plate)
    def do_plate(self, args):
        """Set a location to a plate."""
        name_loc: str = args.name_loc
        plate_type: str = args.plate_type
        row: int = args.row
        col: int = args.col
        if (self._autopipette.is_location(name_loc)):
            # If plate type should exist
            if (plate_type not in PlateTypes.TYPES.keys()):
                err_msg = \
                    f"Plate type:{plate_type} does not exist.\n"
                self.poutput(err_msg)
        self._autopipette.set_plate(name_loc, plate_type,
                                    row, col)
        self.poutput(f"Location:{name_loc} with rows:{row} cols:{col} set to Plate:{plate_type}\n")

    @with_argparser(TAPCmdParsers.parser_pipette)
    def do_pipette(self, args):
        """Move an amount of liquid from soure to destination."""
        vol_ul: float = args.vol_ul
        src: str = args.src
        dest: str = args.dest
        aspirate: bool = args.aspirate
        keep_tip: bool = args.keep_tip
        src_row: int = args.src_row
        src_col: int = args.src_col
        dest_row: int = args.dest_row
        dest_col: int = args.dest_col
        if (not self._autopipette.is_location(src)):
            err_msg = \
                f"Source location:{src} does not exist.\n"
            self.poutput(err_msg)
            return
        if (not self._autopipette.is_location(dest)):
            err_msg = \
                f"Destination location:{dest} does not exist.\n"
            self.poutput(err_msg)
            return
        # Make sure there is a garbage for tips
        if (self._autopipette.garbage is None):
            err_msg = \
                "No coordinate set as Garbage.\n"
            self.poutput(err_msg)
            return
        # Make sure there is a tip box
        if (self._autopipette.tipboxes is None):
            err_msg = \
                "No coordinate set as TipBox.\n"
            self.poutput(err_msg)
            return
        self._autopipette.pipette(vol_ul, src, dest,
                                  src_row, src_col, dest_row, dest_col,
                                  keep_tip, aspirate)
        self.output_gcode(f"\n; Pipette {vol_ul} from {src} to {dest}\n" +
                          self._autopipette.return_gcode() + "\n")

    @with_argparser(TAPCmdParsers.parser_move_loc)
    def do_move_loc(self, args):
        """Move to a location or a coordinate."""
        loc: str = args.loc
        # There should either be one arg (location) or 3 (coordinate)
        if (not self._autopipette.is_location(loc)):
            err_msg = \
                f"Arg:{loc} passed into move is not a location."
            self.poutput(err_msg)
        coor = self._autopipette.get_location_coor(loc)
        self._autopipette.move_to(coor)
        self.output_gcode(self._autopipette.return_gcode())

    @with_argparser(TAPCmdParsers.parser_move)
    def do_move(self, args):
        """Move to a coordinate."""
        x: float = args.x
        y: float = args.y
        z: float = args.z
        coor = Coordinate(x, y, z)
        self._autopipette.move_to(coor)
        self.output_gcode(self._autopipette.return_gcode())

    def do_next_tip(self):
        """Pickup the next tip in the tip box."""
        # Check if there is a TipBox assigned to pipette
        if self._autopipette.tipboxes is None:
            err_msg = "No TipBox assigned to pipette."
            self.poutput(err_msg)
            return
        self._autopipette.next_tip()
        self.output_gcode(self._autopipette.return_gcode())

    def do_eject_tip(self):
        """Eject the tip on the pipette."""
        self._autopipette.eject_tip()
        self.output_gcode(self._autopipette.return_gcode())

    def do_print(self):
        """Print anythong."""
        self.poutput("Print")

    @with_argparser(TAPCmdParsers.parser_run)
    def do_run(self, args):
        """Run a protocol."""
        filename: str = args.filename
        cmds = []
        file_path = self.PROTOCOL_PATH / filename
        if (not file_path.exists()):
            self.poutput(f"File: {file_path} does not exist")
            return
        with file_path.open("r") as fp:
            for line in fp:
                cmds.append(line)
        self._append_gcode = True
        self.runcmds_plus_hooks(cmds,
                                add_to_history=False,
                                stop_on_keyboard_interrupt=True)
        self._append_gcode = False
        self.output_gcode(self._gcode_buf)
        self._gcode_buf = ""

    def do_stop(self):
        """Send an emergency stop command to the pipette.

        Can also use Ctrl-Z.
        """
        MOONRAKER_API_URL = \
            "http://" + self.ip + ":7125/printer/emergency_stop"
        payload = {
            "jsonrpc": "2.0",
            "method": "printer.emergency_stop",
            "id": 4564
        }
        try:
            response = requests.post(MOONRAKER_API_URL, json=payload)
            response.raise_for_status()
            self.poutput("Emergency stop sent.")
        except requests.RequestException as e:
            print(f"Failed to send emergency stop: {e}")


if __name__ == '__main__':
    main()
