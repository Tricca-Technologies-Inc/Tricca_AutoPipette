"""Base class for Tricca AutoPipette command sets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cmd2 import CommandSet

if TYPE_CHECKING:
    from tricca_autopipette.cli.tap_shell import TriccaAutoPipetteShell
    from tricca_autopipette.daemon.service import AutoPipetteService


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
        from tricca_autopipette.cli.tap_shell import TriccaAutoPipetteShell

        if self._cmd is None:
            raise RuntimeError("CommandSet not registered with a shell")

        # Type assertion - we know this is TriccaAutoPipetteShell
        assert isinstance(self._cmd, TriccaAutoPipetteShell)
        return self._cmd

    @property
    def service(self) -> AutoPipetteService:
        """The ``AutoPipetteService`` that owns this shell's business logic.

        As of migration Phase 4 (see CLAUDE.md's ports-and-adapters notes),
        ``TriccaAutoPipetteShell.__init__`` always constructs its
        ``AutoPipetteService`` before registering any command sets, so this
        is unconditionally available -- both for the daemon (which talks to
        an ``AutoPipetteService`` directly, with no cmd2 shell at all) and
        for standalone/local-scripting use of this shell.

        Returns:
            The ``AutoPipetteService`` instance.
        """
        return self.shell.service
