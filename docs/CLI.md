# NAIA command reference

[README](../README.md) · [Examples](INTERACTIONS.md) · [Features](FEATURES.md)

Use your existing Codex or Claude assistant to set up projects and run approved work.
Use the browser to review tasks, suites, results, and model graphs.
The CLI is for direct control, automation, and recovery.

## Install and open

Follow the [installation steps](../README.md#install) with Python 3.10+.
From a source checkout, use `python -m pip install .`. This version is not on PyPI yet.
Read existing project instructions and inspection exclusions before initialization.

```bash
cd /path/to/your/project
naia init --assistant both
naia policy
naia context questions
naia ui
```

Open `http://127.0.0.1:8767`; use `naia ui --port 9000` to change the port.
Commands find `.lab/project.json` in the current directory or its ancestors.
Select a project with `naia --project /path/to/project <command>`.

Choose `codex`, `claude`, or `both` to install managed rules in root `AGENTS.md`, `CLAUDE.md`, or both.
Setup preserves existing text. Without a recorded choice, `naia init` returns a question for your assistant.
For an already initialized NAIA project, use `naia instructions install --assistant both`.
See [assistant setup and defaults](FEATURES.md#project-setup).

First `naia init` scans permitted README files, scripts, and configuration for static
evidence. Add repeatable `--exclude PATH` options with relative paths or globs,
or `--no-scan` to skip it:

```bash
naia init --assistant both --exclude archive
naia context scan --exclude archive
```

`context scan` refreshes discovery in an initialized project. The scan is bounded
and skips common secret files, symlinks, and generated data; your assistant interprets
the evidence. See [discovery limits](FEATURES.md#project-setup).

## Try the demo

This synthetic CPU example requires a fresh directory:

```bash
naia --project ./naia-demo demo
cd naia-demo
naia suite launch DEMO
naia ui
```

Two small runs produce evaluations, updated cards, and one review task.
The demo confirms setup only for its own synthetic project.

## Confirm setup

Your assistant proposes project choices from evidence, shows a summary with file
references, and asks you to confirm or correct it. It asks separate questions only
for missing or uncertain details. Fresh projects already have reporting and governance
defaults; the other five topics need confirmed proposals or answers.
See [context fields](FEATURES.md#project-setup).

```bash
naia context show
naia context propose project --value @project-proposal.json --evidence README.md:3
naia context accept project --by YOUR_NAME
naia context backend local --file local.json --confirmed
naia context confirm --by YOUR_NAME
naia doctor
```

`propose` accepts JSON or `@file` and requires one or more repeatable
`--evidence FILE[:LINE]` references relative to the project root.
Proposals are unconfirmed and separate from answers. Use `accept` only after actual
user confirmation, and repeat for each proposed field. Discovery and proposals do
not overwrite existing confirmed answers. `context set FIELD --value JSON|@FILE`
remains available for direct answers; add `--confirmed` only after user approval.
`local.json` can contain `{"kind":"local"}`. Final confirmation needs a named user, seven confirmed
nonempty answers, and at least one confirmed backend. Launches, including dry runs, require this setup
and a confirmed selected backend. Changing an answer or backend resets setup to pending; confirm again.

## Tasks

```bash
naia task add REVIEW --title "Review results" \
  --goal "Inspect evidence" --decision "Choose the next experiment"
naia task list
naia task next
naia task start REVIEW
naia task done REVIEW --note "Approved the follow-up"
```

Other actions: `pause`, `resume`, `cancel`, `move-top`, and `assign ID --owner NAME`; each accepts `--note`.
Add accepts `--owner`, repeated `--material` and `--depends-on`, and `--top`. Related tasks do not block selection.
See [queue behavior](FEATURES.md#task-queue).

## Suites and recovery

Prepare an approved [suite definition](FEATURES.md#suites-and-results) in JSON. Your assistant registers it,
reserves results, validates it, runs a dry run, and shows a brief plan before an authorized launch.

```bash
naia suite add suite.json --approved-by YOUR_NAME
naia suite validate SUITE
naia suite show SUITE
naia suite launch SUITE --dry-run
naia suite launch SUITE
naia sync
naia suite evaluate SUITE --retry
naia suite seal SUITE --by YOUR_NAME
```

Registration and sealing require actual user approval. Launch/evaluate accept `--backend`, `--cell`,
`--profile`, `--dry-run`, and `--retry`. Declared evaluations run automatically; use launch's
`--no-auto-eval` only for recovery. Local work runs sequentially; Slurm queues dependent evaluations.
Completed work is reused after verification.

Evaluation retry preserves earlier evidence without retraining; training retry creates a new attempt.
Inspect uncertain states before retrying. Dry runs create no launch records. Changed definitions need a new suite.
Sealing blocks new training but permits evaluation. `naia sync` checks tracked Slurm jobs, updates validated
results, and queues reviews when results are ready.

## Execution environments

Training `{python}` uses backend `command_python`, or NAIA's interpreter if omitted.
Evaluation uses `evaluation_python`, or inherits the training interpreter.
For a separate management or pipx installation, set project interpreter paths explicitly;
activating another environment does not change them.

Slurm needs a shared `management_python` with NAIA installed. See the [backend template](../examples/slurm_profile.json)
and [environment options](FEATURES.md#execution-and-environments) for command prefixes and separate evaluation resources.

## Analysis assignments

`naia analysis add analysis.json --approved-by YOUR_NAME` records approved instructions and input/output paths,
then queues a task. Your assistant performs the [analysis](FEATURES.md#analysis-assignments).

## NAIA Lens

Capture runs in your model's PyTorch environment, with NAIA installed there. Viewing needs no PyTorch.
These commands work without project setup:

```bash
naia arch capture --factory module:build --output graph.json --trace
naia arch validate graph.json
naia arch view graph.json
```

The trusted factory returns `(model, example_args, example_kwargs)`. Capture runs copies of the model
and inputs in evaluation mode, without gradients; use small inputs and a new output filename.
Results cover that input path.
Playback shows call order, not timing. FX tracing is optional and best effort.
Standalone viewing opens at `http://127.0.0.1:8768`; `--port` changes it.

Register a saved graph inside an initialized project to view it in the dashboard:

```bash
naia arch add BASELINE --graph artifacts/baseline.json --title "Baseline model" \
  --suite BASELINE_SUITE --task REVIEW_BASELINE
naia arch list
naia ui
```

The graph must be inside the project root. `--suite` and `--task` link existing records and are optional.
Registration validates the graph and records its path and checksum; full launch setup is not required.
Select it in the Architecture tab. Keep registered graphs unchanged; use a new file and ID for a revision.
The dashboard reads saved graphs. See [Lens details](FEATURES.md#naia-lens).

## Help and records

Use `naia --help`, `naia suite launch --help`, or `naia arch capture --help`.
See [project files](FEATURES.md#project-files). `lab`, `naia-arch`, and `lab-arch` remain compatibility commands.
