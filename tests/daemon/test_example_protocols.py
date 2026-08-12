"""End-to-end execution tests for the real ``protocols/examples/*.pipette``

files documented in ``docs/protocol-authoring.md``. Unlike
``tests/daemon/test_service_protocol_run.py`` (which exercises the dispatch
machinery against small synthetic fixtures under ``tests/fixtures/
protocols/``), this runs the actual committed example files against the
real ``protocols/`` and ``config/locations/`` directories -- proving every
example genuinely executes cleanly end-to-end, not merely that it parses.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fakes.fake_moonraker_state import FakeMoonrakerState

from tricca_autopipette.core.pipette_constants import DefaultPaths
from tricca_autopipette.daemon.service import AutoPipetteService, ProtocolAbortedError

_EXAMPLES = [
    "examples/home_and_move.pipette",
    "examples/simple_transfer.pipette",
    "examples/multi_liquid.pipette",
    "examples/splits.pipette",
    "examples/breakpoint.pipette",
]


@pytest.fixture
def example_service(service: AutoPipetteService) -> AutoPipetteService:
    """The ``service`` fixture, pointed at the real ``config/locations/``.

    ``service`` redirects ``location_manager.locations_dir`` to ``tmp_path``
    so ordinary tests can't leave stray files in the repo -- but these
    examples' first line is ``load_locations examples_deck.json``, which
    must resolve against the real committed
    ``config/locations/examples_deck.json``. Also pre-homes the fake
    Moonraker state, since every example after ``home_and_move.pipette``
    assumes the machine is already homed (matching real usage -- see
    ``docs/protocol-authoring.md``).

    Returns:
        The same ``service``, mutated in place.
    """
    service._autopipette.location_manager.locations_dir = (
        DefaultPaths.DIR_CONFIG_LOCATIONS
    )
    assert isinstance(service.moonraker_state, FakeMoonrakerState)
    service.moonraker_state.set_homed(True)
    return service


@pytest.mark.parametrize("filename", _EXAMPLES, ids=_EXAMPLES)
def test_example_protocol_runs_cleanly(
    filename: str, example_service: AutoPipetteService
) -> None:
    """Every committed example executes without raising.

    ``breakpoint.pipette``'s ``break`` line is answered "continue" here, so
    the whole file runs; ``test_breakpoint_example_aborts_cleanly`` below
    covers the "abort" path separately.
    """
    with patch.object(example_service, "request_breakpoint", return_value=True):
        example_service._run_protocol_sync(filename)


def test_breakpoint_example_aborts_cleanly(
    example_service: AutoPipetteService,
) -> None:
    """Answering ``breakpoint.pipette``'s break with "abort" stops the run.

    The lines after ``break`` (the transfer and disposal) must not run --
    there's no direct way to observe that from here, but a clean
    ``ProtocolAbortedError`` (rather than some other exception from a line
    that shouldn't have executed) is the closest black-box proxy available.
    """
    with (
        patch.object(example_service, "request_breakpoint", return_value=False),
        pytest.raises(ProtocolAbortedError),
    ):
        example_service._run_protocol_sync("examples/breakpoint.pipette")
