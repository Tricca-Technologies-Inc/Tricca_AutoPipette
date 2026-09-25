# Releasing

Manual checklist for cutting a release. There is no bump/automation tooling
(`bump-my-version`, a Make target, etc.) — releases are infrequent and
solo-maintainer, so the extra tooling surface isn't worth it (see issue #22).

**Versioning:** SemVer, staying in the `0.x` series. The control-plane RPC
namespaces and the `.pipette` grammar are both public contracts still being
reshaped (e.g. issue #15's `keep_tip` → `tip_disposition` change), so 1.0 is
gated on those two surfaces stabilizing — don't bump to `1.0.0` as part of a
routine release.

**Packaging scope:** releases are sdist + wheel only, built from `pyproject.toml`
as configured today. `config/` and `systemd/` are deliberately **not**
packaged (`[tool.setuptools.package-data]` only covers
`autopipette_kiosk/static/*`) — this is scoped honestly as "source + wheel
for people who clone the repo," matching the existing
`AUTOPIPETTE_REPO_ROOT`-env-var install model, not advertised as turnkey.
Closing that gap is out of scope for this process; see issue #22.

**First tag:** `v0.2.0` is meant to be the first real tag. Don't cut it (or
any tag) until issue #19's CI workflow is live and green on `main` — a
release built off an unverified `main` has nothing checking it.

## Steps

1. Bump `version` in `pyproject.toml` (`[project]` section) to the new
   version number.
2. Draft the `CHANGELOG.md` entry for the release:
   - List merged PRs since the previous tag, e.g.:
     ```bash
     gh pr list --repo Tricca-Technologies-Inc/Tricca_AutoPipette \
       --search "is:merged base:main merged:>=<date-of-previous-tag>"
     ```
     or use GitHub's own generated notes as a starting point (the same
     mechanism `release.yml`'s `--generate-notes` uses).
   - Hand-edit that list into [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
     format under a new `## [X.Y.Z] - YYYY-MM-DD` heading, sorted into
     `Added`/`Changed`/`Fixed`/`Removed` as appropriate.
3. Commit both changes (`pyproject.toml` version bump + `CHANGELOG.md`
   entry) to `main`.
4. Tag the commit: `git tag vX.Y.Z`
5. Push the tag: `git push --tags`

Pushing the tag triggers `.github/workflows/release.yml`, which builds the
sdist/wheel and publishes them to a GitHub Release with generated notes —
nothing further to do by hand.
