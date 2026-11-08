#!/usr/bin/env python3
"""Offline Klipper tests for the AutoPipette config set (issue CFG-2).

Runs the pinned Klipper in batch mode (no boards) against a copy of the
config repo, one klippy process per case, and checks each case's errors
or reported state. Exits non-zero on any failure.

Usage:
  run_offline_tests.py --klipper <klipper checkout> --config <configs repo>
                       --dicts <dir> [--python <python with klippy deps>]
                       [--stage auto|1|2] [--keep]

--dicts must contain (built per WP1 section 7 at the pinned Klipper rev):
  m8p-bridge.dict  ebb42.dict  octopus.dict  host.dict

Before CFG-1 exists, build a config to test with make_fixture.py.

Batch-mode facts this harness relies on (verified at Klipper 7bc4d09):
  * CAN MCUs crash batch mode (canbus_bus_state enumeration), so every
    MCU is stubbed as "serial: /dev/null"; the dictionaries still define
    each board's commands and pins.
  * Homing moves never trigger early: each runs to its MOVE target and the
    position is set to that target. G28 sequencing can be tested; switch
    behaviour (release checks, direction, trigger point) cannot.
  * delayed_gcode does not fire before the input ends, so startup binding
    is tested by calling its body (_PIPETTE_BIND); the timer itself is
    checked on hardware (M-13).
  * Commands after an error still run, which lets every refusal case check
    that the state did not change. One process per case keeps cases
    independent.
"""
import argparse, glob, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

HOMED = "SET_KINEMATIC_POSITION X=150 Y=150 Z=0\n_T_HOME_ALL_PLATES\n"
PIPHOMED = ("MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0\n"
            "MANUAL_STEPPER STEPPER=pipette_stepper ENABLE=1\n"
            "SET_GCODE_VARIABLE MACRO=_PIPETTE_STATE VARIABLE=homed VALUE=1\n")
BIND = "_PIPETTE_BIND\n"
MID = HOMED + "G1 Z20 F600\nSAVE_GCODE_STATE NAME=low\nG1 Z0 F600\nG1 U100 F3000\n"  # tip was low, now raised; plate1 out to 100

