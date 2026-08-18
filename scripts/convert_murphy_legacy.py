#!/usr/bin/env python3
"""One-time conversion: legacy Murphy .conf/.pipette files -> the JSON
config tree + current .pipette grammar.

Kept as a historical record of exactly how ``config/{pipettes,locations,
liquids,system}/murphy_*`` and ``protocols/legacy/`` were produced from the
old `cmd2`-shell-era ``Murphy-100.conf``/``Murphy-1000.conf`` and their
``.pipette`` files (see ``protocols/legacy/README.md`` for the resulting
flag-mapping table and caveats). Not meant to be re-run blindly -- it
encodes machine-classification and flag-mapping judgment calls that were
reviewed by hand against the actual parser/location-manager code, not just
generic rules. Re-derive those if the source files change materially.

Reads from ~/Documents/prots-n-conf-to-be-converted/{conf,protocols} (the
original, since-superseded location of these files) and writes to OUT_ROOT;
review the diff before copying anything into config/ or protocols/.
"""
from __future__ import annotations

import configparser
import json
import re
import shutil
from pathlib import Path

SRC_ROOT = Path("/home/james/Documents/prots-n-conf-to-be-converted")
OUT_ROOT = Path("/tmp/murphy_legacy_conversion_out")

MACHINES = {
    "murphy_100": SRC_ROOT / "conf" / "Murphy-100.conf",
    "murphy_1000": SRC_ROOT / "conf" / "Murphy-1000.conf",
}

DIP_FUNC_MAP = {
    "cylinder": "cylinder",
    "fstube": "cylinder",  # FStube isn't a registered strategy in the new
                            # system; it has the same required params
                            # (dip_top, dip_btm, well_diameter) as cylinder.
    "simple": "simple",
}


