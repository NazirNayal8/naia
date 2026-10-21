<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/naia-logo-dark.svg">
    <img alt="NAIA" src="docs/assets/naia-logo-light.svg" width="320">
  </picture>
</p>

<p align="center"><em>Your research, as a graph.</em></p>

Beta `0.1.0b2` · [MIT](https://github.com/NazirNayal8/naia/blob/main/LICENSE)

NAIA (Nazir's AI Assistant) is a tool to help manage your research project and accelerate it using Codex and/or Claude.

You talk to your existing assistant; NAIA keeps the tasks, experiments, results, and reports in your project. It is not a separate chatbot or hosted service.

## Experimental Suites

NAIA represents the research projects as a directed graph of experimental suites. A suite aims at exploring a certain research question. Within the suite, you can define several experiments and variations which all together aim at verifying the research question at hand.

You create a suite by proposing the idea to your agent, and your initial thoughts on how to implement it, what sub-experiments are required to verify it and so on. You can discuss with the agent back and forth until you converge on a certain set of experiments and controls. Once approved, NAIA will create a suite for you and give you the commands to launch the experiments. NAIA provides an interface where you can keep track of the suites as a graph. Each suite has a card that summarizes its design and contains result tables. During setup, your assistant adapts shared launchers to your existing training and evaluation scripts, with your approval. Once these are connected, launching a suite also schedules its declared evaluations, and each validated result updates the card automatically.

After this suite is done, the results will inspire new research questions. So when you create new suites after discussing the results of the previous one, NAIA will remember. Within your graph view, the new suites will be linked directionally to the previous suites. This is quite useful because at the end of the week, after trying multiple ideas after one another, the time of your research meeting will arrive, and you will forget how you have arrived at this point. But not any more. With NAIA, you can simply trace back your train of thought throughout the week by iterating over the suites from child to parent. Moreover, if you get stuck at some point, you can stare at the suite graph and decide to branch out with new ideas from an earlier stage in the project, because with NAIA, your thoughts are documented.

## Task Queue

With this, if you have 4 ideas that are totally separate at the same time, you can prepare their suites and launch them all together. However, the next day, you will wake up, look at your screen and ask yourself: "Why did I do this, what experiments should I track, and what results should I evaluate?" This is quite troublesome. NAIA has your back: your assistant keeps track of the reviews and decisions you need to make, and each completed suite automatically adds a review task. Open the task queue and work through these one by one. Each task contains its goal and the material you should review. You can also keep several tasks active; they are highlighted and stay at the top of the queue.


## NAIA Lens: the Architecture Visualizer

After having your assistant write lots of code, let's say you want to debug your architecture. But oops, there is a lot of code that you're unfamiliar with now and it will take days to look through it. Ask your assistant to add an experimental configuration to Lens. It will prepare a graph with project-aware names, connections, and intermediate tensor sizes that you can inspect at different granularities. You can play back a captured input path and compare separately captured model variants. Lens shows what was captured; it does not edit your model or run new configurations from the browser.


## Reports

Let's say you ran many experiments and found some interesting results. Now you want to inspect some properties of your method. Discuss the analysis with your agent, ask it to run it, and summarize the results in a report with interactive plots. You can edit the prose and captions, rearrange sections and visuals, replace any AI slop writing, and use the report directly in your research meeting. Chart data stays unchanged by these edits.

## Install

You need Python 3.10+ and Git. Install into a Python or Conda environment; no clone is needed:

```bash
pip install "git+https://github.com/NazirNayal8/naia.git"
```

Creating, editing, and exporting reports currently needs POSIX filesystem support; on Windows, use WSL for those features. NAIA is not yet published on PyPI, so `pip install naia` is not the command for this project.

<!-- Append `@v0.1.0b2` to the URL to install that release. NAIA is not yet published
on PyPI, so `pip install naia` is not the command for this project. -->

<!-- NAIA's task/suite management and graph viewing need no GPU, PyTorch, or AI API key. -->
Your training and evaluation scripts still need their own dependencies.
To capture a model, install NAIA in the model's existing PyTorch environment.
NAIA does not install or replace Torch/CUDA. You can also use a
[separate management environment](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md#execution-and-environments).

## Use in your project

### Onboarding

Installing NAIA does not automatically teach your assistant about it. Choose either setup path:

1. **Ask your assistant first.** Open your project with Codex or Claude and say:

   > NAIA is installed as a command-line tool. Run `naia policy` and `naia --help`, then set up NAIA here for Codex and Claude.

2. **Start from the terminal.** In your project, run:

   ```bash
   naia init --assistant both
   ```

   Start a new assistant session and ask it to read the installed project instructions and complete NAIA onboarding.

Use `codex` or `claude` instead of `both` if you use only one assistant.

Onboarding follows these steps:

1. Your assistant reads the project's instructions and permitted files, adds NAIA's guidance in `AGENTS.md` and/or `CLAUDE.md` without replacing your own text, and proposes what it understands instead of asking everything from scratch.
2. You confirm the goal, scope, training and evaluation commands, environments, and local or Slurm resources. A working submission script helps when using a cluster.
3. You agree on evaluation metrics and constraints, reporting preferences, and project rules. If using both assistants, you can give them different roles.
4. The assistant records the confirmed setup and checks readiness with `naia doctor`.

Missing or uncertain details are discussed with you; existing confirmed settings are preserved. These steps give the assistant the context it needs for future work.

To try NAIA before connecting your project, see the [small CPU demo](https://github.com/NazirNayal8/naia/blob/main/docs/CLI.md#try-the-demo).

### Finish the setup

Onboarding records the project settings; it does not connect every feature by itself. Ask your assistant:

> Finish setting up NAIA for this project: connect suite launching, automatic evaluation and result tables, add a representative model to Lens, and prepare an editable report from existing results.

The assistant should adapt shared Bash launchers, connect the evaluator's JSON metrics to table columns, and check a dry run before any approved jobs. For Lens, it captures and registers a model in its PyTorch environment. For Reports, it creates and checks an editable HTML report. If you have no results yet, the report can wait. Start with one small approved suite to verify the full training → evaluation → table → review-task cycle before launching a large sweep.

Then use ordinary requests: "Add a review task", "Test these learning rates",
or "Retry the failed evaluations". The instructions cover concise records,
review followups, launch validation, automatic evaluations, and duplicate checks.
NAIA uses your existing trainer, evaluator, and config system.


### Interface

You can open the NAIA interface by running `naia ui` in your project directory. It runs on the machine where your project is.

Each project gets an available random port and a `NAIA - <project folder>` tab title. Edit tasks, reorder the queue, change suite status, and review cards or interactive reports there. Suite design and launches stay with your assistant
or the CLI.

For a remote machine, [forward the interface port over SSH](https://github.com/NazirNayal8/naia/blob/main/docs/CLI.md#remote-dashboard). Keep local runs in a persistent terminal session such as `tmux` if you disconnect; submitted Slurm jobs do not depend on keeping the browser open.

### Suite Launching System

Your assistant reuses or adapts shared launchers for the environment confirmed during onboarding. Each experiment has its own tracked job. Local runs are sequential; Slurm runs can execute in parallel, with evaluations queued after successful training. Only evaluations run through the configured workflow update result tables automatically; NAIA does not import arbitrary old logs.


### Optional: install the setup skill

Run once per machine to make “Set up NAIA here” a discoverable assistant skill:

```bash
naia assistant install --assistant both
```

This installs a setup skill for Codex and Claude Code; it does not initialize a
project or change global instructions. Start a new session if the skill is not
visible. You can also invoke `$naia-setup` in Codex or `/naia-setup` in Claude Code.
After upgrading NAIA, rerun the command to refresh its managed skill copies.
Project rules still belong in each project's `AGENTS.md` and `CLAUDE.md`.

## What's included

- A prioritized task queue with owners and review decisions.
- Experiment suites with result tables, run tracking, and suite relationships.
- Sequential local runs or parallel Slurm jobs, with dependent evaluations.
- Analysis assignments linked to their inputs and outputs.
- Searchable HTML reports with shared charts, controls, editable prose, and offline export.
- NAIA Lens: a draggable, color-coded model graph with separate Flow and Hierarchy
  views, a reusable block glossary, intermediate tensor sizes, and captured-path playback.
  Lens is included in the same package and can also run on its own.

## Documentation

- [Examples](https://github.com/NazirNayal8/naia/blob/main/docs/INTERACTIONS.md)
- [Features and limits](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md)
- [CLI reference](https://github.com/NazirNayal8/naia/blob/main/docs/CLI.md) — optional direct control; includes a small CPU demo.
- [Release notes](https://github.com/NazirNayal8/naia/blob/main/CHANGELOG.md) and [TODO](https://github.com/NazirNayal8/naia/blob/main/TODO.md)

## Updating

```bash
pip install --upgrade "git+https://github.com/NazirNayal8/naia.git"
```

In each project, run `naia instructions install` to refresh its assistant guidance, then restart `naia ui`. If you installed the optional setup skill, rerun `naia assistant install --assistant both` too, using your chosen assistant instead of `both` if needed.

For a fixed version, append its release tag to the installation URL; available versions are listed in the [release notes](https://github.com/NazirNayal8/naia/blob/main/CHANGELOG.md).

Try a small suite first. Broader real-cluster validation and recovery from interrupted local launchers are still in progress; see [known limits](https://github.com/NazirNayal8/naia/blob/main/docs/FEATURES.md).

## Customization

NAIA should fit your project, not the other way around. Ask your assistant to adjust the project rules, execution resources, evaluation profiles, report layouts, or model capture adapters. It should keep your existing configuration system unless you agree to change it. Keep your own instructions outside NAIA's managed sections so guidance updates preserve them.

For a new feature or a different interface, you can fork NAIA and install your checkout with `pip install -e .`. You and your assistant can change it as you like under the [MIT license](https://github.com/NazirNayal8/naia/blob/main/LICENSE). Keep source changes in your fork rather than editing an installed package that the next upgrade would replace.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the fork, test, and review workflow.

Bug reports, documentation fixes, and pull requests are welcome. For a larger feature, open an [issue](https://github.com/NazirNayal8/naia/issues) first so we can discuss the approach.

Fork and clone the repository, create a branch for your change, then run from the checkout's root:

```bash
pip install -e .
python -m unittest discover -s tests -v
```

Open a pull request against `main` explaining what changed and how you tested it. Add a regression test for a bug fix where possible. Model-capture and viewer tests need PyTorch and Node.js respectively; some tests skip when these are unavailable, so mention what you ran. Please leave out credentials, private project data, and generated experiment files.

<!-- ## Status

This is a beta release. Local execution, installation, PyTorch capture, and the
browser UI have been tested. Slurm tests use a mocked scheduler; real-cluster
validation and interrupted-run recovery are still pending.

NAIA has no embedded chatbot or hosted service. Assistant instructions are not
a security sandbox; model capture executes trusted Python code. Try a small
project first, and [report issues](https://github.com/NazirNayal8/naia/issues)
without including credentials or private data.

For development: `pip install -e .`, then `python -m unittest discover -s tests -v`. -->
