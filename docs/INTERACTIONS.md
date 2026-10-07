# Working with NAIA

[README](../README.md) · [Features](FEATURES.md) · [CLI](CLI.md)

These are requests to your existing Codex or Claude assistant, not built-in chat
commands. NAIA does not call an AI model. Once setup is complete, you do not need
to repeat the workflow rules.

## Setup

> Set up NAIA here. I use Codex and Claude.

The assistant reads existing instructions and inspection exclusions first, then
checks permitted README files, scripts, and configuration. NAIA's static scan
collects evidence; your assistant uses it to infer the project goal, training
commands, evaluation protocol, and other settings.

It shows a summary with file references for you to confirm or correct, then asks
only about missing or uncertain details. Proposals remain separate from confirmed
answers until you approve them. Existing confirmed settings are preserved.
For Slurm, share a submission script if the repository does not supply enough evidence.

## Tasks

> Remind me to review the baseline before increasing model capacity.

> Pause that review, assign the data audit to Alex, and show me the next task.

The assistant updates the queue. You can also change task status and priority
in the browser, but editing task titles and goals is not yet supported there.

## Experiments

> Test learning rates 0.0001, 0.0003, and 0.001.

The assistant resolves missing choices with you and prepares a suite using your
existing training and evaluation commands.

> Launch this suite.

It validates the suite, shows a dry-run plan, and launches the approved work.
Declared evaluations run automatically: sequentially locally, or after successful
training on Slurm.

> Retry the failed evaluations.

The assistant checks tracked attempts first. Completed work is reused; uncertain
job state needs investigation before retrying.

## Review

> What do these results tell us?

Results update the suite card, and a review task is queued when all declared
results are ready. The assistant discusses the findings; it records conclusions
only after you approve them.

> I approve that conclusion. Seal the suite.

Sealing prevents new training. It does not cancel jobs or block evaluations.

## Analysis and model inspection

> Assign Alex a probing analysis of these checkpoints.

NAIA records the assignment and its evidence paths. Alex or an assistant still
needs to perform the analysis.

> Turn this analysis into an interactive report and attach it to the review task.

The assistant uses approved results, adds HTML and metadata to the reports folder,
validates it, and checks it in the Reports tab. Search, tag filters, and related
task/suite links are provided by NAIA; figures and controls belong to the report.

> Show this model's layers and tensor sizes in Lens. Attach it to the baseline suite.

The assistant captures the model in its PyTorch environment and links the saved
graph. In Lens, expand blocks, inspect shapes, and play the captured forward calls.
Playback is illustrative, not a timing measurement. Saved graphs can also be
viewed without PyTorch or project setup.
