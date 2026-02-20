#!/usr/bin/env python3
"""G-code command buffering and management.

This module provides the GCodeBuffer class for accumulating, organizing,
and retrieving G-code commands with optional header support.
"""

from __future__ import annotations


class GCodeBuffer:
    """Manages G-code command generation and buffering.

    Provides separate buffers for header comments (configuration info)
    and command sequences. Supports batch accumulation and retrieval.

    Attributes:
        _commands: Main buffer for G-code commands.
        _header: Buffer for configuration header comments.

    Example:
        >>> buffer = GCodeBuffer()
        >>> buffer.add("G28\n")
        >>> buffer.add("G1 X10 Y10 F5000\n")
        >>> commands = buffer.get_commands()
        >>> # commands = ['G28\n', 'G1 X10 Y10 F5000\n']
    """

    def __init__(self) -> None:
        """Initialize empty command and header buffers."""
        self._commands: list[str] = []
        self._header: list[str] = []

    def add(self, command: str) -> None:
        """Add a command to the main buffer.

        Args:
            command: G-code command string to buffer.

        Example:
            >>> buffer.add("G28\n")
            >>> buffer.add("G1 X100 Y50 F5000\n")
        """
        self._commands.append(command)

    def add_header(self, line: str) -> None:
        """Add a line to the configuration header.

        Args:
            line: Header comment line (typically starts with ';').

        Example:
            >>> buffer.add_header("; Configuration: autopipette.conf\n")
            >>> buffer.add_header("; SPEED_XY = 5000\n")
        """
        self._header.append(line)

    def get_commands(self) -> list[str]:
        """Retrieve buffered commands and clear the command buffer.

        Returns:
            List of G-code command strings.

        Note:
            This is destructive - the command buffer is cleared after retrieval.
            The header buffer is NOT cleared.

        Example:
            >>> buffer.add("G28\n")
            >>> commands = buffer.get_commands()
            >>> # commands = ['G28\n']
            >>> commands2 = buffer.get_commands()
            >>> # commands2 = []  (buffer was cleared)
        """
        commands = self._commands.copy()
        self._commands.clear()
        return commands

    def get_header(self) -> list[str]:
        """Retrieve the configuration header.

        Returns:
            List of header comment lines.

        Note:
            Unlike get_commands(), this does NOT clear the header buffer.
            The header can be retrieved multiple times.

        Example:
            >>> header = buffer.get_header()
            >>> header2 = buffer.get_header()
            >>> # header == header2 (not cleared)
        """
        return self._header.copy()

    def clear_commands(self) -> None:
        """Clear the command buffer without returning contents.

        Example:
            >>> buffer.add("G28\n")
            >>> buffer.clear_commands()
            >>> # Commands discarded
        """
        self._commands.clear()

    def clear_header(self) -> None:
        """Clear the header buffer.

        Example:
            >>> buffer.add_header("; Config\n")
            >>> buffer.clear_header()
            >>> # Header cleared
        """
        self._header.clear()

    def clear_all(self) -> None:
        """Clear both command and header buffers.

        Example:
            >>> buffer.clear_all()
            >>> # Everything cleared
        """
        self._commands.clear()
        self._header.clear()

    def has_commands(self) -> bool:
        """Check if the command buffer has any commands.

        Returns:
            True if commands are buffered, False otherwise.

        Example:
            >>> buffer.has_commands()
            False
            >>> buffer.add("G28\n")
            >>> buffer.has_commands()
            True
        """
        return len(self._commands) > 0

    def command_count(self) -> int:
        """Get the number of buffered commands.

        Returns:
            Number of commands in the buffer.

        Example:
            >>> buffer.add("G28\n")
            >>> buffer.add("G1 X10\n")
            >>> buffer.command_count()
            2
        """
        return len(self._commands)

    def peek_commands(self) -> list[str]:
        """View buffered commands without clearing them.

        Returns:
            Copy of buffered commands.

        Note:
            Unlike get_commands(), this does not clear the buffer.

        Example:
            >>> buffer.add("G28\n")
            >>> peek = buffer.peek_commands()
            >>> # peek = ['G28\n']
            >>> commands = buffer.get_commands()
            >>> # commands = ['G28\n'] (buffer now cleared)
        """
        return self._commands.copy()

    def build_header_from_config(
        self, config_filename: str, config_sections: dict[str, dict[str, str]]
    ) -> None:
        """Build configuration header from config data.

        Creates a formatted header with all configuration settings
        organized by section.

        Args:
            config_filename: Name of the configuration file.
            config_sections: Dictionary of section names to key-value pairs.

        Example:
            >>> sections = {
            ...     "SPEED": {"SPEED_XY": "5000", "SPEED_Z": "2000"},
            ...     "SERVO": {"ANGLE_RETRACT": "160"}
            ... }
            >>> buffer.build_header_from_config("auto.conf", sections)
            >>> header = buffer.get_header()
            >>> # header contains formatted config comments
        """
        self.clear_header()
        self.add_header(f"; Configuration: {config_filename}\n")
        self.add_header("; Settings:\n")

        for section_name, items in config_sections.items():
            self.add_header(f"; [{section_name}]\n")
            for key, value in items.items():
                self.add_header(f";\t {key} = {value}\n")

    def __len__(self) -> int:
        """Return the number of buffered commands.

        Allows using len(buffer) instead of buffer.command_count().

        Example:
            >>> buffer.add("G28\n")
            >>> len(buffer)
            1
        """
        return len(self._commands)

    def __bool__(self) -> bool:
        """Return True if buffer has commands.

        Allows using if buffer: instead of if buffer.has_commands().

        Example:
            >>> buffer = GCodeBuffer()
            >>> bool(buffer)
            False
            >>> buffer.add("G28\n")
            >>> bool(buffer)
            True
        """
        return len(self._commands) > 0

    def __repr__(self) -> str:
        """Return string representation of the buffer.

        Example:
            >>> buffer = GCodeBuffer()
            >>> buffer.add("G28\n")
            >>> repr(buffer)
            'GCodeBuffer(commands=1, header=0)'
        """
        return (
            f"GCodeBuffer(commands={len(self._commands)}, "
            f"header={len(self._header)})"
        )
