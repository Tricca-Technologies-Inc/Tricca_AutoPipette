"""G-code management for the Tricca AutoPipette Shell.

This module provides G-code generation, buffering, and file operations.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from gcode_buffer import GCodeBuffer

if TYPE_CHECKING:
    from autopipette import AutoPipette

# Constants
GCODE_TIMESTAMP_FORMAT = "%Y-%m-%d-%H-%M-%S-%f.gcode"


class GCodeManager:
    """Manages G-code generation, buffering, and file operations.

    Provides two modes of operation:
    1. Immediate mode: G-code is written to file and uploaded immediately
    2. Batch mode: G-code is buffered for later combined upload (for protocols)

    Attributes:
        gcode_path: Base directory for G-code files.
        _autopipette: AutoPipette instance for header generation.
        _buffer: G-code buffer for batch mode operations.
        _batch_mode: Flag indicating if batch mode is active.
    """

    def __init__(self, gcode_path: Path, autopipette: AutoPipette) -> None:
        """Initialize the G-code manager.

        Args:
            gcode_path: Base directory for G-code files.
            autopipette: AutoPipette instance for configuration.
        """
        self.gcode_path = gcode_path
        self._autopipette = autopipette
        self._buffer = GCodeBuffer()
        self._batch_mode = False

    @property
    def is_batch_mode(self) -> bool:
        """Check if batch mode is active.

        Returns:
            True if in batch mode, False otherwise.
        """
        return self._batch_mode

    def start_batch(self) -> None:
        """Enter batch mode for protocol execution.

        Clears any existing buffer and activates batch mode.
        """
        self._batch_mode = True
        self._buffer.clear_commands()

    def end_batch(self) -> list[str]:
        """Exit batch mode and return accumulated G-code.

        Returns:
            List of accumulated G-code commands.
        """
        self._batch_mode = False
        result = self._buffer.get_commands()  # Gets and clears
        return result

    @contextmanager
    def batch_mode(self) -> Iterator[GCodeManager]:
        """Context manager for batch G-code generation.

        Yields:
            Self for method chaining within the context.

        Example:
            >>> with gcode_mgr.batch_mode():
            ...     gcode_mgr.add_gcode(["G0 X10 Y10"])
            ...     gcode_mgr.add_gcode(["G0 Z5"])
            >>> buffer = gcode_mgr.get_buffer()
        """
        self.start_batch()
        try:
            yield self
        finally:
            pass  # Don't auto-clear; caller retrieves buffer explicitly

    def add_gcode(self, gcode: list[str]) -> None:
        """Add G-code commands to the buffer.

        Only works in batch mode. In immediate mode, use write_gcode_file.

        Args:
            gcode: List of G-code command strings.

        Raises:
            RuntimeError: If called when not in batch mode.
        """
        if not self._batch_mode:
            raise RuntimeError(
                "add_gcode() can only be used in batch mode. "
                "Use write_gcode_file() for immediate mode."
            )
        for cmd in gcode:
            self._buffer.add(cmd)
        self._buffer.add("\n")

    def get_buffer(self) -> list[str]:
        """Get the current G-code buffer without clearing it.

        Returns:
            Copy of the current buffer.
        """
        return self._buffer.peek_commands()

    def clear_buffer(self) -> None:
        """Clear the G-code buffer."""
        self._buffer.clear_commands()

    def write_gcode_file(
        self,
        gcode: list[str],
        filename: str | None = None,
        append_header: bool = False,
    ) -> Path:
        """Write G-code to file.

        Creates a G-code file in the temp directory with optional header.

        Args:
            gcode: List of G-code command strings.
            filename: Output filename, or None to auto-generate timestamp.
            append_header: Whether to prepend configuration header.

        Returns:
            Path to the created G-code file.

        Raises:
            OSError: If the file or directory cannot be created or written

        Example:
            >>> path = gcode_mgr.write_gcode_file(
            ...     ["G28", "G0 X10 Y10"],
            ...     "home_and_move.gcode"
            ... )
        """
        if filename is None:
            filename = datetime.now().strftime(GCODE_TIMESTAMP_FORMAT)

        file_path = self.gcode_path / "temp" / filename

        try:
            # Ensure temp directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                if append_header:
                    for comment in self._autopipette.get_header():
                        f.write(comment.rstrip("\n") + "\n")
                for cmd in gcode:
                    f.write(cmd.rstrip("\n") + "\n")
        except OSError as e:
            raise OSError(f"Failed to write G-code file: {file_path}") from e

        return file_path
