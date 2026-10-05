# Working with NAIA

[README](../README.md) · [Features & options](FEATURES.md) · [CLI reference](CLI.md)

Your assistant is the main interface. These are example requests, not built-in
chat commands: the assistant reads project context, clarifies missing details,
and uses NAIA's tools. NAIA itself does not call an AI model.

Setup supplies the workflow rules once. Everyday requests can stay short.

## Set up a project

> “Set up NAIA here. I use Codex and Claude.”

Choose Codex, Claude, or both. The assistant asks once if you omit the choice.
NAIA installs a managed contract in `AGENTS.md`, `CLAUDE.md`, or both and preserves
existing text. The selection and confirmed context live in `.lab/project.json`;
both assistants use the same state without an assumed lead or assistant role.

The assistant inspects the repository and asks only about unresolved goals,
hardware, execution, evaluation, and configuration choices. Fresh projects use
confirmed reporting and governance defaults; questions about these concern your
exceptions or preferences. Existing custom answers are preserved. For Slurm,
share an example submission script and environment paths. Review project-specific
answers before confirming them.

The contract supplies concise writing, no unsolicited documents, automatic
review followups, launch preparation, declared evaluation, and duplicate checks.
Your assistant asks before deletion, scope expansion, or recording unapproved
interpretations. Project-specific hardware and evaluation choices still need
confirmation; you do not need to restate these defaults.

## Keep the next decision clear

> “Remind me to review the baseline before increasing model capacity.”

> “Pause that review, assign the data audit to Alex, and tell me the next ready
> task.”

The assistant can create, assign, prioritize, pause, resume, complete, or cancel
tasks. Each task records a goal, decision, owner, and evidence references.
After substantive discussions, evaluations, and analyses, it creates user-review
tasks or maintains existing ones with relevant evidence and the next decision.

In the browser, use **Start**, **Pause**, **Resume**, **Done**, or **Move to top**
where offered. **Done** can record a short decision note. Existing task-text
editing is not implemented in this alpha; the browser changes progress and
ready-task priority, not titles or goals.

## Turn a hypothesis into a suite

> “Test these learning-rate values: 0.0001, 0.0003, 0.001.”

The assistant resolves missing scientific choices with you and prepares a
machine-readable definition using your existing trainer and evaluator.

> “Launch this suite.”

For authorized work, registration, validation, a dry run, and a brief launch plan
are automatic preparation. Registration reserves result rows. The assistant uses
the confirmed backend, checks existing jobs, and enables declared evaluations.
It asks when a launch would exceed the approved design or resources.

Local runs execute sequentially. Slurm training runs can execute in parallel;
declared evaluations queue after successful training. The browser shows suite
cards and scientific lineage; it is not a launch console.

## Review and close the loop

> “What do these results tell us?”

Validated metrics update generated card tables. When every declared result is
ready, NAIA queues one suite-review task. The assistant discusses conclusions
with you, creates or maintains followup review tasks, and records interpretations
only after approval; NAIA does not generate scientific explanations.

> “I approve that conclusion. Seal it.”

Sealing is currently assistant/CLI-led, not a browser control. It blocks new
training, but does not cancel jobs, delete evidence, or block evaluations.

## Recover without duplicating work

> “Retry the failed evaluations.”

The assistant inspects tracked attempts before choosing a retry. Completed work
is reused; uncertain state needs investigation, not a blind resubmission.

## Assign analysis and inspect models

> “Investigate what these checkpoints encode. Assign the probing analysis to Alex.”

NAIA records the approved assignment and queues a task. The analyst or assistant
performs it; recording an assignment does not run the analysis automatically.

> “Show this model's architecture and intermediate tensor sizes in Lens.”

Lens comes with the same NAIA installation. The assistant captures the model in
its existing PyTorch environment, registers the saved graph, and opens the
dashboard's Architecture tab. If a graph already exists, it can register and
view it without PyTorch.

> “Attach this architecture to the baseline suite and its review task.”

The assistant links the capture to existing suite/task records so model structure
and experiment evidence stay together. In Lens, expand blocks, select layers,
inspect inputs/outputs, and play observed forward calls. Playback illustrates one
captured execution, not measured latency. The dashboard does not run model
factories or automatically capture every run.

> “Show this saved architecture without setting up a project.”

The standalone viewer opens the graph directly. Capture and validation also work
without project setup through `naia arch`.
