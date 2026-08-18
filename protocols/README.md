This is where protocols are stored.

`examples/` holds five runnable `.pipette` files that accompany
[`docs/protocol-authoring.md`](../docs/protocol-authoring.md) — a
task-oriented guide to writing a protocol file, with a walkthrough of each
example. They aren't listed by the kiosk (its protocol picker only globs
this top-level directory, not subdirectories); run them from `tap` with
`run examples/<name>.pipette`.

## Shared vs. local protocols

Like the other `config/` categories (see `config/README.md`'s "Shared repo
vs. local per-machine config"), `protocols/` is a **shared-and-local union
category**: real per-machine protocol files belong under the per-machine
local config root's `protocols/` directory
(`$AUTOPIPETTE_LOCAL_DIR/protocols/`, default `~/.config/tricca-autopipette/protocols/`),
not in this shared repo. A protocol run from `tap`/the kiosk resolves the
same way regardless of which root it actually lives in; the same filename in
both roots means the local one wins. `run <name>.pipette` and the kiosk's
protocol picker both apply this union the same way `.pipette` files ever
have — no `shared:`-style prefix, one consistent mental model with every
other category.
