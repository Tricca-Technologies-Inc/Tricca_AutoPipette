#!/usr/bin/env python3
"""Holds class and methods for running Tricca AutoPipette Shell."""
from cmd2 import Cmd, Cmd2ArgumentParser, with_argparser
import sys
from autopipette import AutoPipette
from pathlib import Path
from datetime import datetime
from plates import PlateTypes
from coordinate import Coordinate
from tap_cmd_parsers import TAPCmdParsers
from tap_web_utils import TAPWebUtils
from rich import print as rprint
from res.string_constants import TAP_CLR_BANNER
from rich.console import Console
from threaded_event_loop_manager import ThreadedEventLoopManager
import asyncio
from moonraker_requests import MoonrakerRequests
from tap_webcam import TAPWebcam


def main():
    """Entry point for the program."""
    argparser = Cmd2ArgumentParser()
    argparser.add_argument("ip", type=str,
                           help="ip address of the autopipette")
    argparser.add_argument("--conf", type=str, help="optional config file")
    args = argparser.parse_args()
    # Remove other processed parser commands to avoid cmd2 from using them
    sys.exit(TriccaAutoPipetteShell(conf_autopipette=args.conf,
                                    ip=args.ip).cmdloop())


class TriccaAutoPipetteShell(Cmd):
    """Terminal to control pipette."""

    # Prompt Variables
    intro = ""
    prompt: str = "autopipette >> "
    ip: str = ""
    webutils: TAPWebUtils = None
    alert_manager: ThreadedEventLoopManager = None
    alert_task = None
    console: Console = None
    mrr: MoonrakerRequests = None

    # Paths
    GCODE_PATH: Path = Path(__file__).parent.parent / 'gcode/'
    PROTOCOL_PATH: Path = Path(__file__).parent.parent / 'protocols/'

    # Gcode Variables
    _append_gcode: bool = False
    _gcode_buf: str = ""
    _autopipette: AutoPipette = None

    def __init__(self,
                 conf_autopipette: str = None,
                 ip: str = "0.0.0.0"):
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
        self.ip = ip
        self.debug = True
        self.console = Console()
        self.mrr = MoonrakerRequests()
        self.alert_manager = ThreadedEventLoopManager()
        self.alert_manager.start()
        # Delete set cmd bc we use our own
        delattr(Cmd, 'do_set')
        # Create some hooks to handle the starting and stopping of our thread
        self.register_preloop_hook(self._preloop_hook)
        self.register_postloop_hook(self._postloop_hook)

    def _preloop_hook(self) -> None:
        """Start the alerter thread."""
        # self.screen_printer = TAPScreenPrinter(self,
        #                                        self.need_prompt_refresh,
        #                                        self.async_refresh_prompt,
        #                                        self.terminal_lock)
        # self.screen_printer.refresh_screen()
        self.console.print("\033c", end="")
        self.console.print(TAP_CLR_BANNER)
        self.console.print("[green]Connecting to Pipette...[/]")
        self.webutils = TAPWebUtils(ip=self.ip)
        self.console.print("[green]Initializing Pipette...[/]")
        self.console.print("[green]Loading commands...[/]")
        # Example of how to load other commands
        # self.register_command_set(CommandSetPipette())

    def _postloop_hook(self) -> None:
        """Stop the alerter thread."""
        # self.screen_printer.close()
        self.alert_manager.stop()
        self.webutils.stop_websocket_listener()
        self.console.print("Exited gracefully.")

    def output_gcode(self, gcode: str, filename: str = None) -> None:
        """Direct gcode output."""
        if self._append_gcode:
            self._gcode_buf += gcode + "\n"
        else:
            now = datetime.now()
            if filename is None:
                filename = now.strftime("%Y-%m-%d-%H-%M-%S-%f.gcode")
            file_path = self.GCODE_PATH / "temp/" / filename
            with open(file_path, 'w') as file:
                file.write(gcode + "\n")
            self.webutils.exec_gcode_file(file_path, filename)
            # Delete temp file
            file_path.unlink()

    async def alerter_coroutine(self):
        """Coroutine for managing asynchronous alerts."""
        while True:
            if self.terminal_lock.acquire(blocking=False):
                # Process messages from the queue
                message = self.alert_manager.dequeue_message()
                if message:
                    self.async_alert(message)
                self.terminal_lock.release()
            await asyncio.sleep(0.5)  # Non-blocking sleep

    """--------------------------Commands Below-----------------------------"""
    @with_argparser(TAPCmdParsers.parser_home)
    def do_home(self, args):
        """Home a subset of motors on the pipette."""
        motors: str = args.motors
        filename: str = None
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
        elif motors == "servo":
            filename = "home_servo.gcode"
            self._autopipette.home_servo()
        else:
            filename = "home_all.gcode"
            self._autopipette.home_axis()
            self._autopipette.home_pipette_motors()
        self.output_gcode(self._autopipette.return_gcode(), filename)

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
            rprint(err_msg)
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
        aspirate: bool = args.aspirate
        keep_tip: bool = args.keep_tip
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
        if (self._autopipette.garbage is None):
            err_msg = \
                "No coordinate set as Garbage.\n"
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
                                  keep_tip, aspirate)
        self.output_gcode(f"\n; Pipette {vol_ul} from {src} to {dest}\n" +
                          self._autopipette.return_gcode() + "\n")

    @with_argparser(TAPCmdParsers.parser_move_loc)
    def do_move_loc(self, args):
        """Move to a location or a coordinate."""
        loc: str = args.name_loc
        # There should either be one arg (location) or 3 (coordinate)
        if (not self._autopipette.is_location(loc)):
            err_msg = \
                f"Arg:{loc} passed into move is not a location."
            rprint(err_msg)
        self._autopipette.move_to_loc(loc)
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

    def do_next_tip(self, _):
        """Pickup the next tip in the tip box."""
        # Check if there is a TipBox assigned to pipette
        if self._autopipette.tipboxes is None:
            err_msg = "No TipBox assigned to pipette."
            rprint(err_msg)
            return
        self._autopipette.next_tip()
        self.output_gcode(self._autopipette.return_gcode())

    def do_eject_tip(self, _):
        """Eject the tip on the pipette."""
        self._autopipette.eject_tip()
        self.output_gcode(self._autopipette.return_gcode())

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
        self.output_gcode(self._gcode_buf)
        self._gcode_buf = ""

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

    def do_start_alerts(self, _):
        """Start the alerter thread."""
        if self.alert_task and not self.alert_task.done():
            rprint("Alerts are already running.")
        else:
            self.alert_task = \
                self.alert_manager.submit_coroutine(self.alerter_coroutine())
            rprint("Alerts started.")

    def do_stop_alerts(self, _):
        """Stop the alerter thread."""
        if self.alert_task:
            self.alert_task.cancel()
            print("Alerts stopped.")

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
        self._autopipette._locations[plate].curr = 0

    def do_reset_plates(self, _):
        """Reset plates by setting the position on all plates to the origin."""
        for location in self._autopipette.get_plate_locations():
            self._autopipette._locations[location].curr = 0
        rprint("Plates Reset")

    def do_printer(self, _):
        """Print something to screen."""
        rprint("do_printer")
        self.alert_manager.enqueue_message("Queued message")

    @with_argparser(TAPCmdParsers.parser_vol_to_steps)
    def do_vol_to_steps(self, args):
        """Print the number of steps for a given volume."""
        vol = args.vol
        rprint(self._autopipette.volconv.vol_to_steps(vol))

    def do_break(self, _):
        """Prompts the user to continue.

        Useful for scripts.
        """
        self.select("Yes", "Continue?")

    def do_webcam(self, _):
        """Open a window with a webcam."""
        url: str = "http://" + self.ip + "/webcam/?action=stream"
        print(url)
        TAPWebcam().stream_webcam(url)

    def dip(self, coor):
        """Manage how far the pipette dips down."""
        total_dist = 0.0
        while True:
            user_input = self.read_input("How far to dip?: ")
            if user_input is None:
                return
            try:
                dist = float(user_input)
                if dist <= 0.0 or dist >= 25.0:
                    self.perror("Dip distance is too small or too large.")
                    continue
                total_dist += dist
                self._autopipette.dip_z_down(coor, dist)
                self.output_gcode(self._autopipette.return_gcode())
                self.poutput(f"Dipped {total_dist} so far.")
                dip_again = self.read_input("Dip again?(y/n): ")\
                                .strip().lower()
                dip_again = dip_again if dip_again else "n"
                if dip_again == "y":
                    continue
                else:
                    break
            except ValueError:
                self.perror("Not a valid number!")
        self._autopipette.dip_z_return(coor, total_dist)
        self.output_gcode(self._autopipette.return_gcode())

    def do_world_tour(self, _):
        """Go to every location."""
        while True:
            locs = self._autopipette._locations
            locs.append("stop")
            loc = self.select(locs, "Go to? ")
            if loc == "stop":
                break
            self._autopipette.move_to_loc(loc)
            self.output_gcode(self._autopipette.return_gcode())
            select = self.select("adjust dip next stop", "Which option? ")
            if select == "adjust":
                break
            elif select == "dip":
                self.dip(self._autopipette.get_location_coor(loc))
            elif select == "next":
                continue
            elif select == "stop":
                break
            else:
                break

    @with_argparser(TAPCmdParsers.parser_move_pip)
    def do_move_pip(self, args):
        """Move the pipette plunger."""
        dist = args.dist
        self._autopipette.move_pipette_stepper(dist)
        self.output_gcode(self._autopipette.return_gcode())


if __name__ == '__main__':
    main()