# (id, gcode, expectation)
#   "refused:<text>"  an error containing <text>, and nothing moved (axis map
#                     and positions unchanged across the last command).
#                     Optional "&&<regex>": the state after must also match it
#   "range"           Klipper's "Move out of range"; state unchanged likewise
#   "noerror"         no error at all
#   "state:<regex>"   no error and a _T_STATE line matching <regex>
#   "inventory"       the registered commands equal command-inventory.txt
# Any template crash (a non-CommandError "Error evaluating") fails the case,
# and so does any log line that is neither on the BENIGN list nor part of the
# expected refusal (so an unexpected Klipper error can't pass silently).
COMMON = [
    ("C-02 G1 U10 with Z unhomed", "G1 U10\n", "refused:Z not homed"),
    ("C-03 G1 U10 with Z at 0 and plates homed", HOMED + "G1 U10 F3000\n_T_STATE\n",
     r"state:'U': 4.*?pos=\(150.0, 150.0, 0.0, 0.0, 10.0"),
    ("C-04 Z lowered, then G1 U10", HOMED + "G1 Z20 F600\nG1 U10\n", "refused:tip below safe height"),
    ("C-05 plate mid-travel, then G1 Z20", HOMED + "G1 U10 F3000\nG1 Z20\n", "refused:plate1 mid-travel"),
    ("C-06 plates parked (V fully out), G1 Z20", HOMED + "G1 V350 F3000\nG1 Z20 F600\n_T_STATE\n",
     r"state:pos=\(150.0, 150.0, 20.0"),
    ("C-07 G1 Z20 U0 in one move", HOMED + "G1 Z20 U0\n", "refused:tip below safe height"),
    ("C-08 raw MANUAL_STEPPER on a plate", HOMED + "MANUAL_STEPPER STEPPER=plate1 MOVE=5\n",
     "refused:use HOME_PLATE"),
    ("C-08b same with _PLATE_INTERNAL=1", HOMED +
     "MANUAL_STEPPER STEPPER=plate1 GCODE_AXIS= _PLATE_INTERNAL=1\n"
     "MANUAL_STEPPER STEPPER=plate1 MOVE=5 _PLATE_INTERNAL=1\n", "noerror"),
    ("C-09 G91 relative Z descent, plate mid-travel", HOMED + "G1 W5 F3000\nG91\nG1 Z5\n",
     "refused:plate3 mid-travel"),
    ("C-10 SET_GCODE_OFFSET Z=30 then G1 Z0, plate mid-travel", HOMED +
     "G1 A7 F3000\nSET_GCODE_OFFSET Z=30\nG1 Z0\n", "refused:plate4 mid-travel"),
    ("C-11 G0 U10 with Z lowered", HOMED + "G1 Z20 F600\nG0 U10\n", "refused:tip below safe height"),
    ("C-12 G1 U351", HOMED + "G1 U351\n", "range"),
    ("C-14b startup bind body binds P", BIND + "_T_STATE\n", r"state:'P': 4\}"),
    ("C-15 G1 P before plunger homing", BIND + "G1 P-5\n", "refused:plunger not homed"),
    ("C-19 M84 then G1 U5", HOMED + "M84\nSET_KINEMATIC_POSITION X=150 Y=150 Z=0\nG1 U5\n",
     "refused:plate1 not homed"),
    ("C-19c stepper off/on by hand then G1 U5", HOMED +
     'SET_STEPPER_ENABLE STEPPER="manual_stepper plate1" ENABLE=0\n'
     'SET_STEPPER_ENABLE STEPPER="manual_stepper plate1" ENABLE=1\nG1 U5\n',
     "refused:plate1 not homed"),
    ("C-21 G28 U with Z unhomed", "G28 U\n", "refused:home Z and raise"),
    ("C-22 bare G28 homes everything", "G28\n_T_STATE\n",
     r"state:'C': 9, 'P': 10\}.*pip_homed=1 homed=xyz plates=6"),
    ("C-23 G28 X Y homes the gantry only", "G28 X Y\n_T_STATE\n",
     r"state:\{'X': 0, 'Y': 1, 'Z': 2, 'E': 3\} pos=\(150.0, 150.0, 0.0.*pip_homed=0 homed=xy plates=0"),
    ("C-24 G28 P homes the plunger only", "G28 P\n_T_STATE\n",
     r"state:'P': 4\}.*pip_homed=1 homed= plates=0"),
    ("C-25 G92 P5 has no effect", "G28 P\nG92 P5\n_T_STATE\n",
     r"state:'P'.*0.0\) pip_homed=1"),
    # --- Rev J: non-G1 motion paths (review finding B-1, S-2) ---------------
    ("C-26 RESUME would lower the tip onto a mid-travel plate",
     HOMED + "G1 Z20 F600\nPAUSE\nG1 Z0 F600\nG1 U100 F3000\nRESUME\n", "refused:plate1 mid-travel"),
    ("C-26b RESUME with plates parked returns the tip",
     HOMED + "G1 Z20 F600\nPAUSE\nG1 Z0 F600\nRESUME\n_T_STATE\n", r"state:pos=\(150.0, 150.0, 20.0"),
    ("C-27 RESTORE_GCODE_STATE MOVE=1 onto a mid-travel plate",
     MID + "RESTORE_GCODE_STATE NAME=low MOVE=1\n", "refused:plate1 mid-travel"),
    ("C-27b RESTORE_GCODE_STATE MOVE=1 of an unknown state",
     HOMED + "RESTORE_GCODE_STATE NAME=nope MOVE=1\n", "refused:was not saved"),
    ("C-27c PLATE_MOVE still works (SAVE/RESTORE without MOVE)",
     HOMED + "PLATE_OUT PLATE=plate2\n_T_STATE\n", r"state:pos=\(150.0, 150.0, 0.0, 0.0, 0.0, 350.0"),
    ("C-28 SET_GCODE_OFFSET Z_ADJUST=20 MOVE=1, plate mid-travel",
     HOMED + "G1 U100 F3000\nSET_GCODE_OFFSET Z_ADJUST=20 MOVE=1\n", "refused:plate1 mid-travel"),
    ("C-28b SET_GCODE_OFFSET Z=20 MOVE=1, plate mid-travel",
     HOMED + "G1 U100 F3000\nSET_GCODE_OFFSET Z=20 MOVE=1\n", "refused:plate1 mid-travel"),
    ("C-28c SET_GCODE_OFFSET Z_ADJUST=5 MOVE=1, plates parked",
     HOMED + "SET_GCODE_OFFSET Z_ADJUST=5 MOVE=1\n_T_STATE\n", r"state:pos=\(150.0, 150.0, 5.0"),
    ("C-30 STEPPER_BUZZ on a plate with the tip low",
     HOMED + 'G1 Z20 F600\nSTEPPER_BUZZ STEPPER="manual_stepper plate1"\n', "refused:raise the tip"),
    ("C-30b STEPPER_BUZZ on a Z stepper, plate mid-travel",
     HOMED + "G1 U100 F3000\nSTEPPER_BUZZ STEPPER=stepper_z\n", "refused:plate1 mid-travel"),
    # --- Rev J: homed state can't be restored without homing (S-3, S-4) -----
    ("C-31 M84, re-enable via the base command, G1 U5", HOMED +
     'M84\nSET_KINEMATIC_POSITION X=150 Y=150 Z=0\n'
     'SET_STEPPER_ENABLE_BASE STEPPER="manual_stepper plate1" ENABLE=1\nG1 U5\n',
     "refused:plate1 not homed"),
    # --- Rev J: other review findings (N-3, N-4) -----------------------------
    ("C-33 G28 X on a cold machine (park only homed axes)", "G28 X\n_T_STATE\n",
     r"state:pos=\(150.0, 0.0, 0.0.*homed=x plates=0"),
    ("C-34 unbound plate flagged homed: clean refusal, no crash", HOMED +
     "MANUAL_STEPPER STEPPER=plate1 GCODE_AXIS= _PLATE_INTERNAL=1\nG1 Z20 F600\n",
     "refused:plate1 not homed"),
    ("C-35 lower-case g1 u10 with the tip low", HOMED + "G1 Z20 F600\ng1 u10\n",
     "refused:tip below safe height"),
    # --- Rev K: second review (R2-S-1, R2-N-1, -3, -12, -13) ------------------
    ("C-38 MANUAL_PROBE refused (TESTZ would bypass)", HOMED + "G1 U100 F3000\nMANUAL_PROBE\n",
     "refused:MANUAL_PROBE is disabled"),
    ("C-38b Z_ENDSTOP_CALIBRATE refused", HOMED + "G1 U100 F3000\nZ_ENDSTOP_CALIBRATE\n",
     "refused:Z_ENDSTOP_CALIBRATE is disabled"),
    ("C-40 SET_STEPPER_ENABLE ENABLE=0 on a Z stepper", HOMED +
     "SET_STEPPER_ENABLE STEPPER=stepper_z ENABLE=0\n", "refused:use M84"),
    ("C-41 refused PLATE_MOVE keeps relative mode", HOMED + "G91\nG1 Z20 F600\n"
     "PLATE_MOVE PLATE=plate1 POS=10\n", "refused:tip below safe height&&abs=False"),
    ("C-41b PLATE_MOVE beyond travel refused before any change", HOMED + "G91\n"
     "PLATE_MOVE PLATE=plate1 POS=351\n", "refused:outside 0..350&&abs=False"),
    ("C-42 G28 E (unknown letter) refused, no full home", "G28 E\n", "refused:unknown axis E"),
    ("C-42b G28 XY (no space) refused", "G28 XY\n", "refused:unknown axis XY"),
    ("C-43 SAVE_GCODE_STATE name with a quote refused", HOMED +
     'SAVE_GCODE_STATE NAME="it\'s"\n', "refused:must not contain quotes"),
    ("C-45 command inventory matches", "_T_CMDS\n", "inventory"),
]
STAGE1 = [
    ("C-13 tapd-style plunger move, P rebound", PIPHOMED +
     "MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0\n"
     "MANUAL_STEPPER STEPPER=pipette_stepper MOVE=-5 SPEED=25\n_T_STATE\n", r"state:'P'"),
    ("C-16 tapd homing sequence then G1 P-2", BIND + PIPHOMED + "G1 P-2 F600\n_T_STATE\n",
     r"state:'P': \d+\}.*-2.0\)"),
    ("C-18 SYNC=0 on the plunger", BIND + PIPHOMED +
     "MANUAL_STEPPER STEPPER=pipette_stepper MOVE=1 SYNC=0\n", "refused:SYNC=0"),
    ("C-19b M84 then G1 P-1", BIND + PIPHOMED + "M84\nG1 P-1\n", "refused:plunger not homed"),
    ("C-20 P unbound, then G1 P-1", BIND + PIPHOMED +
     "MANUAL_STEPPER_BASE STEPPER=pipette_stepper GCODE_AXIS=\nG1 P-1\n", "refused:not bound"),
    ("C-32 M84, tapd-style try_home move, then G1 P-3", BIND + PIPHOMED +
     "M84\nMANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0 MOVE=-1 STOP_ON_ENDSTOP=try_home\n"
     "G1 P-3 F600\n", "refused:plunger not homed"),
    ("C-32b M84, MANUAL_STEPPER ENABLE=1, then G1 P-1", BIND + PIPHOMED +
     "M84\nMANUAL_STEPPER STEPPER=pipette_stepper ENABLE=1\nG1 P-1 F600\n",
     "refused:plunger not homed"),
    # Klipper's own motor_off (e.g. after a failed G28) skips the M84 wrapper.
    # Batch homing can't fail, so M84.1 stands in: it runs the same motor_off.
    ("C-39 motors off by Klipper, ENABLE=1, then G1 P-1", BIND + PIPHOMED +
     "M84.1\nMANUAL_STEPPER STEPPER=pipette_stepper ENABLE=1\nG1 P-1 F600\n",
     "refused:plunger not homed"),
    ("C-39b motors off by Klipper, tapd try_home move, then G1 P-3", BIND + PIPHOMED +
     "M84.1\nMANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0 MOVE=-1 STOP_ON_ENDSTOP=try_home\n"
     "G1 P-3 F600\n", "refused:plunger not homed"),
    ("C-39c normal tapd re-zero and move keep the plunger homed", BIND + PIPHOMED +
     "MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0 MOVE=-1 STOP_ON_ENDSTOP=try_home\n"
     "G1 P-2 F600\n_T_STATE\n", r"state:'P': \d+\}.*-2.0\) pip_homed=1"),
]
STAGE2 = [
    ("C-17 G1 P-61 beyond travel", "G28 P\nG1 P-61 F600\n", "range"),
    ("C-17b G1 P-2 after G28 P", "G28 P\nG1 P-2 F600\n_T_STATE\n",
     r"state:'P': 4\}.*-2.0\) pip_homed=1"),
    ("C-17c G1 P1 above home", "G28 P\nG1 P1 F600\n", "range"),
    ("C-13s plain MANUAL_STEPPER on the bound plunger", "G28 P\n"
     "MANUAL_STEPPER STEPPER=pipette_stepper MOVE=-5\n", "refused:Must unregister"),
    ("C-19s M84 then G1 P-1", "G28 P\nM84\nG1 P-1\n", "refused:plunger not homed"),
    ("C-36s re-zeroing the plunger by hand makes it unhomed", "G28 P\n"
     "MANUAL_STEPPER STEPPER=pipette_stepper GCODE_AXIS=\n"
     "MANUAL_STEPPER STEPPER=pipette_stepper SET_POSITION=0\n_PIPETTE_BIND\nG1 P-5 F600\n",
     "refused:plunger not homed"),
    ("C-37s M84, base re-enable, then G1 P-5", "G28 P\nM84\n"
     'SET_STEPPER_ENABLE_BASE STEPPER="manual_stepper pipette_stepper" ENABLE=1\nG1 P-5 F600\n',
     "refused:plunger not homed"),
]

