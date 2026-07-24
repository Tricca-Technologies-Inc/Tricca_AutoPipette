"""Shared ``rich.table.Table`` builders for reporting commands.

Both ``commands/configuration_commands.py`` (``TriccaAutoPipetteShell``,
standalone) and ``cli/remote_shell.py`` (``RemoteTapShell``, talking to the
daemon) render the exact same structured data --
``AutoPipetteService.list_locations``/``list_plates``/``list_liquids``/
``system_summary``'s ``CommandResult.data`` -- so the table-building logic
lives here once rather than being duplicated per driving adapter.
"""

from __future__ import annotations

from typing import Any

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

    for row in liquids:
        viscosity = row.get("viscosity_cP")
        table.add_row(
            row["name"],
            "●" if row["active"] else "",
            f"{viscosity:.2f}" if viscosity else "—",
            "✓" if row["has_custom_speed"] else "",
            f"{row['prewet_cycles']}×" if row["prewet_cycles"] else "",
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
    table.add_row("  Max Volume", f"{data['max_volume_ul']} µL")
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
