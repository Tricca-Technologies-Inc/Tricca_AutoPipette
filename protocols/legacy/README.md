# Legacy Murphy protocols (converted)

The 119 `.pipette` files under `murphy_100/` and `murphy_1000/` are
mechanically converted from the pre-JSON-config era: the two rigs' INI
configs (`Murphy-100.conf`, `Murphy-1000.conf`, still on `origin/Murphy-Branch`)
and the `.pipette` protocols written against the old `cmd2` shell grammar.
CLAUDE.md notes the original `protocols/` directory "was cleared out" when
the JSON config system landed -- this is that content, brought forward.

**None of this has run on real hardware since conversion.** Treat every file
here as a draft: read it, and run it with a `break` inserted near the start
(or supervise the first pass closely) before trusting it unattended on the
rig.

## Running these

Each subdirectory corresponds to a physical syringe + deck combination and
needs the matching system config:

```
tapd --config murphy_100_system.json   # for protocols/legacy/murphy_100/
tapd --config murphy_1000_system.json  # for protocols/legacy/murphy_1000/
```

Both configs point at the same rig (`triccaautopipette02.local` -- the two
old confs share a hostname/IP, so this looks like one physical rig switched
between a 100µL and a ~530µL syringe/deck rather than two separate
machines). Unlike the `examples/` protocols, these do **not** call
`load_locations` themselves -- the full deck loads once from the system
config at daemon startup, exactly matching the old workflow (the old shell
had no per-protocol location loading at all, and reloading a tipbox's JSON
mid-run would reset its consumed-tip state, which is actively wrong for a
real consumable).

## What changed syntactically

| Old | New | Notes |
|---|---|---|
| `--extra_air` | `--pre_air_gap <N>` | `N` = the conf's `[WAIT] ext_air` (30 for Murphy-100, 50 for Murphy-1000) |
| `--after_air` | `--post_air_gap <N>` | `N` = the conf's `[WAIT] aft_air` (2 for Murphy-100, 10 for Murphy-1000) |
| `--prewet N` | `--prewet N --prewet_vol <vol_ul>` | `vol_ul` = the line's own aspirate volume (closest match to the old cycle-drew-~full-volume behavior) |
| `--prewet` (bare, no count) | `--prewet 1 --prewet_vol <vol_ul>` | ~24 lines had no count, which the old parser actually required -- treated as 1 cycle per user decision |
| `--serum_speed` | line wrapped in `switch_liquid serum` / `switch_liquid water` | New `config/liquids/serum.json`, `speed_dispense: 30` (both machines' `speed_pipette_up_slow`). No per-call speed override exists in the new grammar, only liquid profiles. |
| `--touch` | dropped | Dead code even in the legacy implementation -- the move it should have triggered was commented out. CLAUDE.md confirms it and its config counterpart were later removed rather than implemented. |
| `--keep_tip`, `--wiggle`, `--src_row/col`, `--dest_row/col`, `--dispense_vol`/`-d`, `--tipbox` | unchanged | Same names/semantics in the new parser |
| `(* comment *)` | `# comment` | New grammar only recognizes `#` |
| `reset NAME` | `reset_plate NAME` | 5 lines used the bare typo `reset`, which isn't a command in either shell version; fixed rather than carried forward |

Flag order in converted lines follows the documented `pipette` usage order,
not the source file's original order.

## Validation performed

- Every non-comment line (10,517 across all 119 files) was parsed against
  the actual `TAPCmdParsers`/dispatch tables in
  `daemon/service.py`'s `_LINE_DISPATCH`/`_STR_ARG_DISPATCH` -- the same
  tables a real protocol run uses. **Zero syntax errors.**
- Every `source`/`dest`/`--tipbox`/`reset_plate` location name was checked
  against the actual deck each file was assigned to, loaded through the real
  `LocationManager`. Three files have unresolved names -- see below.
- Both new system configs (`murphy_100_system.json`,
  `murphy_1000_system.json`) load cleanly through `JsonConfigManager`, and
  both decks (59 and 19 plates respectively) load cleanly through
  `LocationManager`.

## Needs a human before running

- **`murphy_100/step0B.pipette`** -- references `STANS_FULL`, which exists
  in neither conf (`STANS1_FULL` does; likely the intended plate, but not
  guessed here).
- **`murphy_100/step0B-2.pipette`** -- references `4DR` and `STANS4M`,
  neither of which exists in either conf (`STANS4` does; `4DR` has no
  obvious match at all).
- **`murphy_100/step4B.pipette`** -- references `SAMPLEPLATE_DIP`
  (Murphy-100-only) and `MSPLATE` (Murphy-1000-only) in the same line --
  the two can't coexist on either deck as converted. Needs a person to
  decide which machine/plate name was actually intended.

## Machine assignment

Most files were assigned to `murphy_100/` or `murphy_1000/` by checking
which plate names they reference against each conf's exclusive plate list.
Eight files reference only names shared by both confs (`96wellplate`,
`DFIPLATE`, `ICEM`, `LCPLATE`, `LRA`, `SAMPLEPLATE`, `STANS1_FULL`,
`STANS2`, `STANS3`, `dest`, `garbage`, `src`, `tipbox`) and were
**defaulted to `murphy_100/`** without independent evidence either way --
move them to `murphy_1000/` if that's wrong:

`0PB-2.pipette`, `0PB-3.pipette`, `MB0-2.pipette`, `YPB0-3-15.pipette`,
`YPB0-3.pipette`, `YPB0-3a.pipette`, `step0B-2.pipette`, `test_home.pipette`

## Files using the wrapped `--serum_speed` (12)

`1B-2_S.pipette`, `1B_S.pipette`, `4B_S.pipette`, `4B_SNP.pipette`,
`4GB.pipette`, `A10_S.pipette`, `a_step1_test.pipette`, `pcrload.pipette`,
`testA6_S.pipette`, `testA8.pipette`, `test_serum_S.pipette`,
`~old0B_S.pipette`
