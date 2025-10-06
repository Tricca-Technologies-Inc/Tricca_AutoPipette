#!/usr/bin/env python3
"""Holds class and methods for running Tricca AutoPipette Shell."""
from cmd2 import Cmd, with_argparser, plugin, Statement
from autopipette import AutoPipette, TipAlreadyOnError, NoTipboxError
from pathlib import Path, PosixPath
from datetime import datetime
from coordinate import Coordinate
from tap_cmd_parsers import TAPCmdParsers
from rich import print as rprint
from res.string_constants import TAP_CLR_BANNER
from rich.console import Console
from rich.text import Text
from moonraker_requests import MoonrakerRequests
from plates import Plate, PlateFactory
from websocketclient import WebSocketClient
from typing import Any, Dict, Optional
import logging
import threading
import json

logger = logging.getLogger(__name__)


class TriccaAutoPipetteShell(Cmd):
    """Terminal to control pipette."""

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
        # Prompt Variables
        self.intro = ""
        self.prompt: str = "autopipette >> "
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
        # Web Objects
        self.mrr = MoonrakerRequests()
        self.uri = "ws://" + self.hostname + "/websocket"
        self.client = WebSocketClient(self.uri)
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
        self.client.start()
        connected = self.client._connected.wait(timeout=10)
        if not connected or not self.client.ws or self.client.ws.closed:
            self.perror("Failed to connect to WebSocket.")
            self.prompt = "autopipette (disconnected) >> "
        self.console.print("[green]Initializing Pipette...[/]")
        self.console.print("[green]Loading commands...[/]")
        # Example of how to load other commands
        # self.register_command_set(CommandSetPipette())

    def _postloop_hook(self) -> None:
        """Stop other threads."""
        # self.screen_printer.close()
        self.poutput("Shutting down...")
        self.poutput("Closing WebSocket client...")
        self.client.stop()
        self.poutput("WebSocket client closed.")
        self.poutput("Exited.")
        return True

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
        """Ran after a command."""
        return data

    def send_rpc(self, payload: Optional[Dict[str, Any]]) -> None:
        """Send a Json RPC request."""
        def worker():
            try:
                response = self.client.send_jsonrpc(payload)
                with self.terminal_lock:
                    self.async_alert(f"Response: {response}")
            except json.JSONDecodeError as jde:
                self.perror(f"JSON decode error in params: {jde}")
            except Exception as e:
                self.perror(f"Error: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def upload_gcode(self, filename: str, file_path: PosixPath) -> None:
        """Upload a gcode file to the pipette."""
        def worker():
            future = self.client.upload_gcode_file(filename, file_path)
            try:
                server_path = future.result(timeout=30)
                with self.terminal_lock:
                    self.async_alert(
                        f"Upload successful. Server path: {server_path}")
                self.poutput(f"Upload successful. Server path: {server_path}")
            except Exception as e:
                self.perror(f"Upload failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def upload_and_execute_gcode(self,
                                 filename: str,
                                 file_path: PosixPath,
                                 delete_file: bool = False) -> None:
        """Upload and start a gcode job."""
        def worker():
            future = self.client.upload_gcode_file(filename, file_path)
            try:
                server_path = future.result(timeout=30)
                with self.terminal_lock:
                    self.async_alert(f"Upload successful. Server path: {server_path}")
                self.send_rpc(self.mrr.printer_print_start(filename))
                if delete_file:
                    file_path.unlink()
            except Exception as e:
                self.perror(f"Upload failed: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def output_gcode(self,
                     gcode: list[str],
                     filename: str = None,
                     append_header: bool = False) -> None:
        """Direct gcode output."""
        if self._append_gcode:
            self._gcode_buffer.extend(gcode)
            self._gcode_buffer.append("\n")
            return
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
            self.upload_and_execute_gcode(filename,
                                          file_path,
                                          delete_file=True)

    """--------------------------Commands Below-----------------------------"""
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
        rprint(f"Location:{name_loc} with rows:{row} cols:{col} "
               f"set to Plate:{plate_type}\n")

    @with_argparser(TAPCmdParsers.parser_pipette)
    def do_pipette(self, args):
        """Move an amount of liquid from source to destination (supports --splits)."""
        vol_ul: float = args.vol_ul
        src: str = args.src
        dest: str = args.dest
        prewet: bool = args.prewet
        disp_vol = args.disp_vol_ul
        keep_tip: bool = args.keep_tip
        wiggle: bool = args.wiggle
        src_row: int = args.src_row
        src_col: int = args.src_col
        dest_row: int = args.dest_row
        dest_col: int = args.dest_col
        splits_spec: str | None = args.splits
        leftover_action: str = args.leftover  # "keep" or "waste"
        tipbox_name: str = args.tipbox_name

        # Validate source
        if not self._autopipette.is_location(src):
            rprint(f"Source location:{src} does not exist.\n")
            return

        # Validate dest if we're doing the classic single-dispense path
        if not splits_spec and not self._autopipette.is_location(dest):
            rprint(f"Destination location:{dest} does not exist.\n")
            return

        # Validate tip/waste infrastructure (same as old behavior)
        if self._autopipette.waste_container is None:
            rprint("No plate set as waste container.\n")
            return
        try:
            # ensure there is a usable tipbox (named or pooled)
            self._autopipette._resolve_tipbox(tipbox_name)
        except Exception as e:
            rprint(f"{e}\n")
            return

        # If splits are provided, validate each split destination exists
        if splits_spec:
            try:
                split_list = self._autopipette._parse_splits_spec(splits_spec)
            except Exception as e:
                rprint(f"Invalid --splits: {e}\n")
                return
            for s in split_list:
                if not self._autopipette.is_location(s.dest):
                    rprint(f"Split destination '{s.dest}' does not exist.\n")
                    return
            # Also check the total split volume vs aspirate
            total_split = sum(s.vol_ul for s in split_list)
            if total_split - vol_ul > 1e-6:
                rprint(f"Split volumes ({total_split} uL) exceed aspirate ({vol_ul} uL).\n")
                return

        # Build the G-code using the same call pattern as before
        self._autopipette.pipette(
            vol_ul, src, dest, disp_vol,
            src_row, src_col, dest_row, dest_col,
            keep_tip, prewet, wiggle,
            splits=splits_spec,
            leftover_action=leftover_action,
            tipbox_name=tipbox_name,
        )

        # IMPORTANT: send exactly like the old version (simple header, ASCII only)
        self.output_gcode(
            [f"\n; Pipette {vol_ul} from {src} to {dest}\n"]
            + self._autopipette.get_gcode()
            + ["\n"]
        )

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
        self._autopipette.dispose_tip()
        self.output_gcode(self._autopipette.get_gcode())

    def do_trigger(self, arg: str):
        """trigger <channel> <on|off>"""
        try:
            parts = arg.split()
            if len(parts) != 2:
                self.perror("Usage: trigger <air|shake|aux> <on|off>")
                return

            channel, state = parts
            self._autopipette.set_trigger(channel, state)
            self.output_gcode(self._autopipette.get_gcode())
        except Exception as e:
            self.perror(f"Trigger error: {e}")


    def do_print(self, _):
        """Print anything."""
        rprint("Print")

    @with_argparser(TAPCmdParsers.parser_run)
    def do_run(self, args):
        filename = args.filename
        proto = self.PROTOCOL_PATH / filename
        if not proto.exists():
            rprint(f"File not found: {proto}")
            return

        lines = proto.read_text().splitlines()
        self._append_gcode = True
        self.runcmds_plus_hooks([ln + "\n" for ln in lines],
                                add_to_history=False,
                                stop_on_keyboard_interrupt=True)
        self._append_gcode = False

        # now write & upload
        self.output_gcode(self._gcode_buffer,
                        Path(filename).with_suffix('.gcode').name,
                        append_header=True)
        self._gcode_buffer = []


    def do_stop(self, args):
        """Send an emergency stop command to the pipette."""
        rprint("[bold red]Emergency Stop.[/]")
        # self.webutils.append_to_send(
        #     self.mrr.gen_request("printer.emergency_stop"))

    def do_pause(self, args):
        """Pause an ongoing protocol."""
        rprint("Pause")
        # self.webutils.append_to_send(
        #     self.mrr.gen_request("printer.print.pause"))

    def do_resume(self, args):
        """Resume an ongoing protocol."""
        rprint("Resume")
        # self.webutils.append_to_send(
        #     self.mrr.gen_request("printer.print.resume"))

    def do_cancel(self, args):
        """Cancel an ongoing protocol."""
        rprint("Cancel")
        # self.webutils.append_to_send(
        #     self.mrr.gen_request("printer.print.cancel"))

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
        rprint(self._autopipette.volume_converter.vol_to_steps(vol))

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
                plate_val = \
                    self._autopipette.config[f"COORDINATE {plate}"][plate_var]
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

    """------------------------WebSocket Cmds-------------------------------"""

    @with_argparser(TAPCmdParsers.parser_send)
    def do_send(self, args) -> None:
        """Run a JSON-RPC request in background and display the response."""

    @with_argparser(TAPCmdParsers.parser_notify)
    def do_notify(self, args) -> None:
        """Run a JSON-RPC notification in background without awaiting a response."""
        def worker():
            try:
                params = json.loads(args.params.strip()) if args.params and args.params.strip() else None
                self.client.send_notification(args.method, params)
                self.poutput("Notification sent.")
            except json.JSONDecodeError as jde:
                self.perror(f"JSON decode error in params: {jde}")
            except Exception as e:
                self.perror(f"Error: {e}")

        threading.Thread(target=worker, daemon=True).start()

    @with_argparser(TAPCmdParsers.parser_upload)
    def do_upload(self, args) -> None:
        """Upload a G-code file to the pipette and display the server path."""
        self.upload_gcode(args.filename, args.file_path)

    def do_read(self, _: Statement) -> None:
        """Read and display the next message from the server if available."""
        if not self.client.message_queue.empty():
            message = self.client.message_queue.get()
            self.poutput(f"Received: {message}")
        else:
            self.poutput("No messages.")

    def do_reconnect(self, _: Statement) -> None:
        """Reconnect the WebSocket client and restore any subscriptions."""
        existing_handlers = dict(self.client._handlers)
        self.client.stop()

        new_client = WebSocketClient(self.url)
        for method, callback in existing_handlers.items():
            new_client.register_handler(method, callback)
        self.client = new_client
        self.client.start()

        connected = self.client._connected.wait(timeout=10)
        if connected and self.client.ws and not self.client.ws.closed:
            for method in existing_handlers.keys():
                try:
                    self.client.send_notification(method, None)
                except Exception:
                    pass
            self.poutput("WebSocket reconnected and subscriptions restored.")
        else:
            self.perror("Failed to reconnect to WebSocket.")
