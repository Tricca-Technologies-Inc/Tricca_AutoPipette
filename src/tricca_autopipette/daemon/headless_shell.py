"""Headless variant of the interactive shell, hosted inside ``tapd``.

Subclasses :class:`TriccaAutoPipetteShell` unchanged so every existing
``commands/*.py`` ``CommandSet`` keeps working (they reach through
``self.shell._autopipette``/``.client``/``.mrr``/``.gcode_manager`` per
``commands/base_command_set.py``'s ``TAPCommandSet.shell`` accessor, which
does not care whether the underlying shell is interactive or headless).

Only the parts of the shell that assume a live TTY/``cmdloop()`` are
replaced: lifecycle hooks tied to ``cmdloop()`` (never called here — the
daemon drives startup/shutdown explicitly) and the homed-safety interlock.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from cmd2 import plugin
from rich import print as rprint

from tricca_autopipette.cli.tap_shell import TriccaAutoPipetteShell
from tricca_autopipette.core.pipette_models import TipState

if TYPE_CHECKING:
    from typing import Any

    from tricca_autopipette.daemon.moonraker_state import MoonrakerStateTracker

logger = logging.getLogger(__name__)


class HeadlessTapShell(TriccaAutoPipetteShell):
    """``TriccaAutoPipetteShell`` variant safe to run with no TTY.

    Attributes:
        moonraker_state: Live Klipper state tracker, set by
            ``AutoPipetteService`` after construction (it needs this shell's
            ``client``/``mrr`` to exist first). ``None`` until then; the
            interlock fails safe (treats the machine as not homed) while
            it's unset.
    """

    #: Commands blocked until Moonraker reports the machine homed. Unlike
    #: the interactive shell's original set, "run" is intentionally
    #: excluded: `runcmds_plus_hooks` already re-applies this hook to every
    #: line inside a protocol, so a protocol that needs homing must include
    #: its own leading `home all`/`init` line rather than the outer `run`
    #: command being gated itself.
    _GATED_COMMANDS = frozenset(
        {
            "move",
            "move_loc",
            "move_rel",
            "pipette",
            "aspirate",
            "dispense",
            "next_tip",
            "eject_tip",
            "dispose_tip",
            "change_tip",
        }
    )

    def __init__(
        self,
        config_system: Path,
        config_gantry: Path | None,
        config_pipette: Path | None,
        config_locations: Path | None,
        config_liquids: Path | None,
        connect_websocket: bool = True,
        connect_local_websocket: bool = False,
    ) -> None:
        """Initialize the headless shell.

        Args:
            config_system: Path to master configuration file.
            config_gantry: Path to gantry configuration file (optional).
            config_pipette: Path to pipette model configuration file
                (optional).
            config_locations: Path to named locations configuration file
                (optional).
            config_liquids: Path to liquids configuration file (optional).
            connect_websocket: Whether to connect to Moonraker on startup.
            connect_local_websocket: Whether to connect to a local Moonraker
                for testing.
        """
        self.moonraker_state: MoonrakerStateTracker | None = None
        self._last_persisted_state: tuple[str, bool, str] | None = None
        super().__init__(
            config_system=config_system,
            config_gantry=config_gantry,
            config_pipette=config_pipette,
            config_locations=config_locations,
            config_liquids=config_liquids,
            connect_websocket=connect_websocket,
            connect_local_websocket=connect_local_websocket,
        )

    def _register_hooks(self) -> None:
        """Register hooks appropriate for headless operation.

        Deliberately does not register the base class's preloop/postloop
        hooks (they clear the screen, print a banner, and start/stop the
        WebSocket client — all tied to ``cmdloop()``, which is never called
        here; ``AutoPipetteService`` drives connection startup/shutdown
        directly) or its precmd-based interlock (structurally broken under
        the installed cmd2 4.0 API — ``PrecommandData`` has no ``stop``
        field, so it silently fails to block anything). The replacement
        postparsing hook uses a real ``stop`` field and live Moonraker
        state instead of a locally-mutated flag.
        """
        self.register_postparsing_hook(self._homed_interlock_hook)
        self.register_postcmd_hook(self._persist_tip_liquid_state_hook)

    def _homed_interlock_hook(
        self, data: plugin.PostparsingData
    ) -> plugin.PostparsingData:
        """Block gated commands until Moonraker reports the machine homed.

        Args:
            data: Postparsing data containing the parsed statement.

        Returns:
            Data unmodified if the command is allowed to run, or with
            ``stop=True`` if it must be blocked.
        """
        if data.statement.command not in self._GATED_COMMANDS:
            return data

        homed = self.moonraker_state is not None and self.moonraker_state.is_homed()
        if not homed:
            rprint("[red]Pipette not homed. Run 'init' or 'home all' first.[/]")
            logger.warning(
                "Command '%s' blocked - pipette not homed", data.statement.command
            )
            return replace(data, stop=True)
        return data

    def apply_persisted_state(self, values: dict[str, Any]) -> None:
        """Rehydrate tip/liquid state from a prior daemon run.

        Args:
            values: Mapping as returned by
                ``MoonrakerStateTracker.load_tip_liquid_state`` — any subset
                of ``tip_state``/``has_liquid``/``current_liquid`` may be
                absent (e.g. first run, nothing persisted yet).
        """
        state = self._autopipette.state
        if "tip_state" in values:
            state.tip_state = TipState(values["tip_state"])
        if "has_liquid" in values:
            state.has_liquid = bool(values["has_liquid"])
        current_liquid = values.get("current_liquid")
        if current_liquid and current_liquid in self._autopipette.system_config.liquids:
            self._autopipette.switch_liquid(current_liquid)
        self._last_persisted_state = (
            state.tip_state.value,
            state.has_liquid,
            self._autopipette.active_liquid,
        )

    def _persist_tip_liquid_state_hook(
        self, data: plugin.PostcommandData
    ) -> plugin.PostcommandData:
        """Persist tip/liquid state to Moonraker's database if it changed.

        Runs after every command rather than being wired into individual
        ``next_tip``/``eject_tip``/``switch_liquid``/etc. handlers, so
        ``commands/*.py`` doesn't need to know about daemon-specific
        persistence at all.

        Args:
            data: Postcommand data (unmodified; this hook only has side
                effects).

        Returns:
            Data unmodified.
        """
        if self.moonraker_state is None:
            return data

        state = self._autopipette.state
        snapshot = (
            state.tip_state.value,
            state.has_liquid,
            self._autopipette.active_liquid,
        )
        if snapshot != self._last_persisted_state:
            self._last_persisted_state = snapshot
            self.moonraker_state.save_tip_liquid_state(*snapshot)
        return data
