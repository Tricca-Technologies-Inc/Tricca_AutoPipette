"""Report tables must style cells without Rich markup (issue #174).

cmd2's ``poutput`` prints with ``markup=False``, so any ``[red]``-style markup
in a cell is printed literally. Render each table the same way and check.
"""

from __future__ import annotations

import io
import re

from rich.console import Console
from rich.table import Table

from tricca_autopipette.cli.report_tables import (
    build_drawer_status_table,
    build_system_table,
)

_MARKUP = re.compile(r"\[/?(bold|red|green|yellow)\]")


def _render_like_cmd2(table: Table) -> str:
    out = io.StringIO()
    Console(file=out, markup=False, width=200).print(table)
    return out.getvalue()


def _system_data(**extra: object) -> dict[str, object]:
    return {
        "system_name": "nick",
        "version": "1",
        "pipette_model": "murphy",
        "pipette_design": "syringe",
        "max_volume_ul": 100,
        "active_liquid": "water",
        "gantry_speed_xy": 1000,
        "gantry_speed_z": 500,
        "gantry_accel_max": 1000,
        "hostname": "nick",
        "port": 80,
        **extra,
    }


def test_system_table_section_headings_render_without_markup() -> None:
    text = _render_like_cmd2(build_system_table(_system_data()))

    assert not _MARKUP.search(text)
    for heading in ("Pipette", "Active Liquid", "Gantry", "Network", "Plates"):
        assert heading in text


def test_system_table_with_plates_renders_without_markup() -> None:
    axes = {
        "z_safe": 0.0,
        "park_tol": 0.1,
        "plates": [
            {
                "name": "plate4",
                "letter": "A",
                "position_min": 0.0,
                "position_max": 350.0,
                "safe_stops": [0.0, 350.0],
            }
        ],
        "pipette": {
            "letter": "P",
            "stage": 1,
            "position_min": None,
            "position_max": None,
        },
    }
    text = _render_like_cmd2(build_system_table(_system_data(extra_axes=axes)))

    assert not _MARKUP.search(text)
    assert "Plunger axis" in text


def test_drawer_status_yes_no_render_without_markup() -> None:
    rows = [
        {
            "name": "plate1",
            "letter": "U",
            "homed": False,
            "position": None,
            "stop": None,
            "tip_safe": False,
        },
        {
            "name": "plate4",
            "letter": "A",
            "homed": True,
            "position": 0.0,
            "stop": "in",
            "tip_safe": True,
        },
    ]
    text = _render_like_cmd2(build_drawer_status_table(rows))

    assert not _MARKUP.search(text)
    assert "yes" in text
    assert "no" in text