ERR_RE = re.compile(r"^(?:Error evaluating .*?CommandError: (.*)|(Move out of range.*)"
                    r"|(Must home axis first.*)|(Unknown command.*)|(Malformed command.*)"
                    r"|(Must unregister.*))$", re.M)
BENIGN_RE = re.compile(
    r"^(STATE |CMDS |Stats |Exiting|Configured MCU|Pausing toolhead|SET_KINEMATIC_POSITION |"
    r"manual_stepper \S+ has been manually (en|dis)abled|action:(paused|resumed|cancel)|"
    r"Stepper buzz |Reactor .* busy|- '|Traceback|  File |    |\d[\d.]* '|$)")
CRASH_RE = re.compile(r"^(Error evaluating '[^']*': (?!gcode\.CommandError).*|Internal error.*)$", re.M)
STATE_RE = re.compile(r"^STATE .*$", re.M)
MCU_SECTION_RE = re.compile(r"^\[mcu(?: [^\]]+)?\]\n(?:(?!\[).*\n?)*", re.M)


def section(text, name):
    m = re.search(r"^\[" + re.escape(name) + r"\]\n((?:(?!\[).*\n?)*)", text, re.M)
    return m.group(1) if m else ""


def lint(cfg_dir):
    """Static checks:
    * '{-' or '-}' in a Klipper template is Jinja whitespace control: the
      minus sign is silently dropped. Write '{0 - x}' instead.
    * The plunger stage variable and the plunger soft limits must agree."""
    bad = []
    for f in sorted(glob.glob(os.path.join(cfg_dir, "*.cfg"))):
        for n, line in enumerate(open(f), 1):
            code = line.split("#")[0]
            if "{-" in code or "-}" in code:
                bad.append(f"{os.path.basename(f)}:{n}: {line.strip()}")
    st, lim = stage_var(cfg_dir), has_limits(cfg_dir)
    if st is None:
        bad.append("plate-macros.cfg: _PIPETTE_CFG variable_stage not found")
    elif (st >= 2) != lim:
        bad.append(f"stage mismatch: variable_stage={st} but plunger limits "
                   f"{'present' if lim else 'absent'} (see stage2.patch.md)")
    return bad


