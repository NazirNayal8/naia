# Release notes

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
are pending. The browser does not yet edit task text or suite status.
See [TODO](TODO.md).
