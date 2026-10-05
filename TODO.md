# TODO

## First integrations

- [ ] Test onboarding and a complete train/evaluate/review cycle in another project.
- [ ] Verify GitHub CI after the first push; check the packaged installation across its Python matrix.
- [ ] Run real Slurm smoke tests: shared environments, dependent evaluations, duplicate checks, failures, and filesystem locks.
- [ ] Add safe recovery for stale local runs after launcher interruption.
- [ ] Add explicit reconciliation/adoption for uncertain Slurm submissions; retain conservative duplicate protection.

## Distribution and portability

- [ ] Set up PyPI Trusted Publishing and verify the `naia` name before the first upload.
- [ ] Strengthen environment diagnostics: interpreter execution and installed NAIA checks.
- [ ] Implement and test import/migration of existing task and experiment records.

## Interface

- [ ] Add browser task-text editing and approved suite/context controls.
- [ ] Render suite Markdown rather than displaying source text.
- [ ] Connect browser refresh to scheduler reconciliation, not just saved-result syncing.

Current capabilities and limits: [feature guide](docs/FEATURES.md).