def stage_var(cfg_dir):
    p = os.path.join(cfg_dir, "plate-macros.cfg")
    if not os.path.exists(p):
        return None
    m = re.search(r"^variable_stage\s*:\s*(\d+)", section(open(p).read(), "gcode_macro _PIPETTE_CFG"), re.M)
    return int(m.group(1)) if m else None


def has_limits(cfg_dir):
    p = os.path.join(cfg_dir, "ebb-pipette.cfg")
    sec = section(open(p).read(), "manual_stepper pipette_stepper") if os.path.exists(p) else ""
    return bool(re.search(r"^position_min\s*[:=]", sec, re.M))


def build(config, work):
    for f in glob.glob(os.path.join(config, "*.cfg")):
        shutil.copy(f, work)
    shutil.copy(os.path.join(HERE, "test-harness.cfg"), work)
    p = os.path.join(work, "printer.cfg")
    text = open(p).read()
    keep_host = re.search(r"^\[mcu CB1\]\n(?:(?!\[).*\n?)*", text, re.M)
    text = MCU_SECTION_RE.sub("", text)  # drop machine-written MCU sections
    text += ("\n[include test-harness.cfg]\n"
             + (keep_host.group(0) if keep_host else "[mcu CB1]\nserial: /tmp/klipper_host_mcu\n")
             + "\n[mcu]\nserial: /dev/null\n[mcu EBBCan]\nserial: /dev/null\n"
               "[mcu octopus]\nserial: /dev/null\n")
    open(p, "w").write(text)


