# One `tapd` process per physical rig, permanently

**Status:** accepted

Every piece of daemon state — the single Moonraker connection, `AutoPipette`,
`LocationManager`, `TipBoxManager`, the homed interlock — is modeled as a
singleton inside one `AutoPipetteService`. We considered whether `tapd` should
ever grow into a multi-rig/multi-tenant process (one daemon fanning out to
several controller boards, or several rigs sharing a host process) and decided
against it, permanently: retrofitting that later would mean threading a rig-id
through nearly every method signature in `daemon/service.py`, `core/`, and the
control-plane RPC surface. If multiple rigs ever need to be operated from one
place, the answer is N independent `tapd` processes (one per rig, one port
each), optionally fronted by a separate fleet tool (#31) — not a multi-rig-aware
daemon. This also fixes the meaning of "rig" in `CONTEXT.md`.
