#!/usr/bin/env python3
"""Holds command sets related to the pipette."""
from cmd2 import CommandSet, with_default_category


@with_default_category("Pipette Commands")
class CommandSetPipette(CommandSet):
    """Class that holds all commands related to the pipette."""

    def __init__(self):
        """Initialize the command set."""
        super().__init__()

    def do_init_pipette(self):
        """Initialize the pipette."""
        self.output_gcode(self._autopipette.return_header())
