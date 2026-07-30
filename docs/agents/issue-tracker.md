# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues on
`Tricca-Technologies-Inc/Tricca_AutoPipette`. Use the `gh` CLI for all
operations.

**This is the single backlog.** It used to be split between `docs/TODO.md` and
this tracker; that file was migrated wholesale to issues #15–#33 and deleted on
2026-07-30. Do not reintroduce a second backlog file — the decision and its
reasoning are recorded in #20.

**Start from the backlog map, #34.** It carries the dependency order between
entries, the standing "true of the code now" findings, and an index of every
issue. An individual issue does not tell you what it blocks or is sequenced
after; the map does.

**Note the number offset.** Pull requests consumed numbers 1–14 before any issue
was filed, so the migrated backlog starts at #15. Old prose that says "item N"
means issue #N+14.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc or `--body-file` for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run
inside a clone.

## Blocking relationships

This repo uses GitHub's **native issue dependencies**. Add an edge with:

```bash
BLOCKER_ID=$(gh api repos/Tricca-Technologies-Inc/Tricca_AutoPipette/issues/<blocker> --jq .id)
gh api --method POST \
  repos/Tricca-Technologies-Inc/Tricca_AutoPipette/issues/<child>/dependencies/blocked_by \
  -F issue_id="$BLOCKER_ID"
```

`<blocker>` is the `#number`, but `issue_id` must be the blocker's numeric
**database id** — not the `#number` and not the `node_id`. GitHub reports
`issue_dependencies_summary.blocked_by` (open blockers only — the live gate).

Only dependencies an issue states outright are encoded. Softer sequencing
preference lives in the #34 graph as prose, deliberately unencoded so entries
don't look unstartable when they are merely better-done-in-order.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be
either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: as above — native issue dependencies. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

Note that #34 is a backlog index, not a `wayfinder:map` — it predates any
wayfinding session and carries no Fog/Decisions-so-far body.
