# TODO

## Testing and recovery

- [ ] Test setup and a full train/evaluate/review cycle in another project.
- [ ] Verify GitHub CI across the supported Python versions.
- [ ] Test on a real Slurm cluster: shared environments, dependent evaluations, duplicates, failures, and file locking.
- [ ] Recover safely from interrupted local launchers.
- [ ] Reconcile uncertain Slurm submissions without risking duplicate jobs.

## Installation and portability

- [ ] Check PyPI name availability and set up Trusted Publishing.
- [ ] Check that configured interpreters run and have NAIA installed where needed.
- [ ] Import existing task and experiment records.

## Browser

- [ ] Edit task text and approved suite/context settings.
- [ ] Render suite Markdown instead of showing its source.
- [ ] Include scheduler reconciliation in refresh, not just saved results.

See [features and limits](docs/FEATURES.md) for current behavior.
