"""Base class for Tricca AutoPipette command sets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cmd2 import CommandSet

if TYPE_CHECKING:
    from tricca_autopipette.cli.tap_shell import TriccaAutoPipetteShell
    from tricca_autopipette.daemon.service import AutoPipetteService

    # cmd2 4.0's CommandSet is generic over the Cmd subclass it loads into,
    # and parameterizing it is what gives `self._cmd` a real type. It can
    # only be subscripted under TYPE_CHECKING: tap_shell imports the command
    # sets, so importing TriccaAutoPipetteShell at runtime here would close
    # an import cycle.
    _CommandSetBase = CommandSet[TriccaAutoPipetteShell]
else:
    _CommandSetBase = CommandSet


class TAPCommandSet(_CommandSetBase):
    """Base class for Tricca AutoPipette command sets.

    Provides type-safe access to the parent shell instance.
    """

    @property
    def shell(self) -> TriccaAutoPipetteShell:
        """The parent shell instance.

        Returns:
            The TriccaAutoPipetteShell instance.

        Raises:
            CommandSetRegistrationError: If this command set has not been
                registered with a shell (raised by cmd2's own ``_cmd``
                property, which never returns None).
        """
        from tricca_autopipette.cli.tap_shell import TriccaAutoPipetteShell

        # Guards against registration into some *other* cmd2 app; the
        # unregistered case is already handled by cmd2's _cmd property.
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
