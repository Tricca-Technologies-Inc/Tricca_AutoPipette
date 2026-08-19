"""Shared command-parsing helpers for `tap`.

This package used to also hold the `TAPCommandSet` subclasses backing the
standalone `TriccaAutoPipetteShell` (`cli/tap_shell.py`); both were removed
in issue #39 once `RemoteTapShell` (`cli/remote_shell.py`) reached full
command parity. What remains is `tap_cmd_parsers.py` (`TAPCmdParsers`),
shared by `RemoteTapShell` and the daemon's `ControlServer`/
`AutoPipetteService` -- import it directly
(`tricca_autopipette.commands.tap_cmd_parsers`) rather than through this
package's namespace.
"""