INVENTORY = set()


def load_inventory():
    names = set()
    for line in open(os.path.join(HERE, "command-inventory.txt")):
        line = line.split("#")[0].strip() if line.startswith("#") else line.strip()
        if line:
            names.add(line.split("|")[0].strip())
    return names


def with_state_probe(gcode, exp):
    """For refusals, report the state just before and after the last command."""
    if not exp.startswith(("refused:", "range")):
        return gcode
    lines = gcode.strip("\n").split("\n")
    return "\n".join(lines[:-1] + ["_T_STATE", lines[-1], "_T_STATE"]) + "\n"


def run_case(args, work, i, gcode):
    gf, lf = os.path.join(work, f"case{i}.gcode"), os.path.join(work, f"case{i}.log")
    open(gf, "w").write(gcode)
    d = args.dicts
    cmd = [args.python, os.path.join(args.klipper, "klippy", "klippy.py"),
           os.path.join(work, "printer.cfg"), "-i", gf, "-o", os.path.join(work, f"case{i}.serial"),
           "-l", lf, "-d", os.path.join(d, "m8p-bridge.dict"),
           "-d", "EBBCan=" + os.path.join(d, "ebb42.dict"),
           "-d", "octopus=" + os.path.join(d, "octopus.dict"),
           "-d", "CB1=" + os.path.join(d, "host.dict")]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    return open(lf).read() if os.path.exists(lf) else "Config error: no log written\n"