def parse_conf(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
    cp.read(path, encoding="utf-8")
    return cp


def fnum(s: str) -> float:
    return float(s.strip())


def is_number(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def clean_num(v: float) -> float | int:
    """Emit ints as ints for cleaner JSON when the value is integral."""
    if float(v).is_integer():
        return int(v)
    return v


def build_gantry(cp: configparser.ConfigParser) -> dict:
    sp = cp["SPEED"]
    accel_max = clean_num(fnum(sp["accel_max"]))
    return {
        "speed_xy": clean_num(fnum(sp["speed_xy"])),
        "speed_z": clean_num(fnum(sp["speed_z"])),
        "speed_max": clean_num(fnum(sp["speed_max"])),
        "accel_xy": accel_max,
        "accel_z": accel_max,
        "accel_max": accel_max,
    }


def build_pipette(cp: configparser.ConfigParser, display_name: str) -> dict:
    name_sec = cp["NAME"]
    sp = cp["SPEED"]
    servo = cp["SERVO"]
    wait = cp["WAIT"]
    vol = cp["VOLUME_CONV"]

    volumes = [fnum(v) for v in vol["volumes"].split(",")]
    steps = [fnum(v) for v in vol["steps"].split(",")]
    max_vol = fnum(vol["max_vol"])

    # Legacy aspirate always plunges at speed_pipette_up_slow; dispense at
    # speed_pipette_down by default (speed_pipette_up_slow if --serum_speed).
    # Legacy hardcodes ACCEL=800 for the manual stepper move regardless of
    # conf -- matches this schema's accel_home/accel_move default already.
    return {
        "name": display_name,
        "manufacturer": "Tricca",
        "description": f"Converted from legacy {display_name}.conf",
        "design_type": "vertical",
        "syringe": {
            "syringe_model": display_name,
            "stepper_name": name_sec["name_pipette_stepper"],
            "motor_orientation": -1,
            "max_volume_ul": clean_num(max_vol),
            "min_volume_ul": 1.0,
            "capacity_margin_ul": 2.0,
            "calibration_volumes": volumes,
            "calibration_steps": steps,
            "speed_aspirate": clean_num(fnum(sp["speed_pipette_up_slow"])),
            "speed_dispense": clean_num(fnum(sp["speed_pipette_down"])),
            "accel_home": 800.0,
            "accel_move": 800.0,
            "wait_aspirate_ms": int(fnum(wait["wait_aspirate"])),
            "wait_dispense_ms": int(fnum(wait["wait_aspirate"])),
        },
        "servo": {
            "name": name_sec["name_pipette_servo"],
            "angle_retract": int(fnum(servo["servo_angle_retract"])),
            "angle_eject": int(fnum(servo["servo_angle_ready"])),
            "wait_ms": int(fnum(wait["wait_eject"])),
        },
        "compatible_tips": [],
    }


def build_locations(cp: configparser.ConfigParser) -> dict:
    plates = []
    for section in cp.sections():
        if not section.startswith("PLATE "):
            continue
        name = section[len("PLATE "):].strip()
        s = cp[section]
        plate: dict = {
            "name": name,
            "type": s.get("type", "array"),
            "x": clean_num(fnum(s["x"])),
            "y": clean_num(fnum(s["y"])),
            "z": clean_num(fnum(s["z"])),
        }
        if "row" in s:
            plate["num_row"] = int(fnum(s["row"]))
        if "col" in s:
            plate["num_col"] = int(fnum(s["col"]))
        if "spacing_row" in s:
            plate["spacing_row"] = clean_num(fnum(s["spacing_row"]))
        if "spacing_col" in s:
            plate["spacing_col"] = clean_num(fnum(s["spacing_col"]))
        if "dip_top" in s:
            plate["dip_top"] = clean_num(fnum(s["dip_top"]))
        if "dip_btm" in s:
            plate["dip_btm"] = clean_num(fnum(s["dip_btm"]))
        if "dip_func" in s:
            raw = s["dip_func"].strip().lower()
            plate["dip_func"] = DIP_FUNC_MAP.get(raw, raw)
        if "well_diameter" in s:
            plate["well_diameter"] = clean_num(fnum(s["well_diameter"]))
        plates.append(plate)
    return {"plates": plates}


def build_system(display_name: str, pipette_key: str, locations_file: str) -> dict:
    return {
        "version": "1.0",
        "system_name": display_name,
        "gantry": None,  # filled by caller (shared block)
        "pipette": pipette_key,
        "liquids": {},
        "locations": locations_file,
        "network": {
            "hostname": "triccaautopipette02.local",
            "port": "7125",
        },
    }


COMMENT_RE = re.compile(r"^\(\*\s*(.*?)\s*\*\)\s*$")
FLAG_WITH_VALUE = {
    "--dest_row", "--dest_col", "--src_row", "--src_col",
    "--dispense_vol", "-d", "--tipbox",
}


def tokenize(line: str) -> list[str]:
    return line.split()


def fmt_num(x: str) -> str:
    """Normalize a numeric token's text (drop trailing .0 noise is NOT done;
    we just pass through what the source wrote, trimming whitespace)."""
    return x.strip()


class ConvertResult:
    def __init__(self):
        self.lines: list[str] = []
        self.used_serum = False
        self.used_touch = False
        self.bare_prewet = 0
        self.unresolved_names: set[str] = set()
        self.typo_reset = 0
        self.unhandled: list[str] = []


def convert_pipette_line(toks: list[str], ext_air: str, aft_air: str, res: ConvertResult) -> list[str]:
    """Convert one legacy `pipette ...` line's tokens into 1-3 new lines."""
    # positionals in the source: first token after 'pipette' that isn't a
    # flag/flag-value is vol_ul; the next two non-flag tokens are source/dest,
    # in whatever order they appear (legacy interleaves flags and positionals
    # freely; argparse resolves them by position among non-flag tokens).
    assert toks[0] == "pipette"
    i = 1
    positionals: list[str] = []
    flags: dict[str, str | bool] = {}
    while i < len(toks):
        t = toks[i]
        if t.startswith("--") or t == "-d":
            key = "--dispense_vol" if t == "-d" else t
            if t == "--prewet":
                # value is optional: a bare '--prewet' (no cycle count) is
                # itself present in the corpus and must stay bare.
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                if nxt is not None and not nxt.startswith("--") and is_number(nxt):
                    flags[key] = nxt
                    i += 2
                else:
                    flags[key] = True
                    i += 1
            elif t in FLAG_WITH_VALUE:
                val = toks[i + 1] if i + 1 < len(toks) else ""
                flags[key] = val
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            positionals.append(t)
            i += 1

    if len(positionals) < 3:
        res.unhandled.append(" ".join(toks))
        return [" ".join(toks)]

    vol_ul, source, dest = positionals[0], positionals[1], positionals[2]

    for name in (source, dest):
        res.unresolved_names.add(name)  # filled in / checked by caller

    out_flags: list[str] = []

    if "--dispense_vol" in flags:
        out_flags += ["--dispense_vol", str(flags["--dispense_vol"])]
    if "--src_row" in flags:
        out_flags += ["--src_row", str(flags["--src_row"])]
    if "--src_col" in flags:
        out_flags += ["--src_col", str(flags["--src_col"])]
    if "--dest_row" in flags:
        out_flags += ["--dest_row", str(flags["--dest_row"])]
    if "--dest_col" in flags:
        out_flags += ["--dest_col", str(flags["--dest_col"])]
    if "--tipbox" in flags:
        out_flags += ["--tipbox", str(flags["--tipbox"])]

    if "--extra_air" in flags:
        out_flags += ["--pre_air_gap", ext_air]
    if "--after_air" in flags:
        out_flags += ["--post_air_gap", aft_air]

    if "--prewet" in flags:
        pv = flags["--prewet"]
        if pv is True:
            res.bare_prewet += 1
            cycles = "1"
        else:
            cycles = str(pv)
        out_flags += ["--prewet", cycles, "--prewet_vol", vol_ul]

    if "--wiggle" in flags:
        out_flags.append("--wiggle")
    if "--keep_tip" in flags:
        out_flags.append("--keep_tip")
    if "--touch" in flags:
        res.used_touch = True  # dropped: dead code even in the legacy impl

    line = " ".join(["pipette", vol_ul, source, dest] + out_flags)

    if "--serum_speed" in flags:
        res.used_serum = True
        return ["switch_liquid serum", line, "switch_liquid water"]
    return [line]


def convert_protocol(text: str, ext_air: str, aft_air: str) -> tuple[str, ConvertResult]:
    res = ConvertResult()
    out_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        m = COMMENT_RE.match(stripped)
        if m:
            out_lines.append(f"# {m.group(1)}".rstrip())
            continue
        if stripped.startswith("#"):
            out_lines.append(stripped)
            continue
        toks = tokenize(stripped)
        cmd = toks[0]
        if cmd == "pipette":
            out_lines.extend(convert_pipette_line(toks, ext_air, aft_air, res))
        elif cmd == "reset_plate":
            out_lines.append(stripped)
            if len(toks) > 1:
                res.unresolved_names.add(toks[1])
        elif cmd == "reset":
            res.typo_reset += 1
            new = "reset_plate " + " ".join(toks[1:])
            out_lines.append(new)
            if len(toks) > 1:
                res.unresolved_names.add(toks[1])
        elif cmd == "home":
            out_lines.append(stripped)
        else:
            res.unhandled.append(stripped)
            out_lines.append(stripped)
    return "\n".join(out_lines) + "\n", res


def main():
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    (OUT_ROOT / "config" / "pipettes").mkdir(parents=True)
    (OUT_ROOT / "config" / "locations").mkdir(parents=True)
    (OUT_ROOT / "config" / "liquids").mkdir(parents=True)
    (OUT_ROOT / "config" / "system").mkdir(parents=True)
    (OUT_ROOT / "protocols" / "legacy" / "murphy_100").mkdir(parents=True)
    (OUT_ROOT / "protocols" / "legacy" / "murphy_1000").mkdir(parents=True)

    machine_data = {}
    plate_names: dict[str, set[str]] = {}
    ext_aft: dict[str, tuple[str, str]] = {}

    for key, conf_path in MACHINES.items():
        cp = parse_conf(conf_path)
        display = "Murphy-100" if key == "murphy_100" else "Murphy-1000"

        gantry = build_gantry(cp)
        pipette = build_pipette(cp, display)
        locations = build_locations(cp)

        (OUT_ROOT / "config" / "pipettes" / f"{key}.json").write_text(
            json.dumps(pipette, indent=2) + "\n"
        )
        (OUT_ROOT / "config" / "locations" / f"{key}_deck.json").write_text(
            json.dumps(locations, indent=2) + "\n"
        )

        system = build_system(display, key, f"{key}_deck.json")
        system["gantry"] = gantry
        (OUT_ROOT / "config" / "system" / f"{key}_system.json").write_text(
            json.dumps(system, indent=2) + "\n"
        )

        machine_data[key] = {"cp": cp, "locations": locations}
        plate_names[key] = {p["name"] for p in locations["plates"]}

        wait = cp["WAIT"]
        ext_aft[key] = (wait["ext_air"].strip(), wait["aft_air"].strip())

    # shared serum liquid profile: speed_pipette_up_slow == 30 for both confs
    serum = {
        "name": "serum",
        "description": (
            "Slow dispense for viscous/serum samples (converted from legacy "
            "--serum_speed flag)."
        ),
        "viscosity_cP": None,
        "density_g_ml": None,
        "speed_aspirate": None,
        "speed_dispense": 30.0,
        "wait_aspirate_ms": None,
        "wait_dispense_ms": None,
        "prewet_cycles": None,
        "prewet_vol_ul": None,
        "pre_air_gap_ul": None,
        "post_air_gap_ul": None,
        "calibration_volumes": None,
        "calibration_steps": None,
    }
    (OUT_ROOT / "config" / "liquids" / "serum.json").write_text(
        json.dumps(serum, indent=2) + "\n"
    )

    only_100 = plate_names["murphy_100"] - plate_names["murphy_1000"]
    only_1000 = plate_names["murphy_1000"] - plate_names["murphy_100"]

    report = {
        "murphy_100_only_plates": sorted(only_100),
        "murphy_1000_only_plates": sorted(only_1000),
        "shared_plates": sorted(plate_names["murphy_100"] & plate_names["murphy_1000"]),
        "files": {},
    }

    protocols_dir = SRC_ROOT / "protocols"
    for pf in sorted(protocols_dir.glob("*.pipette")):
        text = pf.read_text(encoding="utf-8", errors="replace")
        # classify
        raw_names = set()
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("(*"):
                continue
            toks = s.split()
            if toks[0] == "pipette":
                i = 1
                positionals = []
                while i < len(toks):
                    t = toks[i]
                    if t.startswith("--") or t == "-d":
                        if t == "--prewet":
                            nxt = toks[i + 1] if i + 1 < len(toks) else None
                            i += 2 if (nxt is not None and not nxt.startswith("--") and is_number(nxt)) else 1
                        elif t in FLAG_WITH_VALUE or t == "-d":
                            i += 2
                        else:
                            i += 1
                    else:
                        positionals.append(t)
                        i += 1
                if len(positionals) >= 3:
                    raw_names.add(positionals[1])
                    raw_names.add(positionals[2])
            elif toks[0] in ("reset_plate", "reset") and len(toks) > 1:
                raw_names.add(toks[1])

        hits_100 = raw_names & only_100
        hits_1000 = raw_names & only_1000
        undefined = raw_names - plate_names["murphy_100"] - plate_names["murphy_1000"]

        if hits_100 and hits_1000:
            machine = "murphy_100"
            classification = "CONFLICT (references both machines' exclusive plates)"
        elif hits_100:
            machine = "murphy_100"
            classification = "murphy_100 (exclusive plate match)"
        elif hits_1000:
            machine = "murphy_1000"
            classification = "murphy_1000 (exclusive plate match)"
        else:
            machine = "murphy_100"
            classification = "AMBIGUOUS (shared-only plates, defaulted to murphy_100)"

        ext_air, aft_air = ext_aft[machine]
        converted, res = convert_protocol(text, ext_air, aft_air)

        out_path = OUT_ROOT / "protocols" / "legacy" / machine / pf.name
        out_path.write_text(converted)

        report["files"][pf.name] = {
            "classification": classification,
            "machine": machine,
            "used_serum": res.used_serum,
            "used_touch": res.used_touch,
            "bare_prewet": res.bare_prewet,
            "typo_reset_fixed": res.typo_reset,
            "undefined_location_names": sorted(undefined),
            "unhandled_lines": res.unhandled,
        }

    (OUT_ROOT / "conversion_report.json").write_text(json.dumps(report, indent=2))
    print("Done. Output at", OUT_ROOT)
    print("Files converted:", len(report["files"]))
    ambiguous = [f for f, d in report["files"].items() if "AMBIGUOUS" in d["classification"]]
    conflict = [f for f, d in report["files"].items() if "CONFLICT" in d["classification"]]
    undefined_files = [f for f, d in report["files"].items() if d["undefined_location_names"]]
    unhandled_files = [f for f, d in report["files"].items() if d["unhandled_lines"]]
    print("Ambiguous (defaulted to murphy_100):", len(ambiguous))
    for f in ambiguous:
        print("  -", f)
    print("Conflicts:", len(conflict))
    for f in conflict:
        print("  -", f)
    print("Files with undefined location names:", len(undefined_files))
    for f in undefined_files:
        print("  -", f, report["files"][f]["undefined_location_names"])
    print("Files with unhandled lines:", len(unhandled_files))
    for f in unhandled_files:
        print("  -", f, report["files"][f]["unhandled_lines"])
    serum_files = [f for f, d in report["files"].items() if d["used_serum"]]
    print("Files using serum_speed:", len(serum_files))
    touch_files = [f for f, d in report["files"].items() if d["used_touch"]]
    print("Files using --touch (dropped):", len(touch_files))
    bare_prewet_files = {f: d["bare_prewet"] for f, d in report["files"].items() if d["bare_prewet"]}
    print("Files with bare --prewet (defaulted to 1 cycle):", bare_prewet_files)
    typo_files = {f: d["typo_reset_fixed"] for f, d in report["files"].items() if d["typo_reset_fixed"]}
    print("Files with 'reset' typo fixed to 'reset_plate':", typo_files)


if __name__ == "__main__":
    main()
