# Releasing

This project releases from `main` via a `vX.Y.Z` git tag. The tag push triggers
[`release.yml`](.github/workflows/release.yml), which re-verifies the tagged commit
(lint, type-check, full test suite), builds a Python wheel/sdist and a zipped frontend
build, and publishes a GitHub Release using the matching `CHANGELOG.md` section as the
release notes. The workflow never edits the repo — it only validates and ships what the
maintainer already committed, so every step below must be done *before* tagging.

Follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

## Steps

1. **Update `CHANGELOG.md`**: rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and
   add a fresh empty `## [Unreleased]` section above it. The release workflow fails the
   build if it can't find a `## [X.Y.Z]` section matching the tag.
2. **Bump the version** in `pyproject.toml` (`[project] version = "X.Y.Z"`) to match. The
   workflow fails if the tag and this version disagree — a safety net against tagging the
   wrong commit.
3. Commit both: `git commit -am "chore: release vX.Y.Z"`.
4. Push to `main`, wait for [CI](.github/workflows/ci.yml) to go green.
5. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
6. Watch the [Release workflow run](../../actions/workflows/release.yml) — it re-runs the
   full test suite on the tagged commit before publishing anything.
7. Confirm the [GitHub Release](../../releases) looks right (notes, attached wheel/sdist,
   frontend zip).

If the workflow fails after the tag is pushed (e.g. a forgotten changelog section), fix
the issue, delete and re-push the tag (`git tag -d vX.Y.Z && git push origin :vX.Y.Z`,
then repeat from step 5), or re-run it manually via `workflow_dispatch` with the existing
tag once the fix is on `main`.

## Pre-release versions

Tags like `v1.1.0-rc1` are marked as GitHub pre-releases automatically (any version
containing a `-` suffix). `CHANGELOG.md` sections use the same bracketed version.
