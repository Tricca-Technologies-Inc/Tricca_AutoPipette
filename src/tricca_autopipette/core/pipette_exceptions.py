#!/usr/bin/env python3
"""Custom exceptions for the AutoPipette system.

This module defines all custom exception types used throughout the pipette
control system for error handling and validation.
"""


class AutoPipetteError(Exception):
    """Base exception for all AutoPipette-related errors.

    All custom exceptions in the pipette system inherit from this base class,
    making it easy to catch any pipette-specific error.

    Example:
        >>> try:
        ...     pipette.some_operation()
        ... except AutoPipetteError as e:
        ...     print(f"Pipette error: {e}")
    """

    pass


class TipAlreadyOnError(AutoPipetteError):
    """Raised when attempting to attach a tip while one is already attached.

    This error prevents damaging the pipette by trying to pick up a second
    tip without ejecting the current one first.

    Example:
        >>> pipette.next_tip()  # First tip pickup
        >>> pipette.next_tip()  # Raises TipAlreadyOnError
    """

    def __init__(self) -> None:
        """Initialize the error with a descriptive message."""
        super().__init__("Tip already attached. Eject current tip first.")


class NotALocationError(AutoPipetteError):
    """Raised when accessing an undefined or invalid location name.

    Attributes:
        location: The invalid location name that was requested.

    Example:
        >>> pipette.get_location_coor("nonexistent")
        NotALocationError: 'nonexistent' is not a named location.
    """

    def __init__(self, location: str) -> None:
        """Initialize the error with the invalid location name.

        Args:
            location: The name of the location that doesn't exist.
        """
        self.location = location
        super().__init__(f"{location} is not a named location.")


class NoTipboxError(AutoPipetteError):
    """Raised when attempting tip operations without a configured tipbox.

    Example:
        >>> pipette.next_tip()  # No tipbox configured
        NoTipboxError: No tipbox configured.
    """

    def __init__(self) -> None:
        """Initialize the error with a descriptive message."""
        super().__init__("No tipbox configured.")


class MissingConfigError(AutoPipetteError):
    """Raised when required configuration sections are missing from config file.

    Attributes:
        section: The missing configuration section name.
        conf_path: Path to the configuration file.

    Example:
        Missing section 'SPEED' in config: /path/to/config.conf
    """

    def __init__(self, section: str, conf_path: str) -> None:
        """Initialize the error with configuration details.

        Args:
            section: Name of the missing configuration section.
            conf_path: Path to the configuration file being loaded.
        """
        self.section = section
        self.conf_path = conf_path
        super().__init__(f"Missing section {section!r} in config: {conf_path}")


class NotADipStrategyError(AutoPipetteError):
    """Raised when an invalid dipping strategy is specified.

    Attributes:
        strategy: The invalid strategy name that was provided.
        valid_strategies: List of valid strategy names.

    Example:
        >>> well = Well(..., strategy_type="invalid")
        NotADipStrategyError: Invalid dip strategy 'invalid'.
    """

    def __init__(
        self, strategy: str, valid_strategies: list[str] | None = None
    ) -> None:
        """Initialize the error with strategy details.

        Args:
            strategy: The invalid strategy name.
            valid_strategies: List of valid strategy names, or None.
        """
        self.strategy = strategy
        self.valid_strategies = valid_strategies

        if valid_strategies:
            super().__init__(
                f"Invalid dip strategy {strategy!r}. "
                f"Valid options: {valid_strategies}"
            )
        else:
            super().__init__(f"Invalid dip strategy {strategy!r}.")


class NoWasteContainerError(AutoPipetteError):
    """Raised when attempting to dispose of a tip without a waste container.

    Example:
        >>> pipette.dispose_tip()  # No waste container configured
        NoWasteContainerError: No waste container configured.
    """

    def __init__(self) -> None:
        """Initialize the error with a descriptive message."""
        super().__init__("No waste container configured.")


class ProtocolAbortedError(AutoPipetteError):
    """Raised when a ``break`` line's breakpoint is answered "abort".

    Replaces the old ``KeyboardInterrupt``-based signal, which
    ``cmd2.Cmd.runcmds_plus_hooks`` used to swallow into the same ``False``
    return value used for normal completion -- making an aborted protocol
    indistinguishable from a successful one from the caller's side. This is
    a distinct, named exception instead, caught explicitly by
    ``daemon/service.py``'s protocol-run methods.

    Kept in this module (rather than ``daemon/service.py``, where it was
    originally defined) so that ``commands/protocol_commands.py`` can catch
    it without importing ``daemon/service.py`` -- ``daemon/service.py``
    itself imports from ``commands/tap_cmd_parsers.py``, which triggers the
    ``commands`` package's ``__init__.py``, which imports
    ``protocol_commands.py`` -- so the reverse import would be a genuine
    circular import when the daemon (not a cmd2 shell) is the first thing
    to import ``daemon/service.py``.
    """


class NotHomedError(AutoPipetteError):
    """Raised when a gated command runs before the pipette is homed.

    Sourced from live Moonraker ``toolhead.homed_axes`` state (see
    ``daemon/moonraker_state.py``), not local domain state -- unlike this
    module's other exceptions, this one is raised by
    ``daemon/service.py``'s ``require_homed`` decorator rather than
    anywhere in ``core/autopipette.py`` itself. Kept in this module anyway
    since it's the same kind of precondition failure as
    ``NoTipboxError``/``TipAlreadyOnError``.

    Attributes:
        command_name: Name of the command that was blocked.

    Example:
        >>> service.move(MoveArgs(x=10, y=10, z=10))  # Not homed yet
        NotHomedError: Command 'move' blocked — pipette not homed. Run
        'init' or 'home all' first.
    """

    def __init__(self, command_name: str) -> None:
        """Initialize the error with the blocked command's name.

        Args:
            command_name: Name of the command that was blocked.
        """
        self.command_name = command_name
        super().__init__(
            f"Command '{command_name}' blocked — pipette not homed. "
            "Run 'init' or 'home all' first."
        )
