# NAIA command reference

[README](../README.md) · [Interaction examples](INTERACTIONS.md) · [Features & options](FEATURES.md)

Use conversation with your assistant to plan and approve work, and the browser to review project context, tasks, suites, and evidence. The CLI is a secondary interface for setup, automation, and recovery. These commands describe the development alpha exported here.

## Install and open

Install once using the [README instructions](../README.md#get-started), with
Python 3.10+. Then enable NAIA in any project; no NAIA checkout is needed there:

```bash
cd /path/to/your/project
naia init --assistant both
naia policy
naia context questions
naia ui
```

Open `http://127.0.0.1:8767`; change the port with `naia ui --port 9000`. One NAIA
installation includes the workflow and Lens. Neither workflow nor graph viewing
needs PyTorch; model capture runs in your model's PyTorch environment. `lab`,
`naia-arch`, and `lab-arch` remain compatibility commands.

For a source checkout, run `python -m pip install .`. This unified version is
not published on PyPI yet. `pipx` is optional and must be installed separately.
A pipx-managed NAIA needs explicit project interpreters in its backend;
it does not use your activated environment by default.

Commands discover `.lab/project.json` in the current directory or its ancestors. Select a project explicitly with `naia --project /path/to/project <command>`.

`--assistant codex`, `--assistant claude`, or `--assistant both` selects root
`AGENTS.md`, `CLAUDE.md`, or both. Setup installs or upgrades a managed contract
without replacing existing text and stores the choice in `.lab/project.json`.
Plain `naia init` returns the assistant-choice question if no choice is recorded;
your assistant asks once.
Both integrations share the same state and rules, without assigned lead roles.

For an existing project:

```bash
naia instructions install --assistant both
```

Positional filenames remain compatible: `naia instructions install AGENTS.md CLAUDE.md`.
The contract makes review followups, concise writing, launch preparation,
automatic declared evaluations, and duplicate checks default assistant behavior.
You do not need to request these steps in each prompt.

## Try the demo

Use a fresh directory for the synthetic CPU example; no GPU is needed:

```bash
naia --project ./naia-demo demo
cd naia-demo
naia suite launch DEMO
naia ui
```

Two tiny runs produce automatic evaluations, updated cards, and one review task.
Demo confirmation applies only to this synthetic project.

## Confirm onboarding

Context has seven fields: `project`, `hardware`, `execution`, `evaluation`,
`reporting`, `configuration`, and `governance`. Fresh projects confirm built-in
reporting and governance defaults; the assistant inspects the repository and
asks only about unresolved choices in the other five. Discuss reporting or
governance exceptions when needed. Setup preserves existing customized context.
Review project-specific answers, exclusions, and execution paths before confirming.

```bash
naia context show
naia context set project --value @project-answer.json
```

`--value` accepts JSON or `@file`. This records an unconfirmed answer. Add
`--confirmed` after the user confirms a project-specific answer or a change to
the defaults. Do not infer user approval for unresolved project choices.

Configure a user-approved local or Slurm backend, then finalize onboarding:

```bash
naia context backend local --file local.json --confirmed
naia context confirm --by YOUR_NAME
naia doctor
```

`local.json` may contain `{"kind":"local"}`. Final confirmation requires a named user, seven confirmed answers with nonempty values, and at least one confirmed backend. Launches, including dry runs, require confirmed onboarding and the selected confirmed backend. Changing an answer or backend resets onboarding to pending; reconfirm afterward.

The installed defaults do not replace confirmation of hardware, evaluation
protocol, execution settings, or other meaningful project choices.

## Tasks

```bash
naia task add REVIEW --title "Review results" \
  --goal "Inspect evidence" --decision "Choose the next experiment"
naia task list
naia task next
naia task start REVIEW
naia task done REVIEW --note "Approved the follow-up"
```

Other actions: `pause`, `resume`, `cancel`, `move-top`, and `assign ID --owner NAME`. Each accepts `--note`. Add supports `--owner`, repeated `--material` and `--depends-on`, and `--top`. Dependencies reference existing tasks but do not block selection. `next` favors the active task, then the first ready task; only one task can be active.

## Suites and recovery

Prepare an approved JSON definition containing `schema_version: 1`, ID, title, question, cells, training `argv`, completion artifact, and evaluation profiles with commands and expected metric paths. Reserve results before execution.

Within authorized work, the assistant registers and validates the suite, runs a
dry run, and presents a brief plan before launching. The following commands are
available for direct control or recovery; users can simply ask to launch a suite.

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

Use `--approved-by` and sealing only for actual user approval. Launch/evaluate accept `--backend`, `--cell`, `--profile`, `--dry-run`, and `--retry`; launch also supports `--no-auto-eval` for recovery. Local work runs sequentially; Slurm queues dependent evaluations automatically. Verified completed work is reused. Evaluation retry preserves earlier evidence without retraining; training retry creates a new attempt. Inspect uncertain states before retrying. Dry runs create no launch records. Changed definitions require a new suite. Sealing blocks new training but permits evaluation; there is no general suite-status setter.

## Backends and records

Slurm profiles require shared `management_python`; optional `command_python`, `evaluation_python`, command-prefix lists, and separate `resources`/`evaluation_resources` select execution environments. Install NAIA in the management environment. See the [backend template](../examples/slurm_profile.json).

Records live in `.lab/project.json`, `tasks.json`, `suites/<ID>/{suite.json,card.md}`, `state/registry.json`, `state/runs/<suite>/<cell>/<attempt>/`, and `analyses/`. `sync` reconciles tracked Slurm jobs, refreshes validated result tables, and queues reviews when all results are ready.

## Analysis assignments

`naia analysis add analysis.json --approved-by YOUR_NAME` records an approved question, instructions, existing input paths, output paths, and optional owner, then queues a task. The assistant performs the analysis.

## NAIA Lens

Capture, validation, and standalone viewing do not require an initialized project:

```bash
naia arch capture --factory module:build --output graph.json --trace
naia arch validate graph.json
naia arch view graph.json
```

The trusted factory returns `(model, example_args, example_kwargs)`. Capture executes copied model/sample inputs; choose a new output filename. Lens opens at `http://127.0.0.1:8768` (`--port` overrides it). Observations cover the supplied input; playback shows call order, not timing. FX tracing is optional and best effort.

To connect a saved graph to the project dashboard, register it from an initialized
project. Full launch onboarding is not required:

```bash
naia arch add BASELINE --graph artifacts/baseline.json --title "Baseline model" \
  --suite BASELINE_SUITE --task REVIEW_BASELINE
naia arch list
naia ui
```

`--suite` and `--task` are optional links to existing records. The graph must be
inside the project root. Registration validates it and stores its relative path
and checksum; it does not modify the graph. Select it in the dashboard's
Architecture tab, or follow its suite/task links. The dashboard reads saved
graphs; it does not execute factories or automatically capture training runs.
For a changed capture, use a new graph filename and registration ID.
`naia-arch` and `lab-arch` keep standalone capture/validate/view compatibility.

## Help

`naia --help`, `naia suite launch --help`, and `naia arch capture --help`.
