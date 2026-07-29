"""Shared ``rich.table.Table`` builders for reporting commands.

Both ``commands/configuration_commands.py`` (``TriccaAutoPipetteShell``,
standalone) and ``cli/remote_shell.py`` (``RemoteTapShell``, talking to the
daemon) render the exact same structured data --
``AutoPipetteService.list_locations``/``list_plates``/``list_liquids``/
``system_summary``'s ``CommandResult.data`` -- so the table-building logic
lives here once rather than being duplicated per driving adapter.
"""

from __future__ import annotations

import string
from typing import Any, cast

from rich.table import Table


def build_locations_table(locations: list[dict[str, Any]]) -> Table:
    """Build a table of all defined locations (coordinates and plates).

    Args:
        locations: ``AutoPipetteService.list_locations``'s
            ``data["locations"]``.

    Returns:
        A populated Table.
    """
    table = Table(title="All Locations", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("X", justify="right")
    table.add_column("Y", justify="right")
    table.add_column("Z", justify="right")
    table.add_column("Details", style="dim")

    for row in locations:
        table.add_row(
            row["name"],
            row["type"],
            f"{row['x']:.2f}" if row["x"] is not None else "—",
            f"{row['y']:.2f}" if row["y"] is not None else "—",
            f"{row['z']:.2f}" if row["z"] is not None else "—",
            row["details"],
        )
    return table


def build_plates_table(plates: list[dict[str, Any]]) -> Table:
    """Build a table of all defined plates.

    Args:
        plates: ``AutoPipetteService.list_plates``'s ``data["plates"]``.

    Returns:
        A populated Table.
    """
    table = Table(title="Defined Plates", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Dimensions", justify="center")
    table.add_column("Current", justify="center")
    table.add_column("Wells", justify="right")

    for row in plates:
        table.add_row(
            row["name"],
            row["type"],
            row["dimensions"],
            row["current"],
            str(row["wells"]),
        )
    return table


def build_liquids_table(liquids: list[dict[str, Any]]) -> Table:
    """Build a table of all loaded liquid profiles.

    Args:
        liquids: ``AutoPipetteService.list_liquids``'s ``data["liquids"]``.

    Returns:
        A populated Table.
    """
    table = Table(title="Available Liquid Profiles", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Active", style="green", justify="center")
    table.add_column("Viscosity (cP)", justify="right")
    table.add_column("Custom Speed", justify="center")
    table.add_column("Prewet", justify="center")
    table.add_column("Air gap (μL)", justify="center")

    for row in liquids:
        viscosity = row.get("viscosity_cP")
        pre_gap = row.get("pre_air_gap_ul")
        post_gap = row.get("post_air_gap_ul")
        table.add_row(
            row["name"],
            "●" if row["active"] else "",
            f"{viscosity:.2f}" if viscosity else "—",
            "✓" if row["has_custom_speed"] else "",
            f"{row['prewet_cycles']}×" if row["prewet_cycles"] else "",
            f"{pre_gap or 0:g}/{post_gap or 0:g}" if pre_gap or post_gap else "",
        )
    return table


def build_system_table(data: dict[str, Any]) -> Table:
    """Build a summary table of the system configuration.

    Args:
        data: ``AutoPipetteService.system_summary``'s ``data``.

    Returns:
        A populated Table.
    """
    table = Table(title="System Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("System Name", data["system_name"])
    table.add_row("Version", data["version"])
    table.add_row("", "")
    table.add_row("[bold]Pipette[/bold]", "")
    table.add_row("  Model", data["pipette_model"])
    table.add_row("  Design", data["pipette_design"])
    table.add_row("  Max Volume", f"{data['max_volume_ul']} μL")
    table.add_row("", "")
    table.add_row("[bold]Active Liquid[/bold]", data["active_liquid"])
    table.add_row("", "")
    table.add_row("[bold]Gantry[/bold]", "")
    table.add_row("  Speed XY", f"{data['gantry_speed_xy']} mm/min")
    table.add_row("  Speed Z", f"{data['gantry_speed_z']} mm/min")
    table.add_row("  Accel Max", f"{data['gantry_accel_max']} mm/s²")
    table.add_row("", "")
    table.add_row("[bold]Network[/bold]", "")
    table.add_row("  Hostname", data.get("hostname") or "—")
    table.add_row("  Port", str(data.get("port") or "—"))
    return table


#: Glyphs for the tip map. Chosen to stay legible in a terminal without
#: relying on color, since the map is also read over SSH and in logs.
TIP_PRESENT = "O"
TIP_CONSUMED = "."
TIP_MASKED = "x"
TIP_DRIFT = "!"


def build_tipbox_map(
    box: dict[str, Any], persisted: dict[str, Any] | None = None
) -> str:
    """Render one tipbox's occupancy as an ASCII plate map.

    Klipper has no notion of which tip positions are occupied, so this is the
    operator's view of what the daemon *believes* is on the deck -- pair it
    with ``set_tips``/``reset_tips`` to correct it when the belief is wrong.

    Args:
        box: One record from ``AutoPipetteService.tips``'s ``data["boxes"]``,
            as produced by ``TipBoxManager.describe``.
        persisted: The same box's record from Moonraker's database, when the
            caller asked to compare (``tips --db``). Positions that disagree
            with the live state are flagged, which is the whole point of the
            comparison -- a mismatch means a write was lost or the deck was
            changed out from under the daemon.

    Returns:
        A multi-line string: a header, a column-numbered grid, a legend, and
        the next position to be drawn.

    Example:
        >>> print(build_tipbox_map(service.tips(TipsArgs()).data["boxes"][0]))
        tipbox_a   84/96 remaining   order=column_from_bottom_right
        ...
    """
    num_row: int = box["num_row"]
    num_col: int = box["num_col"]
    present: list[bool] = box["present"]
    eligible = set(box["eligible"])

    stored: list[bool] | None = None
    if persisted is not None:
        candidate: object = persisted.get("present")
        # Only compare maps of the same shape; a reshaped box is reported by
        # the daemon at restore time rather than diffed cell by cell here.
        if isinstance(candidate, list):
            flags = cast("list[Any]", candidate)
            if len(flags) == len(present):
                stored = [bool(flag) for flag in flags]

    order = box["order"]
    lines = [
        f"{box['name']}   {box['remaining']}/{box['capacity']} remaining   "
        f"order={order}"
    ]

    width = max(2, len(str(num_col)))
    header = "    " + " ".join(f"{col + 1:>{width}}" for col in range(num_col))
    lines.append(header)

    drifted = False
    for row in range(num_row):
        cells: list[str] = []
        for col in range(num_col):
            index = row * num_col + col
            if index not in eligible:
                glyph = TIP_MASKED
            elif stored is not None and stored[index] != present[index]:
                glyph = TIP_DRIFT
                drifted = True
            else:
                glyph = TIP_PRESENT if present[index] else TIP_CONSUMED
            cells.append(f"{glyph:>{width}}")
        lines.append(f" {string.ascii_uppercase[row]:>2} " + " ".join(cells))

    legend = (
        f"  {TIP_PRESENT} present   {TIP_CONSUMED} consumed   {TIP_MASKED} masked out"
    )
    # Only advertise the drift glyph when one is actually on the map --
    # otherwise the legend implies a discrepancy that isn't there.
    if drifted:
        legend += f"   {TIP_DRIFT} differs from database"
    lines.append(legend)

    next_well = box.get("next_well")
    lines.append(f"  next -> {next_well}" if next_well else "  next -> (box empty)")

    return "\n".join(lines)
