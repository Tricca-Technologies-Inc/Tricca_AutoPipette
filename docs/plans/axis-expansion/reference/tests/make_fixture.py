#!/usr/bin/env python3
"""Build a "configs repo after CFG-1 (or CFG-3)" from a Tricca_Autopipette_Configs
checkout plus this plan's reference files, so the offline tests can run before
CFG-1 exists. Applies reference/klipper/printer.cfg.md and (for --stage 2)
stage2.patch.md mechanically.

Usage:
  make_fixture.py --configs <Tricca_Autopipette_Configs checkout> --out <dir>
                  [--stage 1|2]

Once CFG-1 is merged, run run_offline_tests.py against the real repo instead.
"""
import argparse, os, re, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "..", "klipper")
SECTION = r"^\[{name}\]\n(?:(?!\[).*\n?)*"


def drop_section(text, name):
    new, n = re.subn(SECTION.format(name=re.escape(name)), "", text, flags=re.M)
    if n != 1:
        raise SystemExit(f"expected one [{name}] section, found {n}")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", type=int, default=1, choices=[1, 2])
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    for f in ("printer.cfg", "mainsail.cfg", "tricca-autopipette.cfg"):
        shutil.copy(os.path.join(a.configs, f), a.out)
    for f in ("ebb-pipette.cfg", "octopus-plates.cfg", "plate-macros.cfg"):
        shutil.copy(os.path.join(REF, f), a.out)

    # printer.cfg: add the three includes after tricca-autopipette.cfg
    p = os.path.join(a.out, "printer.cfg")
    t = open(p).read()
    anchor = "[include tricca-autopipette.cfg]\n"
    if anchor not in t:
        raise SystemExit("printer.cfg: include anchor not found")
    t = t.replace(anchor, anchor + "[include ebb-pipette.cfg]\n"
                  "[include octopus-plates.cfg]\n[include plate-macros.cfg]\n", 1)
    open(p, "w").write(t)

    # tricca-autopipette.cfg: pipette sections move to the EBB file;
    # homing_override replaced by the reference section
    p = os.path.join(a.out, "tricca-autopipette.cfg")
    t = open(p).read()
    for name in ("manual_stepper pipette_stepper",
                 "tmc2209 manual_stepper pipette_stepper", "servo pipette_servo"):
        t = drop_section(t, name)
    ho = open(os.path.join(REF, "homing_override.cfg.txt")).read()
    ho = ho[ho.index("\n[homing_override]\naxes") + 1:]
    t = re.sub(SECTION.format(name="homing_override"), lambda m: ho.rstrip("\n") + "\n\n",
               t, count=1, flags=re.M)
    open(p, "w").write(t)

    if a.stage == 2:
        p = os.path.join(a.out, "plate-macros.cfg")
        t = open(p).read()
        t, n = re.subn(r"^variable_stage: 1$", "variable_stage: 2", t, flags=re.M)
        if n != 1:
            raise SystemExit("plate-macros.cfg: variable_stage not found")
        open(p, "w").write(t)
        p = os.path.join(a.out, "ebb-pipette.cfg")
        t = open(p).read()
        t, n = re.subn(r"^(rotation_distance: .*\n)", r"\1position_min: -60\nposition_max: 0\n",
                       t, count=1, flags=re.M)
        if n != 1:
            raise SystemExit("ebb-pipette.cfg: rotation_distance not found")
        open(p, "w").write(t)
    print(f"fixture (stage {a.stage}) written to {a.out}")


if __name__ == "__main__":
    main()
