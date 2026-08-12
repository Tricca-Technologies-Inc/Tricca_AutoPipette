<!--
Thanks for the PR. If this closes an issue, say so explicitly (e.g.
"Closes #54") so it closes automatically on merge.
-->

## What this does

<!-- What changed, and why. Link the issue it addresses if there is one. -->

## Verification

<!-- This repo has no CI yet (#19) -- these are run locally and reported here. -->

- [ ] `ruff check .`
- [ ] `ruff format --check .`
- [ ] `pyright`
- [ ] `pytest`
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
