# Features

[README](../README.md) · [Interaction examples](INTERACTIONS.md) · [CLI reference](CLI.md)

## Project setup

`naia init --assistant <choice>` selects Codex, Claude, or both. Setup adds managed rules
to root `AGENTS.md`, `CLAUDE.md`, or both, preserving existing text and updating older blocks.
If no choice is recorded, setup returns an assistant-choice question. The choice is stored in
`.lab/project.json`; both assistants share state, with no automatically assigned lead. Already
initialized NAIA projects can use `naia instructions install --assistant both`.

When both are selected, the assistant asks about optional roles: peers, Codex lead with
Claude support, the reverse, or custom responsibilities and boundaries. It records only
your confirmed choice under `assistants.roles` in `.lab/project.json` and refreshes the
assistant-specific role sections in managed `AGENTS.md` and `CLAUDE.md`, preserving existing text.
An unanswered role question does not block onboarding; assignments are inactive with a
single integration. Roles do not authorize launches, expand scope, or automatically
invoke another assistant. See the [role commands](CLI.md#assistant-roles).

Ask the assistant to read the rules, or start a new session. Codex's
[instruction precedence](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
can override root `AGENTS.md`. NAIA warns about a nonempty root `AGENTS.override.md`
but leaves it alone. Switching integrations does not delete installed files.

For an existing project, the assistant reads instructions and inspection exclusions
before discovery. First initialization collects bounded static evidence from permitted
README files, scripts, and configuration. The assistant infers the goal, training and
evaluation setup, and other context, then shows a summary with file references for
you to confirm or correct. It asks only about missing or uncertain details.

The scan is a helper, not a full repository audit or an embedded AI model. It skips
common secret files, symlinks, and generated data. Repeat `--exclude PATH` with
relative paths or globs to omit more files, or use `naia init --no-scan` to skip
discovery. Evidence and assistant proposals are stored separately from confirmed
answers in `.lab/project.json`.
Proposed answers require explicit user confirmation; discovery never replaces
confirmed settings.

Onboarding records seven topics in `.lab/project.json`:

| Topic | Options and decisions |
| --- | --- |
| Project | Goal, scope, success criteria, excluded work. |
| Hardware | Local or Slurm, GPUs, memory, environments, shared paths. |
| Execution | Commands, completion artifacts, resume behavior. |
| Evaluation | Metrics, splits, seeds, budgets, controls, constraints. |
| Reporting | Formats and output destinations. |
| Configuration | Keep the current setup; discuss Hydra for new projects or approved migrations. |
| Governance | Approvals, documentation limits, retention, excluded paths. |

New projects start with confirmed reporting and governance defaults: concise suite cards
and the standard policy, with no exceptions or exclusions. The assistant proposes the
other topics from evidence where possible. Setup keeps custom answers. Launches require
confirmed onboarding and a confirmed backend; changes require reconfirmation.
NAIA does not convert configurations or create evaluators.

The rules tell assistants to maintain review tasks, avoid unsolicited documents and
per-suite scripts, and register, validate, dry-run, and show a plan before authorized
launches. They require declared evaluations, duplicate checks, and approval before
deletion, scope expansion, or recording unapproved interpretations. These are assistant
instructions, not a sandbox or authentication system. Keep credentials out of context.

## Task queue

Tasks have a title, goal, decision, owner, evidence, related-task IDs, and notes.
You can create, assign, move to top, start, pause, resume, complete, or cancel them.
States are `ready`, `active`, `paused`, `done`, and `cancelled`. Only one task can be active;
it comes next, otherwise the first ready task does. Resume makes a paused task active.
Related-task IDs do not enforce completion dependencies. The browser supports editing,
drag reordering, and recoverable removal; removed IDs remain reserved. It hides closed
tasks from the queue and shows removed tasks in the archive. Reopening is not implemented.
The CLI can list all tasks.

## Suites and results

A suite groups experiments around a question. Its definition lists named cells with
finite scalar parameters, optional scientific predecessors, training/evaluation arguments,
environment overrides, and optional timeouts. It declares a completion artifact, optional
resume artifact and command, and evaluation profiles with expected JSON metric paths
and optional `min`/`max` directions.

Commands call existing scripts. Predecessors record scientific lineage, not scheduler
dependencies. Registration creates a card, reserves result rows, and adds the suite to
the registry. Approved definitions are immutable; changed designs need a new suite.
Validated results update generated tables without rewriting prose. Run identity links
the suite, cell, attempt, definition, artifact checksum, and evaluation profile.
It checks provenance, not scientific correctness.

Suites are `approved` or `sealed`, separate from job states and result readiness.
When all declared results are ready, NAIA queues one review task. Sealing requires
user approval and blocks new training; evaluation and existing jobs can continue.
The browser can change workflow status or seal/reopen an approved suite. Display
labels do not approve an experiment or launch work; sealed/shelved suites block
new training. Existing approval and result fingerprints are preserved.

## Execution and environments

| Option | Behavior |
| --- | --- |
| Local | Run cells and declared evaluations sequentially. |
| Slurm | Submit training in parallel and evaluations with `afterok` dependencies. |
| Automatic evaluation | On for declared profiles; explicit recovery opt-out. |
| Selection | Choose a cell and/or evaluation profile. |
| Dry run | Show the plan without launch records. |
| Retry | Create a new attempt; evaluation-only retries do not retrain. |
| Completion checks | Reuse verified work; inspect uncertain jobs before resubmitting. |

NAIA can run in the project environment or a separate management environment.
Training/evaluation scripts need NAIA only if they call it. `command_python` supplies
training `{python}`; `evaluation_python` can select a different interpreter. By default,
training uses the interpreter running `naia suite launch`, and evaluation inherits it.
NAIA does not automatically select or activate a project environment. Explicit paths stay explicit;
command-prefix lists and per-command environment variables support wrappers.

Slurm needs a shared `management_python` with NAIA installed. Training and
evaluation can have separate resources. Supported fields are
`partition`, `account`, `qos`, `time`, `mem`, `cpus-per-task`, `gres`, `constraint`,
`exclude`. See the [backend template](../examples/slurm_profile.json).

## Browser dashboard

The dashboard opens at `http://127.0.0.1:8767`, with a selectable port, loopback binding,
and a session token. It uses the local research UI's dark theme and three views:

- Task queue: create/edit tasks, pack/unpack cards, drag to reorder, start/pause/resume,
  complete with a note, and remove into a recoverable archive.
- Suite graph: drag cards, pan/zoom, hide sealed suites, open rendered cards, and edit
  workflow status or seal/reopen a suite.
- Architecture: inspect saved graphs with the Lens canvas below.

Refresh reads validated results and queues missing reviews; it never launches jobs.
It does not query the scheduler—use `naia sync` for that. Project context remains
onboarding data, not a separate browser tab. Markdown, code, and tables render in
the card viewer; equations use a local MathJax installation when available
(`NAIA_MATHJAX_ROOT`). No CDN is used.

## Analysis assignments

An approved analysis records an ID, question, instructions, existing inputs, expected
output paths, and optional owner. NAIA queues a linked task; your assistant or analyst
runs it with existing tools. Reporting preferences such as Markdown, PDF, or LaTeX do not
provide built-in renderers. Input and output references must stay inside the project.

## NAIA Lens

Lens is optional and included in `naia`. Capture runs a trusted Python factory supplying
a model and example inputs. It needs the model's PyTorch environment with NAIA installed;
viewing and managing saved graphs do not need PyTorch.

Register a saved graph with a title and optional suite/task links to show it in the
Architecture tab. Registration needs an initialized project, not completed launch
onboarding. It validates a graph inside the project and stores a read-only path reference
and checksum. Keep that file unchanged; revisions need a new graph and ID.

Standalone `naia arch capture`, `validate`, and `view` work without project setup.
The standalone viewer uses `http://127.0.0.1:8768`; the dashboard uses port `8767`.
The browser reads saved graphs and does not run factories or capture training runs.
Drag nodes and arrow bends, pan/zoom, switch hierarchy levels, search, inspect module
metadata and shapes, save layouts, export SVG, and play observed calls. Compare two or
three registered captures side by side or as an overlay. Colors match the local viewer.
Module enumeration records hierarchy; hooks record calls and shapes. Sample capture also
records runtime tensor dependencies by default, with best-effort FX fallback. Observed,
traced, and explicitly declared evidence remain distinct; hook order alone does not prove flow.
Use `--no-trace` for calls/shapes only, `--structure-only` to skip the sample forward, and
`--aliases` for readable module-path labels. The factory still runs in either mode.

Capture runs copies of the model and inputs in evaluation mode, without gradients.
Use small inputs and a new output filename. Calls and shapes describe the supplied
input path, not every branch. Playback is illustrative, not a profiler.
Lens does not edit the model.

## Project files

| Location | Contents |
| --- | --- |
| `.lab/project.json` | Assistant selection and confirmed roles, discovery evidence, unconfirmed proposals, confirmed context, policies, execution backends. |
| `.lab/archive.json` | Snapshots of removed tasks; original IDs remain reserved. |
| `.lab/tasks.json` | Task queue and decision notes. |
| `.lab/suites/<ID>/` | Registered definition and durable card. |
| `.lab/state/registry.json` | Derived suite registry for the graph. |
| `.lab/state/runs/` | Attempt records, logs, artifacts, evaluation results. |
| `.lab/analyses/` | Approved analysis instructions and evidence references. |
| `.lab/architectures.json` | Validated graph references, checksums, and optional suite/task links. |

Records stay local; NAIA does not upload them or require an AI API key. Your assistant's
setup is separate. `lab`, `naia-arch`, and `lab-arch` remain compatibility commands.
This MIT-licensed alpha is not on PyPI yet; real-cluster validation and historical
import/migration remain unfinished.
