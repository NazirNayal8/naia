# Features & options

[README](../README.md) · [Interaction examples](INTERACTIONS.md) · [CLI reference](CLI.md)

## Project context and assistant contract

Choose Codex, Claude, or both with `naia init --assistant <choice>`. Setup installs
a managed contract in root `AGENTS.md`, `CLAUDE.md`, or both, preserving existing
text and upgrading an older managed block. If no choice is recorded, setup
returns a question for the assistant to ask once. The selection is stored in
`.lab/project.json`; both assistants share project state, with no assigned lead
role. Existing projects can use `naia instructions install --assistant both`.

Ask the assistant to read the installed rules now, or start a new session.
Codex's [instruction precedence](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
can override root `AGENTS.md`; NAIA warns about a nonempty root `AGENTS.override.md`
without changing it. Switching integrations never deletes previously installed files.

Onboarding records seven confirmed topics in `.lab/project.json`:

| Topic | Options and decisions |
| --- | --- |
| Project | Goal, scope, success criteria, excluded work. |
| Hardware | Local or Slurm, GPUs, memory, environments, shared paths. |
| Execution | Existing training/evaluation commands, completion artifacts, resume behavior. |
| Evaluation | Metrics, data splits, seeds, budgets, controls, constraints. |
| Reporting | Preferred formats and output destinations. |
| Configuration | Preserve the current system; discuss Hydra for a new project or approved migration. |
| Governance | Approval boundaries, documentation limits, retention, excluded paths. |

Fresh projects start with confirmed reporting and governance defaults: concise
suite cards and the standard policy, with no declared exceptions or exclusions.
The assistant inspects the repository and asks about unresolved choices in the
other five topics. Reporting or governance questions concern changes to those
defaults. Setup preserves customized answers in existing projects.

Launches require confirmed onboarding and a confirmed execution backend. Changing
answers or backend settings requires reconfirmation. NAIA preserves your stack;
it does not automatically convert configurations or create evaluators.

The installed contract supplies defaults you do not need to repeat in prompts:

- Create user-review tasks after substantive discussions, evaluations, and
  analyses; maintain existing followups with evidence and the next decision.
- Write concisely; avoid unsolicited documents and per-suite scripts.
- Register, validate, dry-run, and show a brief plan before an authorized launch.
- Run declared evaluations automatically and check tracked work before submitting
  jobs to avoid duplicates.
- Ask before deletion, scope expansion, or recording unapproved interpretations.

Hardware, evaluation protocol, and other meaningful project choices still need
confirmation. The contract guides the assistant; it is not a security sandbox or
an independent authentication system. Never store credentials in project context.

## Task queue

Tasks carry a title, goal, decision, owner, evidence references, related-task IDs,
and notes. Available actions are create, assign, move to top, start, pause, resume,
complete, and cancel.

States: `ready`, `active`, `paused`, `done`, `cancelled`. Only one task is active;
the next task is the active one, otherwise the first ready one. Resuming a paused
task returns it to ready. Related-task IDs do not enforce dependency completion.

Task-field editing, deletion, and reopening are not implemented. The browser
hides completed/cancelled tasks; the CLI can list all stored tasks.

## Suites and results

A suite groups experiments around a question. Its definition declares:

- Named cells with finite scalar parameters and optional scientific predecessors.
- Training/evaluation argument lists, environment overrides, and optional timeouts.
- A completion artifact, plus an optional resume artifact and resume command.
- Evaluation profiles with expected JSON metric paths and optional `min`/`max` directions.

Commands reuse your scripts, not a new launcher per suite. Predecessor links form
scientific lineage—not scheduler dependencies.

Registration creates a concise card, reserves result rows, and adds the suite to
the registry. Approved definitions are immutable; changed designs need a new suite.
Validated results update generated table blocks without rewriting authored prose.
Run identity links the suite, cell, attempt, definition, artifact checksum, and
evaluation profile. This checks provenance, not scientific correctness.

Suite lifecycle is `approved` or `sealed`; job states and result readiness are
separate. Once all declared results are ready, NAIA queues one review task.
Sealing requires user approval and blocks new training, not evaluation or existing
jobs. Arbitrary suite-status editing and reopening are not implemented.

## Execution and environments

| Option | Behavior |
| --- | --- |
| Local | Runs cells and declared evaluations sequentially. |
| Slurm | Submits parallel training and `afterok` dependent evaluations. |
| Automatic evaluation | On by default for declared profiles; explicit recovery opt-out. |
| Selection | Limit execution to a cell and/or evaluation profile. |
| Dry run | Show the plan without creating launch records. |
| Retry | New attempt for failed work; evaluation-only retry does not retrain. |
| Completion checks | Reuse verified completed work; inspect uncertain jobs before resubmitting. |

