# Releasing

**The git tag is the version.** Nothing in the repo stores it, so there is no
second copy to drift — `api/main.py` and `web/package.json` used to hold
hand-maintained versions that had already disagreed (`0.1.0` vs `0.0.1`) with
no release to anchor either. `web/package.json` now reads
`0.0.0-unmanaged` and is never published to npm.

An untagged build reports its version as `dev`, which is honest: it is not a
release.

## Versioning

[Semantic versioning](https://semver.org). Pre-1.0, so the API and the on-disk
formats can still change:

| Bump | For |
|---|---|
| **patch** `0.2.0 → 0.2.1` | Bug fixes. No migration, no config change. |
| **minor** `0.2.1 → 0.3.0` | Features, new endpoints, DB migrations, anything needing a `docker compose up --build`. |
| **major** | Held for 1.0. |

A tag with a suffix (`v0.3.0-rc.1`) publishes as a pre-release and does not
move `latest`.

## Cutting a release

1. **Move `[Unreleased]` to a version heading** in `CHANGELOG.md`:

   ```markdown
   ## [Unreleased]

   ## [0.2.0] - 2026-08-05
   ```

   Leave an empty `[Unreleased]` above it for the next cycle. The release
   workflow **refuses to publish** if `CHANGELOG.md` has no `## [<version>]`
   heading, and it uses that section verbatim as the GitHub Release notes —
   so write it for a user, not as a commit log.

2. **Check the migration story.** If this release adds an Alembic migration,
   say so in the changelog and name what happens on first start. Users read
   the release notes to decide whether to upgrade.

3. **Tag an annotated tag on `main`** and push it:

   ```bash
   git checkout main && git pull
   git tag -a v0.2.0 -m "v0.2.0"
   git push origin v0.2.0
   ```

   Lightweight tags work but carry no author or date; use `-a`.

## What the workflow does

`.github/workflows/release.yml`, on any `v*.*.*` tag:

1. **verify** — re-runs the whole gate set against the tagged commit: ruff,
   `ruff format --check`, mypy, backend tests with coverage, tsc, eslint at
   the ratchet, frontend tests with coverage. This is *not* redundant with CI:
   a tag can be pushed to any commit, including one that never went through a
   pull request.
2. **images** — builds `api` and `web` and pushes them to GHCR as
   `ghcr.io/<owner>/pillar43-<service>`, tagged `0.2.0`, `0.2`, and
   `latest`. Every build passes `target: runtime` explicitly, because the
   `api` Dockerfile has a `dev` stage last and Docker builds the last
   stage by default — that is how the test toolchain once shipped to
   production. There is no worker or embeddings image; background jobs run
   inside the api process.
3. **release** — extracts this version's CHANGELOG section and publishes it
   as the GitHub Release body. Nothing else is added to the body.

**Contributors are listed by hand.** The workflow does not generate a
contributors list, so the GitHub Release will name changes only. The grant
promises that each release documents changes and contributors, so before
tagging, add a `### Contributors` list to the version's CHANGELOG section
(names of the people who wrote, reviewed, tested or supplied archive material
for this release; `git shortlog -sn <previous-tag>..HEAD` lists committers but
not the others). The workflow copies it into the release notes with the rest
of the section.

If **verify** fails, nothing is published. Delete the tag, fix, re-tag:

```bash
git tag -d v0.2.0 && git push origin :refs/tags/v0.2.0
```

## After the release

Confirm the published image reports the version you expect:

```bash
docker run --rm ghcr.io/<owner>/pillar43-api:0.2.0 \
  python -c "import os; print(os.environ['PILLAR43_VERSION'])"
```

At runtime it also appears in `GET /health`:

```json
{ "status": "ok", "service": "api", "version": "0.2.0", "api_sha": "…" }
```

## First release checklist

Not yet done for this repo — no tag exists.

- [ ] Decide the opening version (`v0.1.0` suits a technical preview).
- [ ] Confirm the GHCR package visibility is public, or nobody can pull.
- [ ] Add a "Run a published image" section to `README.md` once images exist.
- [ ] Verify a clean-clone install against the tag, following `README.md`
      verbatim, on a machine that has never run Pillar-43.
