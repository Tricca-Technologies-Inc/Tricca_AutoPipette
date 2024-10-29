#!/usr/bin/env python3
"""Holds the class to run a shell to control the autopipette."""
import cmd
from protocol_commands import ProtocolCommands
from autopipette import AutoPipette
import requests
from pathlib import Path
from gcode_generator import gen_gcode


class AutoPipetteShell(cmd.Cmd):
    """A terminal to control the pipette."""

    intro = r"""
  ______     _                     ___         __        ____  _            __  __
 /_  __/____(_)_____________ _    /   | __  __/ /_____  / __ \(_)___  ___  / /_/ /____
  / / / ___/ / ___/ ___/ __ `/   / /| |/ / / / __/ __ \/ /_/ / / __ \/ _ \/ __/ __/ _ \
 / / / /  / / /__/ /__/ /_/ /   / ___ / /_/ / /_/ /_/ / ____/ / /_/ /  __/ /_/ /_/  __/
/_/ /_/  /_/\___/\___/\__,_/   /_/  |_\__,_/\__/\____/_/   /_/ .___/\___/\__/\__/\___/
                                                            /_/
"""
    prompt = "autopipette >> "
    file = None
    _autopipette: AutoPipette = None
    _protocol_commands: ProtocolCommands = None
    _url: str = ""
    GCODE_PATH = Path(__file__).parent.parent / 'gcode/'
    PROTOCOL_PATH = Path(__file__).parent.parent / 'protocols/'

    def __init__(self,
                 autopipette: AutoPipette = AutoPipette(),
                 url: str = "http://0.0.0.0:7125/printer/gcode/script"):
        """Initialize self, AutoPipette and ProtocolCommands objects."""
        super(AutoPipetteShell, self).__init__()
        self._autopipette = autopipette
        self._protocol_commands = ProtocolCommands(self._autopipette)
        self._url = url

    def preloop(self):
        """Execute once before entering loop.

        Used to home pipette and set passed in parameters.
        """
        setup = self._autopipette.file_header.splitlines()
        print("Setting up pipette...")
        for code in setup:
            self.send_gcode(code)

    def run_gcode(self, filename: str):
        """Open a gcode file and execute it."""
        file = self.GCODE_PATH / filename
        if (not file.exists()):
            print(f"File {filename} does not exist.")
            return
        with file.open() as fileobj:
            for line in fileobj:
                print(line)
                self.send_gcode(line)

    def send_gcode(self, command):
        """Send gcode to the pipette."""
        response = requests.post(self._url, json={"script": command})
        if response.status_code == 200:
            # print("Command sent successfully")
            pass
        else:
            print(f"Failed to send command: \
                {response.status_code}, {response.text}")

    def print_or_send_lines(self, gcode_lines: str):
        """Print a line if its a gcode comment, otherwise send it."""
        gcode_lines = gcode_lines.splitlines()
        for gcode_line in gcode_lines:
            if gcode_line.startswith(";"):
                print(gcode_line[2:])
            else:
                self.send_gcode(gcode_line)

    def do_move(self, arg):
        """Move the pipette to a specific coordinate."""
        self.print_or_send_lines(self._protocol_commands.move(arg))

    def do_home(self, arg):
        """Home the pipette."""
        print("Homing...")
        self.print_or_send_lines(self._protocol_commands.home(arg))
        print("Done.")

    def do_exit(self, arg):
        """Stop recording, close the shell, and exit."""
        print('Ending connection with pipette...')
        self.close()
        return True

    def do_set(self, arg):
        """Set a variable on the pipette to a value."""
        self.print_or_send_lines(self._protocol_commands.set(arg))

    def do_pipette(self, arg):
        """Move vol amount of liquid from src to dest."""
        print("Pipetting...")
        self.print_or_send_lines(self._protocol_commands.pipette(arg))
        print("Done.")

    def do_coor(self, arg):
        """Create a named location or associate one with a plate type."""
        self.print_or_send_lines(self._protocol_commands.gen_coordinate(arg))

    def do_next_tip(self, arg):
        """Pickup the next tip in the tip box."""
        self.print_or_send_lines(self._protocol_commands.next_tip(arg))

    def do_eject_tip(self, arg):
        """Eject the tip on the pipette."""
        self.print_or_send_lines(self._protocol_commands.eject_tip(arg))

    def default(self, arg: str):
        """Run this function if command not recognized.

        Used to process comments in outside files.
        """
        if arg[0] == ";":
            print(arg[1:].lstrip())
        else:
            super().default(arg)

    # ----- record and playback -----
    def do_record(self, arg: str):
        """Save the future commands to filename.

        RECORD commands.pipette
        """
        if arg.endswith(".pipette"):
            _file = self.PROTOCOL_PATH / arg
            self.file = open(_file, 'w')
        else:
            print("Must have a '.pipette' suffix.")

    def do_playback(self, arg: str):
        """Playback commands from a file.

        PLAYBACK commands.pipette
        """
        if not arg.endswith(".pipette"):
            arg += ".pipette"
        _file_cmd = self.PROTOCOL_PATH / arg
        arg = arg.removesuffix(".pipette")
        if _file_cmd.exists():
            self.close()
            gen_gcode(arg)
            arg += ".gcode"
            _file_gcode = self.GCODE_PATH / arg
            with _file_gcode.open('r') as fobj_gcode:
                for line in fobj_gcode:
                    self.print_or_send_lines(line)
        else:
            print(f"File:{_file_cmd} does not exist.")

    def precmd(self, line):
        """Convert lines to lower and return it or print it if playback."""
        line = line.lower()
        if self.file and 'playback' not in line:
            print(line, file=self.file)
        return line

    def close(self):
        """Close the shell and handle file closing."""
        if self.file:
            self.file.close()
            self.file = None


if __name__ == '__main__':
    AutoPipetteShell().cmdloop()
