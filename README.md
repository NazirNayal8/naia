# NAIA

NAIA (Nazir's AI Assistant) helps Codex and Claude organize research projects.
It keeps tasks, experiment suites, results, and model diagrams together in your
repository. You work through your existing assistant; a local browser UI lets
you review the work and manage the task queue.

Python 3.10+ · [MIT](https://github.com/NazirNayal8/naia/blob/main/LICENSE) · Alpha `0.1.0a4`

## Install

Install into a Python or Conda environment. Git must be available; no clone is needed.

```bash
pip install "git+https://github.com/NazirNayal8/naia.git"
```

Append `@v0.1.0a4` to the URL to install that release. NAIA is not yet published
on PyPI, so `pip install naia` is not the command for this project.

NAIA's task/suite management and graph viewing need no GPU, PyTorch, or AI API key.
Your training and evaluation scripts still need their own dependencies.
To capture a model, install NAIA in the model's existing PyTorch environment.
NAIA does not install or replace Torch/CUDA. You can also use a
[separate management environment](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#execution-and-environments).

## Use in your project

Open your project with Codex or Claude and ask:

> Set up NAIA here. I use Codex and Claude.

The assistant first reads your project instructions and inspection exclusions.
It adds instructions to `AGENTS.md`, `CLAUDE.md`, or both without replacing existing
content, and uses repository evidence to propose the goal, training setup,
evaluation protocol, and other settings. You review a summary with file references,
confirm or correct it, and answer only what remains missing or uncertain.
Proposals stay unconfirmed until you approve them; existing confirmed answers
are preserved in `.lab/project.json`.

Then use ordinary requests: "Add a review task", "Test these learning rates",
or "Retry the failed evaluations". The instructions cover concise records,
review followups, launch validation, automatic evaluations, and duplicate checks.
NAIA uses your existing trainer, evaluator, and config system.

Ask the assistant to run `naia ui` to open the dashboard at
[localhost:8767](http://127.0.0.1:8767). Edit tasks, reorder the queue, change suite
status, and review cards there. Suite design and launches stay with your assistant
or the CLI.

For manual setup, run `naia init --assistant both` in your project, then ask the
assistant to complete onboarding. First initialization collects a bounded static
scan of README files, scripts, and configuration; your assistant interprets it.
Use repeatable `--exclude PATH` options for inspection exclusions, or `--no-scan`
to skip discovery. Use `codex` or `claude` if you use only one.

## What's included

- A prioritized task queue with owners and review decisions.
- Experiment suites with result tables, run tracking, and suite relationships.
- Sequential local runs or parallel Slurm jobs, with dependent evaluations.
- Analysis assignments linked to their inputs and outputs.
- NAIA Lens: a draggable, color-coded model graph with separate Flow and Hierarchy
  views, a reusable block glossary, intermediate tensor sizes, and captured-path playback.
  Lens is included in the same package and can also run on its own.

## Documentation

- [Examples](https://github.com/NazirNayal8/naia/blob/main/docs/INTERACTIONS.md)
- [Features and limits](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md)
- [CLI reference](https://github.com/NazirNayal8/naia/blob/main/docs/CLI.md) — optional direct control; includes a small CPU demo.
- [Release notes](https://github.com/NazirNayal8/naia/blob/main/CHANGELOG.md) and [TODO](https://github.com/NazirNayal8/naia/blob/main/TODO.md)

## Status

This is an early alpha. Local execution, installation, PyTorch capture, and the
browser UI have been tested. Slurm tests use a mocked scheduler; real-cluster
validation and interrupted-run recovery are still pending.

NAIA has no embedded chatbot or hosted service. Assistant instructions are not
a security sandbox; model capture executes trusted Python code. Try a small
project first, and [report issues](https://github.com/NazirNayal8/naia/issues)
without including credentials or private data.

For development: `pip install -e .`, then `python -m unittest discover -s tests -v`.
