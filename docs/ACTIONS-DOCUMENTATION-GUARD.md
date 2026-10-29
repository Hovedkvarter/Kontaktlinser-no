# Documentation-only Actions guard — 2026-10-29

Status: IMPLEMENTERT in this candidate branch, not merged or operationally verified.
Related: chillout-labs/chillout-platform#301 and Continuous Learning PRs #302,
sjekkpris-no#39 and Hovedkvarter/Kontaktlinser-no#44.

## Contract

Keep workflow triggers, job/check names and existing test commands. Classify
the complete push before/after tree difference with local Git and full checkout
history. PR classification uses the merge base, and never authorizes operations.
No changed-file API, pagination limit, last-commit shortcut or broad *.md exclusion.
Rename detection is disabled so a site file moved into documentation still
appears as a deleted site input. NUL-separated paths preserve spaces/newlines.

Only explicit non-runtime root documentation names, docs/**/*.md and
.claude/rules/**/*.md are excluded. Unknown paths (including unknown Markdown,
JSON under docs, content, assets, code, workflows and guard code) are site changes.
Keep docs/ for non-runtime Markdown; if a future site consumes it, remove that
exclusion in the same reviewed change. New documentation locations require review.
One non-documentation path in a mixed push enables the existing operational flow.

An empty diff does not operate. Missing/malformed commits, unavailable history,
Git failure or unsupported events fail the check before operational outputs
are emitted; this is a visible failed run, never a green silent skip or permission
to publish. A new branch with an explicit created event and zero before-SHA
retains initial-build behavior after verifying its after commit.
Schedule and workflow_dispatch retain their existing behavior.

## Side-effect boundary

Sjekkpris: the existing test job always runs; the live catalogue/build/deploy
chain requires operational=true. Live category/product previews use the same
guard, retaining their existing test commands and manual behavior. The design
preview uses fixture data only and is unchanged.

Kontaktlinser: existing tests and rendered-site validation still run against
the runner's disposable checkout. Documentation-only validation receives no
Chillout key/origin. Generating this test site can write temporary history and
sitemap files in that checkout, as the existing tests require; these are never
committed, uploaded for publication or deployed by a docs-only run.
build_catalog.py and feed-history acquisition remain schedule/manual only.
History write-back and Pages publication require operational=true.
The separate feed-discovery test remains; its live discovery/cache/report
write-back job also requires operational=true, even if GitHub's path filter
falls back to running the workflow for a large push.

This is not a production authorization system. Existing schedule/manual runs
remain operational and must not be dispatched as a test of this change.

## Evidence

OBSERVERT locally: 15 standard-library regression tests passed per repository
(Python 3.12 + real temporary Git repositories, no network/feed/deploy).
Coverage: docs, empty diff, real code/content/data/assets, unknown Markdown,
mixed multi-commit pushes, 3,101 changed paths, deleted/renamed inputs,
docs rename/deletion, diverged PR base, force-push, merge commit, initial branch,
schedule/manual, invalid/missing history, CLI output/failure and workflow wiring.
YAML parsing and git diff --check passed. All pre-existing workflow run/uses
commands were compared with main and retained. No CLAUDE.md or local rule edits.
Ordinary PR CI provides the existing application/test checks; no operational
workflow dispatch or live publish is needed to validate the classifier.

## Merge order and bootstrap caveat

After separate authorization: land these two guard PRs before Continuous Learning
#39 and #44. Platform #302 has no dependency on the website guard code; its own
current CI and Railway/autodeploy state still need separate read-only verification.
Then recheck current main, conflicts and CI for all three Continuous Learning PRs
and merge them individually with history preserved.

The guard PRs themselves modify workflows/code and correctly classify as real
changes. A normal merge of either guard PR can therefore trigger the existing
operational push flow. Do not merge them under a no-publication authorization
without a separately approved, verified one-time suppression of those operational
runs. Do not weaken the classifier to label all future workflow changes as docs.
No such suppression, workflow disable, merge, deploy or publication was performed
for this implementation. Active Delivery PRs and original local worktrees stay
unchanged.

FORSLAG/ÅPENT: any broader documentation allowlist, changed website inputs or
bootstrap suppression belongs to a separate explicit scope. Reuse this tested
method, never another Property's data or approvals.
