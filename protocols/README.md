This is where protocols are stored.

`examples/` holds five runnable `.pipette` files that accompany
[`docs/protocol-authoring.md`](../docs/protocol-authoring.md) — a
task-oriented guide to writing a protocol file, with a walkthrough of each
example. They aren't listed by the kiosk (its protocol picker only globs
this top-level directory, not subdirectories); run them from `tap` with
`run examples/<name>.pipette`.

`legacy/` holds the real assay protocols converted from the pre-JSON-config
era (see [`legacy/README.md`](legacy/README.md) for the conversion notes,
what changed syntactically, and which files still need a human before
running). Same non-recursive-kiosk caveat applies: run them with
`run legacy/murphy_100/<name>.pipette` or `run legacy/murphy_1000/<name>.pipette`.
