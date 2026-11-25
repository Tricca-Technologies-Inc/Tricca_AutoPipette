"""Clients hear when a config change invalidates homing.

Klipper still reports the axes homed after a pipette/gantry swap, but
``require_homed`` refuses every move until the next full home. The Move
page's banner needs the daemon's view, so the flag rides ``run.status``
and a fresh ``notify_run_status`` push whenever it flips.
"""

from __future__ import annotations

from typing import Any

from tricca_autopipette.daemon.service import AutoPipetteService


def test_flipping_the_flag_pushes_the_status_once(
    service: AutoPipetteService,
) -> None:
    pushes: list[tuple[str, dict[str, Any]]] = []
    service.set_broadcast_callback(lambda m, p: pushes.append((m, p)))

    service._homing_invalidated = True
    service._homing_invalidated = True  # unchanged: no second push
    service._homing_invalidated = False

    assert [(m, p["homing_invalidated"]) for m, p in pushes] == [
        ("notify_run_status", True),
        ("notify_run_status", False),
    ]


def test_run_status_carries_the_flag(service: AutoPipetteService) -> None:
    service._homing_invalidated = True

    assert service.status_dict()["homing_invalidated"] is True
