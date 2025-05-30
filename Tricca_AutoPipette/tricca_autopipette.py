#!/usr/bin/env python3
"""Holds class and methods for running Tricca AutoPipette Shell."""
from cmd2 import Cmd, Cmd2ArgumentParser, with_argparser, plugin
import sys
from autopipette import AutoPipette, TipAlreadyOnError, NoTipboxError
from pathlib import Path
from datetime import datetime
from coordinate import Coordinate
from tap_cmd_parsers import TAPCmdParsers
from tap_web_utils import TAPWebUtils
from rich import print as rprint
from res.string_constants import TAP_CLR_BANNER
from rich.console import Console
from moonraker_requests import MoonrakerRequests
from plates import Plate, PlateFactory
from async_manager import AsyncManager
from concurrent.futures import Future
import queue


def main():
    """Entry point for the program."""
    argparser = Cmd2ArgumentParser()
    argparser.add_argument("--conf", type=str, help="optional config file")
    args = argparser.parse_args()
    # Remove other processed parser commands to avoid cmd2 from using them
    sys.exit(TriccaAutoPipetteShell(conf_autopipette=args.conf).cmdloop())


class TriccaAutoPipetteShell(Cmd):
    """Terminal to control pipette."""

    # Prompt Variables
    intro = ""
    prompt: str = "autopipette >> "
    hostname: str = ""
    webutils: TAPWebUtils = None
    console: Console = None
    mrr: MoonrakerRequests = None

    # Paths
    GCODE_PATH: Path = Path(__file__).parent.parent / 'gcode/'
    PROTOCOL_PATH: Path = Path(__file__).parent.parent / 'protocols/'

    def __init__(self,
                 conf_autopipette: str = None):
        """Initialize self, AutoPipette and ProtocolCommands objects."""
        super().__init__(allow_cli_args=False,
                         persistent_history_file=Path(__file__).parent
                         / '.tap_history',
                         startup_script=Path(__file__).parent
                         / '.init_pipette',
                         auto_load_commands=False)
        if conf_autopipette is None:
            self._autopipette = AutoPipette()
        else:
            self._autopipette = AutoPipette(conf_autopipette)
        if self._autopipette.config.has_option("NETWORK", "IP"):
            self.hostname = self._autopipette.config["NETWORK"]["IP"]
        else:
            self.hostname = self._autopipette.config["NETWORK"]["HOSTNAME"]
        self.debug = True
        self.console = Console()
        self.mrr = MoonrakerRequests()
        uri = "ws://" + self.hostname + ":7125/websocket"
        self.async_mgr = AsyncManager(uri)
        # Gcode Variables
        self._gcode_buffer: list[str] = []
        self._append_gcode: bool = False

        # Delete set cmd bc we use our own
        delattr(Cmd, 'do_set')
        # Create some hooks to handle the starting and stopping of our thread
        self.register_preloop_hook(self._preloop_hook)
        self.register_postloop_hook(self._postloop_hook)
        self.register_precmd_hook(self._precommand_hook)
        self.register_postcmd_hook(self._postcommand_hook)

    def _preloop_hook(self) -> None:
        """Print the banner."""
        # self.screen_printer = TAPScreenPrinter(self,
        #                                        self.need_prompt_refresh,
        #                                        self.async_refresh_prompt,
        #                                        self.terminal_lock)
        # self.screen_printer.refresh_screen()
        self.console.print("\033c", end="")
        self.console.print(TAP_CLR_BANNER)
        self.console.print("[green]Connecting to Pipette...[/]")
        self.webutils = TAPWebUtils(ip=self.hostname)
        self.console.print("[green]Initializing Pipette...[/]")
        self.console.print("[green]Loading commands...[/]")
        # Example of how to load other commands
        # self.register_command_set(CommandSetPipette())

    def _postloop_hook(self) -> None:
        """Stop other threads."""
        # self.screen_printer.close()
        self.poutput("Shutting down...")
        shutdown_future = self.async_mgr.schedule_shutdown()
        shutdown_future.result(timeout=5)
        self.console.print("Exited gracefully.")

    def _precommand_hook(self,
                         data: plugin.PrecommandData) -> plugin.PrecommandData:
        """Check commands before running.

        TODO find a way to label all moving commands so the below doesn't need
        to be updated
        """
        if data.statement.command not in ["pipette", "move", "move_loc",
                                          "move_rel", "next_tip", "run"]:
            return data
        if not self._autopipette.homed:
            rprint("[red]Pipette not homed. Run the 'home all' command.[/]")
            data.stop = True
        return data

    def _postcommand_hook(self,
                          data: plugin.PostcommandData
                          ) -> plugin.PostcommandData:
        """Process pending UI updates after each command."""
        while not self.async_mgr.callback_queue.empty():
            try:
                self.async_mgr.callback_queue.get_nowait()()
            except queue.Empty:
                break
        return data

    def _handle_response(self, future: Future, method: str):
        """Process async response in main thread."""
        def ui_callback():
            try:
                result = future.result()
                self.poutput(f"{method} result: {result}")
            except Exception as e:
                self.poutput(f"{method} error: {str(e)}")

        self.async_mgr.callback_queue.put(ui_callback)

    def output_gcode(self,
                     gcode: list[str],
                     filename: str = None,
                     append_header: bool = False) -> None:
        """Direct gcode output."""
        if self._append_gcode:
            self._gcode_buffer + gcode
            self._gcode_buffer.append("\n")
        else:
            now = datetime.now()
            if filename is None:
                filename = now.strftime("%Y-%m-%d-%H-%M-%S-%f.gcode")
            file_path = self.GCODE_PATH / "temp/" / filename
            with open(file_path, 'w') as file:
                if append_header:
                    header = self._autopipette.get_header()
                    for comment in header:
                        file.write(comment)
                for cmd in gcode:
                    file.write(cmd)
            self.webutils.exec_gcode_file(file_path, filename)
            # Delete temp file
            file_path.unlink()

    """--------------------------Commands Below-----------------------------"""
    def do_call(self, arg: str):
        """Call JSON-RPC method: call <method> [param1 param2 ...]."""
        if not arg:
            self.poutput("Usage: call <method> [params]")
            return

        parts = arg.split()
        method = parts[0]
        params = parts[1:]

        future = self.async_mgr.send_request(method, params)
        future.add_done_callback(lambda f: self._handle_response(f, method))

    @with_argparser(TAPCmdParsers.parser_home)
    def do_home(self, args):
        """Home a subset of motors on the pipette."""
        motors: str = args.motors
        filename: str = None
        if motors not in ["x", "y", "z", "pipette", "axis", "all", "servo"]:
            # TODO raise error
            rprint(f"{motors} is not a valid argument.")
            return
        if motors == "x":
            filename = "home_x.gcode"
            self._autopipette.home_x()
        elif motors == "y":
            filename = "home_y.gcode"
            self._autopipette.home_y()
        elif motors == "z":
            filename = "home_z.gcode"
            self._autopipette.home_z()
        elif motors == "pipette":
            filename = "home_pipette.gcode"
            self._autopipette.home_pipette_motors()
        elif motors == "axis":
            filename = "home_axis.gcode"
            self._autopipette.home_axis()
        elif motors == "all":
            filename = "home_all.gcode"
            self._autopipette.home_axis()
            self._autopipette.home_pipette_motors()
            self._autopipette.homed = True
        elif motors == "servo":
            filename = "home_servo.gcode"
            self._autopipette.home_servo()
        else:
            filename = "home_all.gcode"
            self._autopipette.home_axis()
            self._autopipette.home_pipette_motors()
        self.output_gcode(self._autopipette.get_gcode(), filename)

    @with_argparser(TAPCmdParsers.parser_set)
    def do_set(self, args):
        """Set a variable on the pipette to a value."""
        pip_var: str = args.pip_var
        pip_val: float = args.pip_val
        # Variable should exist in autopipette
        # TODO use pydantic properly here
        sections = self._autopipette.config.keys()
        options = []
        pip_var = pip_var.upper()
        # TODO put limits on pip_val
        for section in sections:
            options += list(self._autopipette.config[section].keys())
        options = list(map(str.upper, options))
        if (pip_var not in options):
            err_msg = \
                f"Variable {pip_var} not recognized, it could not be set.\n"
            rprint(err_msg)
            return
        if (pip_var == "SPEED_FACTOR"):
            temp = self._autopipette.config["SPEED"]["SPEED_FACTOR"]
            msg = f"; SPEED_FACTOR changed from {temp} to {pip_val}\n"
            self._autopipette.set_speed_factor(pip_val)
            self.output_gcode(self._autopipette.get_gcode().insert(0, msg))
        elif (pip_var == "VELOCITY_MAX"):
            temp = self._autopipette.config["SPEED"]["VELOCITY_MAX"]
            msg = f"; MAX_VELOCITY changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_velocity(pip_val)
            self.output_gcode(self._autopipette.get_gcode().insert(0, msg))
        elif (pip_var == "ACCEL_MAX"):
            temp = self._autopipette.config["SPEED"]["ACCEL_MAX"]
            msg = f"; MAX_ACCEL changed from {temp} to {pip_val}\n"
            self._autopipette.set_max_accel(pip_val)
            self.output_gcode(self._autopipette.get_gcode().insert(0, msg))
        else:
            for section in sections:
                # If the variable we want to set is in that section,
                # set it and return
                if pip_var in self._autopipette.config[section].keys():
                    temp = self._autopipette.config[section][pip_var]
                    self._autopipette.config[section][pip_var] = str(pip_val)
                    rprint(f"{pip_var} changed from {temp} to {pip_val}\n")

    @with_argparser(TAPCmdParsers.parser_coor)
    def do_coor(self, args):
        """Generate a coordinate obj to refer to later."""
        name_loc: str = args.name_loc
        x: float = args.x
        y: float = args.y
        z: float = args.z
        # If the following 3 are decimals, set a location
        self._autopipette.set_location(name_loc, x, y, z)
        self.output_gcode(
            [f"; Location:{name_loc} set to x:{x} y:{y} z:{z}\n"])

    @with_argparser(TAPCmdParsers.parser_plate)
    def do_plate(self, args):
        """Set a location to a plate."""
        name_loc: str = args.name_loc
        plate_type: str = args.plate_type
        row: int = args.row
        col: int = args.col
        if (self._autopipette.is_location(name_loc)):
            # If plate type should exist
            if (plate_type not in PlateFactory.registered()):
                err_msg = \
                    f"Plate type:{plate_type} does not exist.\n"
                rprint(err_msg)
        self._autopipette.set_plate(name_loc, plate_type,
                                    row, col)
        rprint(f"Location:{name_loc} with rows:{row} cols:{col} set to Plate:{plate_type}\n")

    @with_argparser(TAPCmdParsers.parser_pipette)
    def do_pipette(self, args):
        """Move an amount of liquid from soure to destination."""
        vol_ul: float = args.vol_ul
        src: str = args.src
        dest: str = args.dest
        prewet: bool = args.prewet
        keep_tip: bool = args.keep_tip
        wiggle: bool = args.wiggle
        src_row: int = args.src_row
        src_col: int = args.src_col
        dest_row: int = args.dest_row
        dest_col: int = args.dest_col
        if (not self._autopipette.is_location(src)):
            err_msg = \
                f"Source location:{src} does not exist.\n"
            rprint(err_msg)
            return
        if (not self._autopipette.is_location(dest)):
            err_msg = \
                f"Destination location:{dest} does not exist.\n"
            rprint(err_msg)
            return
        # Make sure there is a garbage for tips
        if (self._autopipette.waste_container is None):
            err_msg = \
                "No plate set as waste container.\n"
            rprint(err_msg)
            return
        # Make sure there is a tip box
        if (self._autopipette.tipboxes is None):
            err_msg = \
                "No coordinate set as TipBox.\n"
            rprint(err_msg)
            return
        self._autopipette.pipette(vol_ul, src, dest,
                                  src_row, src_col, dest_row, dest_col,
                                  keep_tip, prewet, wiggle)
        self.output_gcode([f"\n; Pipette {vol_ul} from {src} to {dest}\n"] +
                          self._autopipette.get_gcode() + ["\n"])

    @with_argparser(TAPCmdParsers.parser_move)
    def do_move(self, args):
        """Move to a coordinate."""
        x: float = args.x
        y: float = args.y
        z: float = args.z
        coor = Coordinate(x, y, z)
        self._autopipette.move_to(coor)
        self.output_gcode(self._autopipette.get_gcode())

    @with_argparser(TAPCmdParsers.parser_move_loc)
    def do_move_loc(self, args):
        """Move to a location or a coordinate."""
        loc: str = args.name_loc
        # There should either be one arg (location) or 3 (coordinate)
        if (not self._autopipette.is_location(loc)):
            err_msg = \
                f"Arg:{loc} passed into move is not a location."
            rprint(err_msg)
        coor = self._autopipette.get_location_coor(loc)
        print(coor)
        self._autopipette.move_to(coor)
        self.output_gcode(self._autopipette.get_gcode())

    @with_argparser(TAPCmdParsers.parser_move_rel)
    def do_move_rel(self, args):
        """Move relative to the current position."""
        x: float = args.x
        y: float = args.y
        z: float = args.z
        coor = Coordinate(x, y, z)
        self._autopipette.set_coor_sys("relative")
        self._autopipette.move_to(coor)
        self._autopipette.set_coor_sys("absolute")
        self.output_gcode(self._autopipette.get_gcode())

    def do_next_tip(self, _):
        """Pickup the next tip in the tip box."""
        # Check if there is a TipBox assigned to pipette
        try:
            self._autopipette.next_tip()
        except NoTipboxError as e:
            rprint(f"[yellow]{e}[/]")
        except TipAlreadyOnError as e:
            rprint(f"[yellow]{e}[/]")
        self.output_gcode(self._autopipette.get_gcode())

    def do_eject_tip(self, _):
        """Eject the tip on the pipette."""
        self._autopipette.eject_tip()
        self.output_gcode(self._autopipette.get_gcode())

    def do_print(self, _):
        """Print anything."""
        rprint("Print")

    @with_argparser(TAPCmdParsers.parser_run)
    def do_run(self, args):
        """Run a protocol."""
        filename: str = args.filename
        cmds = []
        file_path = self.PROTOCOL_PATH / filename
        if (not file_path.exists()):
            rprint(f"File: {file_path} does not exist")
            return
        with file_path.open("r") as fp:
            for line in fp:
                cmds.append(line)
        self._append_gcode = True
        self.runcmds_plus_hooks(cmds,
                                add_to_history=False,
                                stop_on_keyboard_interrupt=True)
        self._append_gcode = False
        self.output_gcode(self._gcode_buffer, filename, append_header=True)
        self._gcode_buffer = []

    def do_stop(self, args):
        """Send an emergency stop command to the pipette."""
        rprint("[bold red]Emergency Stop.[/]")
        self.webutils.append_to_send(
            self.mrr.gen_request("printer.emergency_stop"))

    def do_pause(self, args):
        """Pause an ongoing protocol."""
        rprint("Pause")
        self.webutils.append_to_send(
            self.mrr.gen_request("printer.print.pause"))

    def do_resume(self, args):
        """Resume an ongoing protocol."""
        rprint("Resume")
        self.webutils.append_to_send(
            self.mrr.gen_request("printer.print.resume"))

    def do_cancel(self, args):
        """Cancel an ongoing protocol."""
        rprint("Cancel")
        self.webutils.append_to_send(
            self.mrr.gen_request("printer.print.cancel"))

    def do_request(self, args):
        """Try a request."""
        pass

    def do_save(self, _):
        """Save the autopipette config."""
        self._autopipette.save_config_file()

    @with_argparser(TAPCmdParsers.parser_reset_plate)
    def do_reset_plate(self, args):
        """Reset a specific plate."""
        plate: str = args.plate
        if plate not in self._autopipette.get_plate_locations():
            rprint(f"Plate: {plate}, is not a plate.")
            return
        self._autopipette.locations[plate].curr = 0

    def do_reset_plates(self, _):
        """Reset plates by setting the position on all plates to the origin."""
        for location in self._autopipette.get_plate_locations():
            self._autopipette.locations[location].curr = 0
        rprint("Plates Reset")

    @with_argparser(TAPCmdParsers.parser_gcode_print)
    def do_gcode_print(self, args):
        """Send a gcode command to print something to the screen."""
        msg = args.msg
        rprint(msg)
        self._autopipette.gcode_print(msg)
        self.output_gcode(self._autopipette.get_gcode())

    @with_argparser(TAPCmdParsers.parser_vol_to_steps)
    def do_vol_to_steps(self, args):
        """Print the number of steps for a given volume."""
        vol = args.vol
        rprint(self._autopipette.volconv.vol_to_steps(vol))

    def do_break(self, _):
        """Prompts the user to continue.

        Useful for scripts.
        TODO make this generic
        """
        self.select("Yes", prompt="Continue?")

    def do_webcam(self, _):
        """Open a window with a webcam."""
        url: str = "http://" + self.hostname + "/webcam/?action=stream"
        print(url)
        # TAPWebcam().stream_webcam(url)

    def ls_locs(self):
        """Print all locations."""
        if not self._autopipette.locations:
            rprint("There are no set locations for the pipette.")
            return
        for loc_name in self._autopipette.locations.keys():
            rprint(f"{loc_name}")
            location = self._autopipette.locations[loc_name]
            if isinstance(location, Coordinate):
                key = f"COORDINATE {loc_name}"
            elif isinstance(location, Plate):
                key = f"PLATE {loc_name}"
            for loc_var in self._autopipette.config[key].keys():
                loc_val = self._autopipette.config[key][loc_var]
                rprint(f"\t{loc_var}: {loc_val}")

    def ls_plates(self):
        """Print all locations."""
        plates = self._autopipette.get_plate_locations()
        if not plates:
            rprint("There are no set plates for the pipette.")
            return
        for plate in plates:
            rprint(plate)
            for plate_var in self._autopipette.config[f"COORDINATE {plate}"].keys():
                plate_val = self._autopipette.config[f"COORDINATE {plate}"][plate_var]
                rprint(f"\t{plate_var}: {plate_val}")

    def ls_vars(self):
        """Print all locations."""
        sections_dict = {}
        sections_dict = self._autopipette.config
        filtered_dict = {
            key: value
            for key, value in sections_dict.items()
            if not key.startswith("COORDINATE")
        }
        del filtered_dict["VOLUME_CONV"]
        for section in filtered_dict.keys():
            rprint(section)
            for var_var in self._autopipette.config[section].keys():
                var_val = self._autopipette.config[section][var_var]
                rprint(f"\t{var_var}: {var_val}")

    def ls_conf(self):
        """Print the whole conf file."""
        for section in self._autopipette.config.keys():
            rprint(section)
            for key in self._autopipette.config[section].keys():
                val = self._autopipette.config[section][key]
                rprint(f"\t{key}: {val}")

    def ls_vol(self):
        """Print the volume conversion variables."""
        rprint("VOLUME_CONV")
        for vol_var in self._autopipette.config["VOLUME_CONV"].keys():
            vol_val = self._autopipette.config["VOLUME_CONV"][vol_var]
            rprint(f"\t{vol_var}: {vol_val}")

    @with_argparser(TAPCmdParsers.parser_ls)
    def do_ls(self, args):
        """List a variety of variables associated with the pipette.

        Options: locs, locations, plates, vars, conf, config, vol, volumes
        """
        var: str = args.var
        var.lower()
        if var in ["locs", "locations"]:
            self.ls_locs()
        elif var == "plates":
            self.ls_plates()
        elif var == "vars":
            self.ls_vars()
        elif var in ["conf", "config"]:
            self.ls_conf()
        elif var in ["vol", "volume"]:
            self.ls_vol()
        else:
            rprint(f"Unknown variable {var}. Couldn't list its properties.")

    @with_argparser(TAPCmdParsers.parser_load_conf)
    def do_load_conf(self, args):
        """Load a new configuration file."""
        filename: str = args.filename
        self._autopipette.load_config_file(filename)


if __name__ == '__main__':
    main()
