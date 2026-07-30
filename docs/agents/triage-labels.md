# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those
roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the
corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Repo-specific labels

Not part of the canonical five; applied alongside them.

| Label | Meaning |
| --- | --- |
| `safety` | Touches a physical-safety limit or interlock — a syringe capacity bound, the homed interlock, tip disposal, gantry kinematics, or network exposure of hardware control. Currently on #15, #24, #27, #32. |

`safety` is not a severity. It marks work where the failure mode is **mechanical
or physical** rather than an exception — a wrong value overdrives a syringe or
crashes a gantry, and no amount of error handling catches it. Treat a `safety`
issue as needing bounds and a human reviewer regardless of how small the diff
looks.

## Current state

Every issue migrated from `docs/TODO.md` (#15–#33) carries `needs-triage` and has
**not** had a real triage pass. `ready-for-agent` is deliberately unused so far:
the migrated backlog states outright that none of its entries are shovel-ready —
each needs a planning session first. Don't let a `/triage` run promote one to
`ready-for-agent` on the strength of the issue body alone.
