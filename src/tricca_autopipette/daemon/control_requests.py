"""Request builders for the ``tapd`` control-plane JSON-RPC protocol.

Pure functions, no I/O — mirrors the shape of
``moonraker/moonraker_requests.py`` so callers can send the resulting dicts
through the same ``WebSocketClient.send_jsonrpc`` transport used to talk to
Moonraker itself.

Example:
    >>> cr = ControlRequests()
    >>> request = cr.run_start("A1.pipette")
    >>> # Send request via WebSocketClient.send_jsonrpc to tapd's control plane
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from tricca_autopipette.commands.tap_cmd_parsers import (
    AspirateArgs,
    CoorArgs,
    DelLocArgs,
    DispenseArgs,
    GcodePrintArgs,
    HomeArgs,
    LoadLocationsArgs,
    MoveArgs,
    MoveLocArgs,
    MoveRelArgs,
    PipetteArgs,
    PlateArgs,
    ResetPlateArgs,
    ResetTipsArgs,
    SeeCalibrationArgs,
    SetArgs,
    SetTipsArgs,
    TipsArgs,
    TriggerArgs,
    UnloadLocationsArgs,
    VolToStepsArgs,
    WaitArgs,
)


class ControlRequests:
    """JSON-RPC request builder for the ``tapd`` control-plane protocol."""

    JSON_RPC_VERSION: str = "2.0"

    def gen_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Generate a JSON-RPC 2.0 request.

        Args:
            method: Control-plane method to call.
            params: Optional parameters dictionary for the method.

        Returns:
            Dictionary representing the JSON-RPC request.
        """
        request: dict[str, Any] = {
            "jsonrpc": self.JSON_RPC_VERSION,
            "method": method,
            "id": str(uuid.uuid4()),
        }
        if params is not None:
            request["params"] = params
        return request

    def init(self) -> dict[str, Any]:
        """Build a request to initialise the pipette.

        Sets the coordinate system, speed, and performs full homing.

        Returns:
            Request to run the init sequence.
        """
        return self.gen_request("movement.init")

    def home(self, args: HomeArgs) -> dict[str, Any]:
        """Build a request to home one or more motors.

        Args:
            args: Motor specification (x, y, z, pipette, axis, all, servo).

        Returns:
            Request to home the given motor(s).
        """
        return self.gen_request("movement.home", dataclasses.asdict(args))

    def move(self, args: MoveArgs) -> dict[str, Any]:
        """Build a request to move to absolute XYZ coordinates.

        Args:
            args: Target x/y/z coordinates in millimeters.

        Returns:
            Request to perform the move.
        """
        return self.gen_request("movement.move", dataclasses.asdict(args))

    def move_loc(self, args: MoveLocArgs) -> dict[str, Any]:
        """Build a request to move to a named location.

        Args:
            args: Location name and optional row/col well indices.

        Returns:
            Request to perform the move.
        """
        return self.gen_request("movement.move_loc", dataclasses.asdict(args))

    def move_rel(self, args: MoveRelArgs) -> dict[str, Any]:
        """Build a request to move relative to the current position.

        Args:
            args: Relative x/y/z offsets in millimeters.

        Returns:
            Request to perform the move.
        """
        return self.gen_request("movement.move_rel", dataclasses.asdict(args))

    def aspirate(self, args: AspirateArgs) -> dict[str, Any]:
        """Build a request to aspirate liquid from a source.

        Args:
            args: Volume, source location, and aspirate options.

        Returns:
            Request to perform the aspiration.
        """
        return self.gen_request("pipette.aspirate", dataclasses.asdict(args))

    def dispense(self, args: DispenseArgs) -> dict[str, Any]:
        """Build a request to dispense liquid to a destination.

        Args:
            args: Destination location and dispense options.

        Returns:
            Request to perform the dispense.
        """
        return self.gen_request("pipette.dispense", dataclasses.asdict(args))

    def transfer(self, args: PipetteArgs) -> dict[str, Any]:
        """Build a request to transfer liquid from source to destination.

        Maps to the interactive ``pipette`` command; named ``transfer``
        here (and in the ``pipette.*`` namespace) to avoid a
        ``pipette.pipette`` stutter.

        Args:
            args: Full transfer parameters.

        Returns:
            Request to perform the transfer.
        """
        return self.gen_request("pipette.transfer", dataclasses.asdict(args))

    def next_tip(self) -> dict[str, Any]:
        """Build a request to pick up the next available tip.

        Returns:
            Request to pick up a tip.
        """
        return self.gen_request("pipette.next_tip")

    def eject_tip(self) -> dict[str, Any]:
        """Build a request to eject the current tip in place.

        Returns:
            Request to eject the tip.
        """
        return self.gen_request("pipette.eject_tip")

    def dispose_tip(self) -> dict[str, Any]:
        """Build a request to dispose the current tip in the waste container.

        Returns:
            Request to dispose the tip.
        """
        return self.gen_request("pipette.dispose_tip")

    def change_tip(self) -> dict[str, Any]:
        """Build a request to dispose the current tip and pick up a fresh one.

        Returns:
            Request to change the tip.
        """
        return self.gen_request("pipette.change_tip")

    def switch_liquid(self, liquid_name: str) -> dict[str, Any]:
        """Build a request to switch to a different liquid profile.

        Args:
            liquid_name: Name of the liquid profile to activate.

        Returns:
            Request to switch liquids.
        """
        return self.gen_request("config.switch_liquid", {"liquid_name": liquid_name})

    def load_liquid(self, filename: str) -> dict[str, Any]:
        """Build a request to load a new liquid profile from a JSON file.

        Args:
            filename: Liquid config filename under ``config/liquids/``.

        Returns:
            Request to load the liquid profile.
        """
        return self.gen_request("config.load_liquid", {"filename": filename})

    def set(self, args: SetArgs) -> dict[str, Any]:
        """Build a request to set a gantry configuration variable.

        Args:
            args: Variable name and new numeric value.

        Returns:
            Request to set the variable.
        """
        return self.gen_request("config.set", dataclasses.asdict(args))

    def coor(self, args: CoorArgs) -> dict[str, Any]:
        """Build a request to define a named coordinate location.

        Args:
            args: Location name and x/y/z coordinates.

        Returns:
            Request to create the coordinate.
        """
        return self.gen_request("config.coor", dataclasses.asdict(args))

    def plate(self, args: PlateArgs) -> dict[str, Any]:
        """Build a request to define a plate at a named location.

        Args:
            args: Plate name, type, dimensions, position, and dip strategy.

        Returns:
            Request to create the plate.
        """
        return self.gen_request("config.plate", dataclasses.asdict(args))

    def reset_plate(self, args: ResetPlateArgs) -> dict[str, Any]:
        """Build a request to reset a plate's position to its origin well.

        Args:
            args: Name of the plate to reset.

        Returns:
            Request to reset the plate.
        """
        return self.gen_request("config.reset_plate", dataclasses.asdict(args))

    def reset_plates(self) -> dict[str, Any]:
        """Build a request to reset all plates to their origin well.

        Returns:
            Request to reset all plates.
        """
        return self.gen_request("config.reset_plates")

    def del_loc(self, args: DelLocArgs) -> dict[str, Any]:
        """Build a request to delete a named location or plate.

        Args:
            args: Name of the location to delete.

        Returns:
            Request to delete the location.
        """
        return self.gen_request("config.del_loc", dataclasses.asdict(args))

    def clear_locs(self) -> dict[str, Any]:
        """Build a request to delete all locations and plates.

        Returns:
            Request to clear all locations.
        """
        return self.gen_request("config.clear_locs")

    def save_locations(self, filename: str) -> dict[str, Any]:
        """Build a request to save current locations to a JSON file.

        Args:
            filename: Output filename under ``config/locations/``.

        Returns:
            Request to save locations.
        """
        return self.gen_request("config.save_locations", {"filename": filename})

    def load_locations(self, args: LoadLocationsArgs) -> dict[str, Any]:
        """Build a request to load locations from a JSON file.

        Args:
            args: Filename under ``config/locations/`` and whether to clear the
                deck first (loading is additive by default).

        Returns:
            Request to load locations.
        """
        return self.gen_request("config.load_locations", dataclasses.asdict(args))

    def unload_locations(self, args: UnloadLocationsArgs) -> dict[str, Any]:
        """Build a request to unload a single location by name.

        Args:
            args: Name of the location to unload.

        Returns:
            Request to unload the location.
        """
        return self.gen_request("config.unload_locations", dataclasses.asdict(args))

    def reset_tips(self, args: ResetTipsArgs) -> dict[str, Any]:
        """Build a request to mark one tipbox as full.

        Args:
            args: Name of the tipbox to reset.

        Returns:
            Request to reset the tipbox.
        """
        return self.gen_request("config.reset_tips", dataclasses.asdict(args))

    def reset_tips_all(self) -> dict[str, Any]:
        """Build a request to mark every tipbox as full.

        Returns:
            Request to reset all tipboxes.
        """
        return self.gen_request("config.reset_tips_all", {})

    def set_tips(self, args: SetTipsArgs) -> dict[str, Any]:
        """Build a request to declare a tipbox's consumed positions.

        Args:
            args: Tipbox name, well ranges, and whether the ranges name the
                available positions rather than the consumed ones.

        Returns:
            Request to set the tipbox's state.
        """
        return self.gen_request("config.set_tips", dataclasses.asdict(args))

    def tips(self, args: TipsArgs) -> dict[str, Any]:
        """Build a request for tip availability per box.

        Args:
            args: Optional box name, and whether to include the state
                persisted in Moonraker's database.

        Returns:
            Request for the tip report.
        """
        return self.gen_request("config.tips", dataclasses.asdict(args))

    def wait(self, args: WaitArgs) -> dict[str, Any]:
        """Build a request to insert a timed pause into the G-code output.

        Args:
            args: Duration in milliseconds.

        Returns:
            Request to perform the wait.
        """
        return self.gen_request("util.wait", dataclasses.asdict(args))

    def trigger(self, args: TriggerArgs) -> dict[str, Any]:
        """Build a request to control an auxiliary trigger channel.

        Args:
            args: Channel name and desired state.

        Returns:
            Request to control the trigger.
        """
        return self.gen_request("util.trigger", dataclasses.asdict(args))

    def gcode_print(self, args: GcodePrintArgs) -> dict[str, Any]:
        """Build a request to display a message on the pipette screen.

        Args:
            args: Message to display.

        Returns:
            Request to queue the display message.
        """
        return self.gen_request("util.gcode_print", dataclasses.asdict(args))

    def webcam_url(self) -> dict[str, Any]:
        """Build a request for the webcam stream URL.

        Returns:
            Request for the webcam URL.
        """
        return self.gen_request("util.webcam_url")

    def vol_to_steps(self, args: VolToStepsArgs) -> dict[str, Any]:
        """Build a request to convert a volume to plunger travel (in mm).

        Despite the ``vol_to_steps`` name, the value is millimetres passed
        to Klipper's ``MANUAL_STEPPER MOVE=``, not motor steps — see
        ``core/volume_converter.py``, issue #29.

        Args:
            args: Volume in microliters.

        Returns:
            Request to perform the conversion.
        """
        return self.gen_request("util.vol_to_steps", dataclasses.asdict(args))

    def see_calibration(self, args: SeeCalibrationArgs) -> dict[str, Any]:
        """Build a request to show a liquid's calibration curve and fit.

        Args:
            args: Liquid profile to inspect (or None for the active liquid).

        Returns:
            Request for the calibration report.
        """
        return self.gen_request("util.see_calibration", dataclasses.asdict(args))

    def steps_to_vol(self, steps: int) -> dict[str, Any]:
        """Build a request to convert plunger travel (mm) back to a volume.

        Despite the name, ``steps`` is a millimetre value, not motor
        steps — see ``core/volume_converter.py``.

        Args:
            steps: Plunger travel value (actually millimetres — see
                ``core/volume_converter.py``).

        Returns:
            Request to perform the conversion.
        """
        return self.gen_request("util.steps_to_vol", {"steps": steps})

    def run_start(self, filename: str) -> dict[str, Any]:
        """Build a request to start a protocol run.

        Args:
            filename: Bare filename under ``protocols/`` (e.g. "A1.pipette").

        Returns:
            Request to start the run.
        """
        return self.gen_request("run.start", {"filename": filename})

    def run_status(self) -> dict[str, Any]:
        """Build a request for the current run status.

        Returns:
            Request for run status.
        """
        return self.gen_request("run.status")

    def run_cancel(self) -> dict[str, Any]:
        """Build a request to cancel the active run.

        Returns:
            Request to cancel the run.
        """
        return self.gen_request("run.cancel")

    def run_pause(self) -> dict[str, Any]:
        """Build a request to pause the active run.

        Returns:
            Request to pause the run.
        """
        return self.gen_request("run.pause")

    def run_resume(self) -> dict[str, Any]:
        """Build a request to resume the active run.

        Returns:
            Request to resume the run.
        """
        return self.gen_request("run.resume")

    def run_confirm_breakpoint(self, proceed: bool) -> dict[str, Any]:
        """Build a request answering a pending protocol breakpoint.

        Only one run (and therefore one pending breakpoint) can be active
        at a time, so this doesn't need a run/breakpoint id to disambiguate.

        Args:
            proceed: True to continue the protocol, False to abort it.

        Returns:
            Request to resolve the pending breakpoint.
        """
        return self.gen_request("run.confirm_breakpoint", {"proceed": proceed})

    def protocols_list(self) -> dict[str, Any]:
        """Build a request to list available protocol files.

        Returns:
            Request for the protocol list.
        """
        return self.gen_request("protocols.list")

    def daemon_ping(self) -> dict[str, Any]:
        """Build a health-check request.

        Returns:
            Request for daemon/Moonraker connectivity status.
        """
        return self.gen_request("daemon.ping")

    def identify(self, client_type: str) -> dict[str, Any]:
        """Build a one-time request identifying this connection's client type.

        Both ``RemoteTapShell`` and the kiosk send this once, right after
        connecting, hardcoded to their own fixed string ("tap"/"kiosk") --
        see issue #53. This is an audit-trail label for the RPC log, not
        access control: a connection that never identifies itself is still
        served, just logged as "unknown".

        Args:
            client_type: Fixed client-type string, e.g. "tap" or "kiosk".

        Returns:
            Request to identify this connection.
        """
        return self.gen_request("daemon.identify", {"client_type": client_type})

    def clients(self) -> dict[str, Any]:
        """Build a request listing currently-connected control-plane clients.

        A debugging aid built on the same ``ControlServer._clients`` map
        that #53's ``daemon.identify`` populates -- see issue #59. Reports
        one entry per open connection, each carrying only the client-type
        label ("tap"/"kiosk"/"unknown"); nothing beyond that is tracked.

        Returns:
            Request for the connected-client list.
        """
        return self.gen_request("daemon.clients")

    def run_stop(self) -> dict[str, Any]:
        """Build a request to send an emergency stop.

        Returns:
            Request to send the emergency stop.
        """
        return self.gen_request("run.stop")

    # ==================== WebSocket diagnostics ====================

    def ws_status(self) -> dict[str, Any]:
        """Build a request for the daemon's own Moonraker connection status.

        Returns:
            Request for WebSocket status.
        """
        return self.gen_request("ws.status")

    def ws_ping(self) -> dict[str, Any]:
        """Build a request to ping Moonraker directly.

        Returns:
            Request to ping Moonraker.
        """
        return self.gen_request("ws.ping")

    def ws_send(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build a request to send an arbitrary JSON-RPC request to Moonraker.

        Args:
            method: Moonraker JSON-RPC method name.
            params: Optional method parameters.

        Returns:
            Request to send the given method/params.
        """
        return self.gen_request("ws.send", {"method": method, "params": params})

    def ws_notify(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build a request to send a fire-and-forget notification to Moonraker.

        Args:
            method: Moonraker JSON-RPC method name.
            params: Optional method parameters.

        Returns:
            Request to send the given notification.
        """
        return self.gen_request("ws.notify", {"method": method, "params": params})

    def ws_subscribe(self, method: str) -> dict[str, Any]:
        """Build a request to subscribe to a raw Moonraker notification method.

        Args:
            method: Notification method name.

        Returns:
            Request to subscribe.
        """
        return self.gen_request("ws.subscribe", {"method": method})

    def ws_unsubscribe(self, method: str) -> dict[str, Any]:
        """Build a request to unsubscribe from a raw Moonraker notification method.

        Args:
            method: Notification method name.

        Returns:
            Request to unsubscribe.
        """
        return self.gen_request("ws.unsubscribe", {"method": method})

    def ws_upload(self, file_name: str, file_path: str) -> dict[str, Any]:
        """Build a request to upload a G-code file (server-local path).

        Args:
            file_name: Name for the file on the server.
            file_path: Path to the file, local to the machine running the
                daemon (not necessarily the calling client's machine).

        Returns:
            Request to upload the file.
        """
        return self.gen_request(
            "ws.upload", {"file_name": file_name, "file_path": file_path}
        )

    def ws_read(self) -> dict[str, Any]:
        """Build a request to pop the next message from the WebSocket queue.

        Returns:
            Request to read one message.
        """
        return self.gen_request("ws.read")

    def ws_read_all(self) -> dict[str, Any]:
        """Build a request to drain all messages from the WebSocket queue.

        Returns:
            Request to read all messages.
        """
        return self.gen_request("ws.read_all")

    def ws_clear_queue(self) -> dict[str, Any]:
        """Build a request to discard all messages from the WebSocket queue.

        Returns:
            Request to clear the queue.
        """
        return self.gen_request("ws.clear_queue")

    def ws_reconnect(self) -> dict[str, Any]:
        """Build a request to reconnect the daemon's Moonraker WebSocket.

        Returns:
            Request to reconnect.
        """
        return self.gen_request("ws.reconnect")

    def ws_query_endstops(self) -> dict[str, Any]:
        """Build a request to query live endstop trigger state from Klipper.

        A thin, structured passthrough to Moonraker's own
        ``printer.query_endstops.status`` -- the same family as
        ``ws_status``/``ws_ping``, not domain/business logic.

        Returns:
            Request for the endstop states.
        """
        return self.gen_request("ws.query_endstops")

    # ==================== Reporting ====================

    def list_locations(self) -> dict[str, Any]:
        """Build a request to list all defined locations.

        Returns:
            Request for the location list.
        """
        return self.gen_request("config.list_locations")

    def list_plates(self) -> dict[str, Any]:
        """Build a request to list all defined plates.

        Returns:
            Request for the plate list.
        """
        return self.gen_request("config.list_plates")

    def list_liquids(self) -> dict[str, Any]:
        """Build a request to list all loaded liquid profiles.

        Returns:
            Request for the liquid list.
        """
        return self.gen_request("config.list_liquids")

    def system_summary(self) -> dict[str, Any]:
        """Build a request for a system configuration summary.

        Returns:
            Request for the system summary.
        """
        return self.gen_request("config.system_summary")