def check(log, exp):
    cfgerr = re.search(r"^(Config error|Error loading template).*$", log, re.M)
    if cfgerr:
        return False, "CONFIG: " + cfgerr.group(0)
    i = log.rfind("Configured MCU")  # skip the config dump
    body = log[i:] if i >= 0 else log
    crash = CRASH_RE.search(body)
    if crash:
        return False, "TEMPLATE CRASH: " + crash.group(0)
    errs = [next(x for x in e if x) for e in ERR_RE.findall(body)]
    states = STATE_RE.findall(body)
    kind, _, arg = exp.partition(":")
    arg, _, after = arg.partition("&&")
    expected = arg if kind == "refused" else ("out of range" if kind == "range" else None)
    unexpected = [l for l in body.splitlines()
                  if not BENIGN_RE.match(l) and not (expected and expected in l)
                  and not (kind == "refused" and l.startswith("Error evaluating") and expected in l)]
    if unexpected:
        return False, "unexpected log line: " + unexpected[0][:160]
    if kind == "inventory":
        m = re.search(r"^CMDS (.*)$", body, re.M)
        got = {c for c in (m.group(1).split() if m else []) if not c.startswith("_T_")}
        new, gone = sorted(got - INVENTORY), sorted(INVENTORY - got)
        if new or gone:
            return False, f"not in inventory: {new}; listed but missing: {gone}"
        return True, f"{len(got)} commands, all classified"
    if kind in ("refused", "range"):
        hit = any(arg in e for e in errs) if kind == "refused" else any("out of range" in e for e in errs)
        # "Unchanged" = nothing moved: same axis map and positions. A refusal may
        # still clear a homed flag (fail safe), so flags aren't compared.
        motion = [re.sub(r" pip_homed=.*$", "", s) for s in states[-2:]]
        same = len(motion) == 2 and motion[0] == motion[1]
        ok = hit and same
        if hit and not same:
            return False, "refused but something moved: " + " -> ".join(states[-2:])
        if ok and after and not re.search(after, states[-1]):
            return False, f"refused, but state after doesn't match {after!r}: " + states[-1][-120:]
    elif kind == "noerror":
        ok = not errs
    elif kind == "state":
        ok = not errs and any(re.search(arg, s) for s in states)
    else:
        raise ValueError(exp)
    detail = errs[0] if errs else (states[-1][-140:] if states else "no output")
    return ok, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--klipper", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--dicts", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--stage", default="auto", choices=["auto", "1", "2"])
    ap.add_argument("--keep", action="store_true", help="keep the work dir and logs")
    args = ap.parse_args()

    work = tempfile.mkdtemp(prefix="ap-offline-")
    build(args.config, work)
    stage = (stage_var(work) or 1) if args.stage == "auto" else int(args.stage)
    global INVENTORY
    INVENTORY = load_inventory()
    cases = [("C-01 config loads", "_T_STATE\n", "state:axis_map")] + COMMON \
        + (STAGE1 if stage == 1 else STAGE2)
    print(f"stage {stage}, {len(cases)} cases, work dir {work}")

    fails = 0
    for line in lint(args.config):
        fails += 1
        print("FAIL LINT", line)
    for i, (name, gcode, exp) in enumerate(cases):
        ok, detail = check(run_case(args, work, i, with_state_probe(gcode, exp)), exp)
        fails += not ok
        print("PASS" if ok else "FAIL", name, "|", detail)
    print("FAILURES:", fails)
    if not args.keep and not fails:
        shutil.rmtree(work)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
