# Contributing

Bug fixes, documentation improvements, and small features are welcome. For a
larger change, open an [issue](https://github.com/NazirNayal8/naia/issues) first
so we can agree on the approach.

## Get started

Fork the repository on GitHub, then use Python 3.10+:

```bash
git clone https://github.com/YOUR-USERNAME/naia.git
cd naia
git switch -c your-change
python -m pip install -e .
python -m unittest discover -s tests -v
```

No GPU, research datasets, or cluster access are needed. Model-capture tests need
PyTorch; browser-code tests need Node.js. Those tests may skip if their dependency
is unavailable. Mention any skips in your PR, and run the relevant tests when
changing those features.

## Open a pull request

Commit the intended files, push your branch to your fork, and open a PR against
`NazirNayal8/naia:main`. If you have write access here, use a feature branch in
this repository instead. Do not push directly to `main`.

- Keep the change focused; explain what it fixes and how you tested it.
- Add a regression test for a bug fix where possible.
- Include before/after screenshots for interface changes.
- Update user-facing documentation when behavior changes.
- Leave out credentials, private project data, generated runs, and local environments.

CI runs automatically; a maintainer may need to approve a first-time contributor's
workflow run. Address review feedback and wait for passing checks. The maintainer
reviews and merges the PR; contributors do not need write access.

## Packaging changes

When changing installation or packaged assets, also check:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Keep changes under the existing [MIT license](LICENSE).
