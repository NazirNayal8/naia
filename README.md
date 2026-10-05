# NAIA

**Nazir's AI Assistant** · Less bookkeeping. More research.

An assistant-first workspace for research: discuss the next experiment with
Codex or Claude, review it in the browser, and keep tasks, results, and model
architectures connected.

Local-first · Python 3.10+ · [MIT](https://github.com/NazirNayal8/naia/blob/main/LICENSE) · Alpha `0.1.0a0`

[Get started](#get-started) · [Examples](https://github.com/NazirNayal8/naia/blob/main/docs/INTERACTIONS.md) · [Features](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md) · [Release notes](https://github.com/NazirNayal8/naia/blob/main/CHANGELOG.md) · [TODO](https://github.com/NazirNayal8/naia/blob/main/TODO.md)

## Your assistant is the front door

> “Test these learning-rate values.”

You discuss the research; your assistant translates approved decisions into NAIA
records and commands. NAIA handles the bookkeeping and execution. It does not
replace your assistant or provide an embedded chatbot.

Setup installs shared defaults: concise writing, review tasks after substantive
discussions and results, validated launch plans, automatic declared evaluations,
and duplicate-job checks. You do not need to repeat them in each request.

| Interface | Use it for |
| --- | --- |
| **AI assistant — primary** | Onboarding, creating tasks, designing suites, launching approved work, and discussing results. |
| **Browser — visual companion** | Reviewing the queue, changing task progress and priority, exploring suites and results, and inspecting linked model architectures. |
| **CLI — optional, secondary** | Direct control, automation, diagnostics, and recovery. |

## Get started

### 1. Install once

One package includes the workflow and NAIA Lens. With Python 3.10+ and Git
available, install directly into your chosen Python or Conda environment:

```bash
pip install "git+https://github.com/NazirNayal8/naia.git"
```

No manual clone needed. For the tagged alpha, append `@v0.1.0a0` to the URL.
PyPI publication is pending; `pip install naia` is not the install command for
this project yet. From a source checkout, use `pip install .` instead.

Workflow and graph viewing need no GPU, PyTorch, Hydra, or AI API key. Lens is
optional to use. Model capture runs in your existing PyTorch environment, with
NAIA installed there; it does not install or replace your Torch/CUDA stack.
Separate management environments are covered in the
[environment guide](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#execution-and-environments).

### 2. Enable it in your project

You do not need to clone NAIA inside your research project. Open that project
with your usual assistant and ask:

> “Set up NAIA here. I use Codex and Claude.”

Choose **Codex**, **Claude**, or **both**. NAIA installs its managed contract in
`AGENTS.md`, `CLAUDE.md`, or both, preserving existing instructions. Both assistants
share the same project context and queue. If you do not specify a choice, your
assistant asks once.

The assistant inspects existing configuration and asks only about unresolved
goals, hardware, execution, evaluation, and configuration choices. Fresh projects
use confirmed reporting and governance defaults; discuss exceptions when needed.
Your existing training stack stays in place, and context lives in
`.lab/project.json`. Hardware and evaluation choices still need your confirmation.

Ask your assistant to run `naia ui`; the dashboard is available at
[localhost:8767](http://127.0.0.1:8767). Prefer to explore first? Ask it to run the
[tiny CPU demo](https://github.com/NazirNayal8/naia/blob/main/docs/CLI.md#try-the-demo).

For a manual bootstrap only: run `naia init --assistant both` from your project's
root, then ask the assistant to read the installed instructions and complete
setup. Choose `codex` or `claude` if you use just one. Repeat this project step
for each repository; reinstalling NAIA is not necessary.

## What stays organized

| Feature | What it gives you |
| --- | --- |
| [Task queue](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#task-queue) | One next decision, explicit ownership, and a prioritized review queue. |
| [Experiment suites](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#suites-and-results) | Approved run grids, concise cards, reserved result rows, and scientific lineage. |
| [Run automation](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#execution-and-environments) | Sequential local runs or parallel Slurm jobs, with automatic declared evaluations. |
| [Analysis assignments](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#analysis-assignments) | Investigations tied to instructions and input/output evidence paths. |
| [NAIA Lens](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#naia-lens) | Hierarchical model inspection, tensor shapes, and forward-call playback, linked to suites and review tasks. |

Keep your existing trainer, evaluator, and configuration system. NAIA connects
them through approved definitions rather than imposing a new research stack.
Inspect models in the dashboard's Architecture tab without mixing capture into
every training run.

## Explore

- [Conversation examples](https://github.com/NazirNayal8/naia/blob/main/docs/INTERACTIONS.md): everyday requests to your assistant.
- [Features & options](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md): capabilities, settings, storage, and limits.
- [CLI reference](https://github.com/NazirNayal8/naia/blob/main/docs/CLI.md): secondary commands for direct control and recovery.
- [Release notes](https://github.com/NazirNayal8/naia/blob/main/CHANGELOG.md) and [TODO](https://github.com/NazirNayal8/naia/blob/main/TODO.md): what is available and what remains.

## Alpha status

Local workflows, package installation, PyTorch capture, and browser rendering
have been tested. Slurm contracts are tested with mocked scheduler responses;
real-cluster validation remains pending. UI text editing, historical migration,
and interrupted-process recovery are still on the TODO list.

NAIA is local-first, not a hosted collaboration service. Its assistant rules guide
behavior; they are not authentication or a security sandbox. Capture runs trusted
Python factories, and playback is illustrative—not a latency measurement.

Try a small project first. [Report a bug](https://github.com/NazirNayal8/naia/issues)
with the command, expected behavior, and a minimal example; redact private paths,
credentials, and research data.

For contributors: `pip install -e .`, then
`python -m unittest discover -s tests -v`. CI checks package builds and fresh
installation; PyTorch capture has a separate CPU test job.