`naia` includes the task workflow and Lens and can live in your project environment
or in a separate lightweight management environment. It invokes your existing
scripts; training/evaluation do not need NAIA unless they call it themselves.

Backend `command_python` chooses the interpreter substituted for training
`{python}`; `evaluation_python` can choose a different evaluator environment. If
omitted, training uses NAIA's interpreter and evaluation inherits the training
interpreter. The default is the interpreter running `naia suite launch`, not an
automatically discovered project environment. Explicit interpreter paths remain
explicit. Optional command-prefix lists and per-command environment variables
support wrappers.

Slurm requires a shared `management_python` with NAIA installed, plus separate
training/evaluation resource settings if needed. Supported resource fields:
`partition`, `account`, `qos`, `time`, `mem`, `cpus-per-task`, `gres`, `constraint`,
`exclude`. See the [backend template](../examples/slurm_profile.json).

## Browser dashboard

Ask your assistant to open the local dashboard at `http://127.0.0.1:8767`.
It binds to loopback and uses a session token; it is not a hosted collaboration
service. Another port can be selected when starting it.

| Area | Current controls |
| --- | --- |
| Tasks | Start, pause, resume, finish with an optional note, and move ready tasks to top. |
| Suites | View cards, lineage, and lifecycle or result-readiness labels. |
| Results | Refresh validated results and generated card blocks; queue missing reviews. |
| Architecture | Select saved model graphs, inspect hierarchy and tensor shapes, and see suite/task associations. |
| Context | Read recorded answers and onboarding status. |

No browser task-text editor, suite-status controls, launch controls, or context
editor yet. Ask your assistant to create tasks, assign/cancel them, and seal
suites. Cards currently display plain Markdown source. Refresh is manual; the
browser result refresh does not reconcile scheduler state like `naia sync` does.

## Analysis assignments

An approved analysis records its ID, question, instructions, existing inputs,
expected output paths, and optional owner. NAIA queues a linked task; execution
and report generation belong to your assistant/analyst and existing tools.

Markdown, PDF, LaTeX, or other reporting preferences are context, not built-in
report renderers. Input/output references must stay inside the project.

## NAIA Lens

Lens is included in the single `naia` installation and is optional to use.
A trusted Python factory supplies a model and example inputs; capture runs in
that model's existing PyTorch environment, with NAIA installed there. A separate
management or pipx environment can view the graph but cannot capture the model
without its dependencies. Managing and viewing saved graphs needs no PyTorch.

Ask your assistant to register a saved graph with a title and optional links to
an experiment suite and review task. The project dashboard's Architecture tab
shows these captures alongside the workflow. Registration requires an initialized
project, but not completed launch onboarding. It validates the graph inside the
project root and stores a read-only path reference and checksum.
Keep registered captures unchanged; register a new graph and ID for a revision.

Standalone `naia arch capture`, `validate`, and `view` work without project setup.
Standalone viewing opens at `http://127.0.0.1:8768`; the integrated viewer is in
the main dashboard at `http://127.0.0.1:8767`. The browser reads saved graphs;
it does not execute factories or capture every training run automatically.

Expand/collapse blocks, inspect recorded module metadata and tensor shapes, and
play observed calls. Module enumeration records hierarchy; hooks record observed
calls and shapes. Optional best-effort FX tracing adds supported data-flow edges.
Hook order alone does not establish tensor dependencies.

Capture copies the model: use small inputs and a new output filename. Observed
calls and shapes cover the supplied input path, not every possible branch.
Playback is illustrative, not a profiler; Lens does not edit the model.

## Records and portability

| Location | Contents |
| --- | --- |
| `.lab/project.json` | Assistant selection, confirmed context, policies, execution backends. |
| `.lab/tasks.json` | Task queue and decision notes. |
| `.lab/suites/<ID>/` | Registered definition and durable card. |
| `.lab/state/registry.json` | Derived suite registry for the graph. |
| `.lab/state/runs/` | Attempt records, logs, artifacts, evaluation results. |
| `.lab/analyses/` | Approved analysis instructions and evidence references. |
| `.lab/architectures.json` | Validated graph references, checksums, and optional suite/task links. |

Records are local and inspectable. NAIA does not upload them or require an AI API
key; your chosen assistant's own setup is separate. `lab`, `naia-arch`, and
`lab-arch` remain compatibility commands. This unified MIT-licensed alpha is not
published on PyPI yet and still needs real-cluster validation
and historical import/migration.
