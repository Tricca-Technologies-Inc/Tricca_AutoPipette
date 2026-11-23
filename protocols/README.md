This is where protocols are stored.

`examples/` holds five runnable `.pipette` files that accompany
[`docs/protocol-authoring.md`](../docs/protocol-authoring.md) — a
task-oriented guide to writing a protocol file, with a walkthrough of each
example. Browse the `examples` folder in the kiosk, or run them from `tap`
with `run examples/<name>.pipette`.

## Shared vs. local protocols

Like the other `config/` categories (see `config/README.md`'s "Shared repo
vs. local per-machine config"), `protocols/` is a **shared-and-local union
category**: real per-machine protocol files belong under the per-machine
local config root's `protocols/` directory
(`$AUTOPIPETTE_LOCAL_DIR/protocols/`, default `~/.config/tricca-autopipette/protocols/`),
not in this shared repo. A protocol run from `tap`/the kiosk resolves the
same way regardless of which root it actually lives in; the same filename in
both roots means the local one wins. Subfolders are matched by relative
path, so a local `examples/a.pipette` overrides the shared file at that
same path, not files with the same name in other folders. A path outside
either root (`..`, or a symlink pointing elsewhere) is refused.
`run <name>.pipette` and the kiosk's protocol picker use no `shared:`-style
prefix, and both get their list from `tapd`.

The kiosk hides `legacy/`: those converted protocols are unverified on
hardware and each needs a specific Murphy profile (see
[`legacy/README.md`](legacy/README.md)). Run them from `tap`.
