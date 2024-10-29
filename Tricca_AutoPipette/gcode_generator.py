#!/usr/bin/env python3

"""Produce a .gcode file from a .pipette protocol file."""
from pathlib import Path
import argparse
from protocol_commands import ProtocolCommands

GCODE_PATH = Path(__file__).parent.parent / 'gcode/'
PROTOCOL_PATH = Path(__file__).parent.parent / 'protocols/'


def gen_gcode(protocol: str, _print: bool = False):
    """Convert the protocol commands into gcode and generate a gcode file."""
    prot_fname = protocol + ".pipette"
    gcode_fname = protocol + ".gcode"
    if _print:
        print(f"Protocol File Name: {prot_fname}, \t\
            GCode File Name: {gcode_fname}")
    prot_file = PROTOCOL_PATH / prot_fname
    if (not prot_file.exists()):
        print(f"File {prot_fname} does not exist.")
    gcode_file = GCODE_PATH / gcode_fname
    # Delete any existing file with the same name and make a new file.
    gcode_file.unlink(missing_ok=True)
    gcode_file.touch()
    protcmds = ProtocolCommands()
    # Each line in .pipette file is a command that is converted into gcode
    with gcode_file.open('w') as gcode_fobj:
        with prot_file.open() as prot_fobj:
            gcode_fobj.write(protcmds.init_file())
            for cmd in prot_fobj:
                gcode_fobj.write(protcmds.cmd_to_gcode(cmd))


if __name__ == "__main__":
    # Setup parser and get arguments
    parser = argparse.ArgumentParser(
        description="Produce a .gcode file from a .pipette protocol file.")
    parser.add_argument("protocol", help="the name of the protocol \
        located in ../protocols")
    args = parser.parse_args()
    gen_gcode(args.protocol, _print=True)
