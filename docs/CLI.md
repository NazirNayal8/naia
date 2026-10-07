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

## Assistant roles

With both integrations selected, your assistant asks about optional roles and records
your confirmed choice. Presets are `peers`, `codex-lead` (Claude support), and
`claude-lead` (Codex support); no hierarchy is assumed automatically.

```bash
naia instructions roles --preset codex-lead --by YOUR_NAME
naia instructions roles --file roles.json --by YOUR_NAME
```

Use either a preset or a custom file after user confirmation. `roles.json` contains:

```json
{
  "codex": {"role": "ROLE", "responsibilities": ["RESPONSIBILITY"], "boundaries": ["BOUNDARY"]},
  "claude": {"role": "ROLE", "responsibilities": ["RESPONSIBILITY"], "boundaries": ["BOUNDARY"]}
}
```

The assignment is stored under `.lab/project.json`'s `assistants.roles`. Updating it
refreshes assistant-specific role sections in both managed instruction files and preserves
existing text. Roles remain optional, do not block onboarding when unanswered, and are
inactive with a single integration. They do not authorize launches, expand scope, or
automatically invoke another assistant.

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

## Reports

```bash
naia report list --query "action dynamics" --tag planning
naia report check
naia report check DATA_AUDIT
naia report new DATA_AUDIT --title "Data audit"
naia report export DATA_AUDIT --out exports/data-audit.html
naia --reports-root docs/reports ui
```

`list` searches static report text; repeat `--tag` for AND filters. `check` exits 1
on invalid reports. All report commands emit JSON. Reports are discovered automatically from the
[configured folder](FEATURES.md#reports); there is no `add` command.
Use `report:DATA_AUDIT` with task `--material` to link its viewer. Existing projects
refresh assistant guidance with `naia instructions install` after upgrading.

`new` creates an empty kit-based draft, not analysis results. `export` inlines local
assets and the chart kit into one HTML file that opens offline. The output must be
inside the project, outside the live reports folder; it never overwrites an existing
file. Missing or network-dependent assets fail explicitly.
Creation and export currently require POSIX descriptor-relative filesystem support.

## NAIA Lens

Capture runs in your model's PyTorch environment, with NAIA installed there. Viewing needs no PyTorch.
These commands work without project setup:

```bash
naia arch capture --factory module:build --output graph.json
naia arch validate graph.json
naia arch view graph.json
```

The trusted factory returns `(model, example_args, example_kwargs)`. Capture runs copies of the model
and inputs in evaluation mode, without gradients; use small inputs and a new output filename.
Sample capture records tensor dependencies by default; results cover that input path.
`--trace` remains a compatibility flag. `--no-trace` records calls and shapes without
dataflow; `--structure-only` skips the sample forward entirely. The factory still runs.
`--aliases '{"encoder":"Token encoder"}'` or `--aliases @labels.json` supplies module-path labels.
These aliases stay in the inspector. For major components and meaningful inputs/outputs,
your assistant infers short names from project sources and asks you when the meaning is unclear.
It records those names separately from measured layer types and dependencies:

```bash
naia arch annotate graph.json --semantics @semantics.json --output named-graph.json
naia arch validate named-graph.json
```

`semantics.json` maps exact captured node IDs to source-grounded names, for example:

```json
{
  "module:encoder": {"name": "Visual encoder", "role": "encoder", "evidence": ["models/world.py:42 defines the observation encoder"]},
  "input:0": {"name": "Observation frames", "evidence": ["models/world.py:56 documents the observation input"]}
}
```

Use actual IDs and citations, not these illustrative references. Only major modules and
boundaries need semantic names; primitive layers remain type-based. Annotation writes a
new graph without running the model or changing captured flow. Capture also accepts
`--semantics JSON|@FILE`. Register the named graph under a new ID; never replace registered evidence.
Playback shows saved calls or dependencies, not timing. Capture limits and fallback warnings stay in the graph.
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
