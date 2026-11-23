<!--
Thanks for the PR. If this closes an issue, say so explicitly (e.g.
"Closes #54") so it closes automatically on merge.
-->

## What this does

<!-- What changed, and why. Link the issue it addresses if there is one. -->

## Verification

<!-- CI repeats these, but run them locally first and tick only what you actually ran. -->

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `pyright`
- [ ] `pytest`
- [ ] Tests written **before** the implementation, and seen failing first (docs/agents/tdd.md)
- [ ] `pytest --doctest-modules`, if you touched a docstring `>>> ` example
- [ ] `sphinx-build -W docs docs/_build/html`, if you touched a docstring or `docs/`

## Safety-sensitive?

<!--
Check this if the change touches a physical-safety limit or interlock -- a
syringe capacity bound, the homed interlock, tip disposal, gantry kinematics,
or network exposure of hardware control (see the `safety` label in
docs/agents/triage-labels.md). If checked, say what bounds/tests keep an
overdrive or unsafe-move failure mode from reaching hardware.
-->

- [ ] This PR touches safety-sensitive code

## AI assistance

<!--
Which AI tools helped (Codex, Claude Code, Copilot, Cursor, ... or none),
and what they did. You are the author either way: you read and checked
everything they wrote before opening this PR.
-->

- Tools used:
- [ ] I read every line the AI wrote, and it follows AGENTS.md
