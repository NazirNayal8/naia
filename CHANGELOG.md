# Release notes

## 0.1.0a1

- Existing-project setup collects bounded repository evidence for assistant review.
- Assistants propose context with file references; users confirm or correct it.
  Discovery keeps proposals unconfirmed and preserves confirmed settings.
- Scan exclusions and manual setup without scanning are available.
- Restored the local research UI's dark task deck and draggable suite graph,
  including task editing, archiving, status controls, and rendered suite cards.
- Replaced the tree-only Lens screen with a draggable, color-coded graph,
  hierarchy levels, shape inspection, playback, saved layouts, comparison, and SVG export.
- Removed the separate project-context tab; onboarding records are unchanged.

Verified: 114 tests, Chromium dashboard/viewer checks, package builds, and isolated installation.

## 0.1.0a0

Initial alpha release:

- One MIT-licensed package with no mandatory runtime dependencies.
- Project context and instructions for Codex, Claude, or both.
- Task queue, experiment suites, result syncing, and review tasks.
- Local execution and Slurm submission with dependent evaluations and duplicate checks.
- Analysis assignments with evidence references.
- Browser dashboard and Lens model inspection, with suite/task links.
- Standalone architecture commands and compatibility with the earlier command names.

Verified: 74 tests in Python 3.10 with PyTorch, package builds and isolated
installation, and Chromium checks for the dashboard and both Lens viewers.

Real-cluster validation, interrupted-run recovery, migration, and PyPI publication
are pending. Task and suite editing improvements are included in 0.1.0a1.
See [TODO](TODO.md).
