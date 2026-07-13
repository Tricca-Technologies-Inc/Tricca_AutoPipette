"""Base class for Tricca AutoPipette command sets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cmd2 import CommandSet

if TYPE_CHECKING:
    from tap_shell import TriccaAutoPipetteShell


class TAPCommandSet(CommandSet):
    """Base class for Tricca AutoPipette command sets.

    Provides type-safe access to the parent shell instance.
    """

    @property
    def shell(self) -> TriccaAutoPipetteShell:
        """Get the parent shell instance.

        Returns:
            The TriccaAutoPipetteShell instance.

        Raises:
            RuntimeError: If command set has not been registered with a shell.
        """
        from tap_shell import TriccaAutoPipetteShell

        if self._cmd is None:
            raise RuntimeError("CommandSet not registered with a shell")

        # Type assertion - we know this is TriccaAutoPipetteShell
        assert isinstance(self._cmd, TriccaAutoPipetteShell)
        return self._cmd
