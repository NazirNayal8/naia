# Release notes

## 0.1.0a0 — Initial alpha

- One MIT-licensed `naia` package; no mandatory runtime dependencies.
- Codex, Claude, or both: managed instructions and persistent project context.
- Prioritized task queue, ownership, and automatic result-review followups.
- Approved experiment suites, reserved results, provenance checks, and card syncing.
- Sequential local execution and Slurm submission with dependent evaluations.
- Duplicate checks and explicit retry paths for tracked failed work.
- One browser dashboard for tasks, suites, context, and saved architectures.
- Bundled Lens: PyTorch capture, hierarchical inspection, tensor shapes, and playback.
- Architecture references linked to suites/tasks and checked against saved-file hashes.
- Standalone architecture commands and legacy command/import compatibility.
- Analysis assignments with input/output evidence references.

### Verification

- 74 tests passed in a Python 3.10/PyTorch environment.
- Isolated source-package installation, wheel/source builds, and metadata checks passed.
- Chromium checks passed for the dashboard, integrated Lens, and standalone Lens.

### Limits

PyPI publication, real-cluster validation, and historical migration are pending.
Browser text editing and suite-status controls are not implemented. Local orphaned
runs and ambiguous scheduler submissions require investigation; automatic recovery
is not guaranteed. See [TODO](TODO.md) for remaining work.

This is an alpha for testing, not a claim of production readiness or universal
hardware/platform validation.
