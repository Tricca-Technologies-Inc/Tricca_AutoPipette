"""Dispatch-completeness test for ``ControlServer``.

Phase 5 of the ports-and-adapters migration -- see CLAUDE.md. Every
request builder on ``ControlRequests`` should have a matching branch in
``ControlServer._call`` -- this test calls each builder to get its
``method`` string, then dispatches that (with the builder's own params)
through a real ``ControlServer``, asserting the *specific* "Unknown
method" failure never happens. It doesn't assert the call succeeds (many
need a homed/connected pipette or real files) -- only that the method name
itself is recognized, so a future ``ControlRequests`` addition without a
matching ``_call`` branch is caught immediately instead of silently
falling through to "Unknown method" in production.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

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
    SetArgs,
    SetTipsArgs,
    TipsArgs,
    TriggerArgs,
    UnloadLocationsArgs,
    VolToStepsArgs,
    WaitArgs,
)
from tricca_autopipette.core.pipette_exceptions import AutoPipetteError
from tricca_autopipette.daemon.control_requests import ControlRequests
from tricca_autopipette.daemon.control_server import ControlServer
from tricca_autopipette.daemon.service import AutoPipetteService

# "save_locations" is dispatched for real, writing an actual file. The
# `service` fixture points location_manager.locations_dir at tmp_path, so
# it lands there rather than in the repo's config/locations/ (which is
# what previously left an untracked custom_locations.json behind after
# every test run).
_SCRATCH_LOCATIONS_FILENAME = "dispatch_completeness_scratch.json"

# Every ControlRequests builder that produces a request dict to dispatch,
# paired with the args needed to call it.
_BUILDER_CALLS: list[tuple[str, tuple[Any, ...]]] = [
    ("init", ()),
    ("home", (HomeArgs(motors="all"),)),
    ("move", (MoveArgs(x=1.0, y=1.0, z=1.0),)),
    ("move_loc", (MoveLocArgs(name_loc="bench", row=None, col=None),)),
    ("move_rel", (MoveRelArgs(x=1.0, y=0.0, z=0.0),)),
    (
        "aspirate",
        (
            AspirateArgs(
                vol_ul=10.0,
                source="bench",
                src_row=None,
                src_col=None,
                pre_air_gap_ul=0.0,
                post_air_gap_ul=0.0,
                prewet_cycles=0,
                prewet_vol_ul=0.0,
            ),
        ),
    ),
    (
        "dispense",
        (
            DispenseArgs(
                dest="bench",
                dest_row=None,
                dest_col=None,
                volume=10.0,
                wiggle=False,
            ),
        ),
    ),
    (
        "transfer",
        (
            PipetteArgs(
                vol_ul=10.0,
                source="bench",
                dest="bench",
                disp_vol_ul=None,
                src_row=None,
                src_col=None,
                dest_row=None,
                dest_col=None,
                tipbox_name=None,
                pre_air_gap_ul=0.0,
                post_air_gap_ul=0.0,
                prewet_cycles=0,
                prewet_vol_ul=0.0,
                wiggle=False,
                keep_tip=True,
                splits=None,
                leftover=None,
            ),
        ),
    ),
    ("next_tip", ()),
    ("eject_tip", ()),
    ("dispose_tip", ()),
    ("change_tip", ()),
    ("switch_liquid", ("methanol",)),
    ("load_liquid", ("water.json",)),
    ("set", (SetArgs(var="SPEED_FACTOR", value=100.0),)),
    ("coor", (CoorArgs(name="bench", x=1.0, y=1.0, z=1.0),)),
    (
        "plate",
        (
            PlateArgs(
                name="p",
                plate_type="array",
                num_row=1,
                num_col=1,
                x=1.0,
                y=1.0,
                z=1.0,
                dip_top=1.0,
                dip_btm=None,
                dip_func="simple",
                well_diameter=None,
                spacing_row=1.0,
                spacing_col=1.0,
            ),
        ),
    ),
    ("reset_plate", (ResetPlateArgs(name="p"),)),
    ("reset_plates", ()),
    ("del_loc", (DelLocArgs(name="bench"),)),
    ("clear_locs", ()),
    ("save_locations", (_SCRATCH_LOCATIONS_FILENAME,)),
    ("load_locations", (LoadLocationsArgs(filename=_SCRATCH_LOCATIONS_FILENAME),)),
    ("unload_locations", (UnloadLocationsArgs(name="bench"),)),
    # The tip commands only need the method string to be routed; an unknown
    # tipbox name comes back as ok=False rather than raising, which is exactly
    # what this test asserts is *not* an unrecognized-method error.
    ("reset_tips", (ResetTipsArgs(name="tipbox"),)),
    ("reset_tips_all", ()),
    ("set_tips", (SetTipsArgs(name="tipbox", ranges=["A1"]),)),
    ("tips", (TipsArgs(),)),
    ("wait", (WaitArgs(ms=1.0),)),
    ("trigger", (TriggerArgs(channel="air", state="on"),)),
    ("gcode_print", (GcodePrintArgs(msg="hi"),)),
    ("webcam_url", ()),
    ("vol_to_steps", (VolToStepsArgs(vol=10.0),)),
    ("steps_to_vol", (100,)),
    ("run_start", ("does_not_exist.pipette",)),
    ("run_status", ()),
    ("run_cancel", ()),
    ("run_pause", ()),
    ("run_resume", ()),
    ("run_confirm_breakpoint", (True,)),
    ("protocols_list", ()),
    ("daemon_ping", ()),
    ("identify", ("tap",)),
    ("clients", ()),
    ("run_stop", ()),
    ("ws_status", ()),
    ("ws_ping", ()),
    ("ws_send", ("server.info", None)),
    ("ws_notify", ("server.info", None)),
    ("ws_subscribe", ("notify_status_update",)),
    ("ws_unsubscribe", ("notify_status_update",)),
    ("ws_upload", ("f.gcode", "/tmp/f.gcode")),
    ("ws_read", ()),
    ("ws_read_all", ()),
    ("ws_clear_queue", ()),
    ("ws_reconnect", ()),
    ("list_locations", ()),
    ("list_plates", ()),
    ("list_liquids", ()),
    ("system_summary", ()),
]


def test_builder_call_table_matches_control_requests_exactly() -> None:
    """`_BUILDER_CALLS` above must cover every `ControlRequests` builder.

    Guards the completeness check itself: without this, a newly-added
    `ControlRequests` builder that nobody added to `_BUILDER_CALLS` would
    just never get checked, silently defeating the point of this file.
    """
    non_builder_attrs = {"gen_request", "JSON_RPC_VERSION"}
    builder_names = {
        name
        for name in dir(ControlRequests)
        if not name.startswith("_") and name not in non_builder_attrs
    }
    covered_names = {name for name, _ in _BUILDER_CALLS}

    missing = builder_names - covered_names
    assert not missing, (
        f"_BUILDER_CALLS is missing coverage for: {sorted(missing)} -- "
        "add an entry so dispatch completeness is actually checked for it."
    )
    stale = covered_names - builder_names
    assert not stale, (
        f"_BUILDER_CALLS references builders that no longer exist: "
        f"{sorted(stale)} -- ControlRequests must have been renamed/removed."
    )


@pytest.mark.parametrize(
    "name,args", _BUILDER_CALLS, ids=[n for n, _ in _BUILDER_CALLS]
)
def test_builder_method_is_dispatchable(
    name: str, args: tuple[Any, ...], service: AutoPipetteService
) -> None:
    """Each builder's ``method`` string must be recognized by ``_call``.

    Doesn't assert the call *succeeds* -- many need a homed/connected
    pipette, an existing file, or other preconditions this fixture's bare
    unconnected service doesn't have. Only asserts dispatch doesn't fall
    through to the generic "Unknown method" branch, which is the one
    failure mode this test exists to catch (a `ControlRequests` builder
    added without a matching `_call` branch).
    """
    requests = ControlRequests()
    builder = getattr(requests, name)
    request = builder(*args)
    server = ControlServer(service)

    try:
        asyncio.run(server._call(request["method"], request.get("params") or {}))
    except ValueError as exc:
        if str(exc).startswith("Unknown method:"):
            pytest.fail(
                f"ControlServer._call has no branch for '{request['method']}' "
                f"(built by ControlRequests.{name}())"
            )
        # Any other ValueError (e.g. a real validation error) means the
        # method WAS recognized -- that's what this test checks for.
    except (AutoPipetteError, FileNotFoundError, RuntimeError):
        # Reaching a real precondition failure (unhomed pipette, missing
        # file, no WebSocket client) means dispatch found the right branch
        # and got as far as calling into the service -- a pass here.
        #
        # Deliberately NOT a bare `except Exception`: `_call` unpacks
        # params by name (`HomeArgs(**params)`, `params["liquid_name"]`,
        # ...), so a builder whose param keys drift out of step with its
        # `_call` branch fails with TypeError/KeyError. That is the other
        # half of the drift this file exists to catch, and a catch-all
        # would swallow it.
        pass
