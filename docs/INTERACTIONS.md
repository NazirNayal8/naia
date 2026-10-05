# Working with NAIA

[README](../README.md) · [Features](FEATURES.md) · [CLI](CLI.md)

These are requests to your existing Codex or Claude assistant, not built-in chat
commands. NAIA does not call an AI model. Once setup is complete, you do not need
to repeat the workflow rules.

## Setup

> Set up NAIA here. I use Codex and Claude.

The assistant checks the repository, asks about unresolved project choices, and
installs instructions for the selected assistants. Share an example submission
script if you use Slurm. Review the project settings before confirming them.

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

> Show this model's layers and tensor sizes in Lens. Attach it to the baseline suite.

The assistant captures the model in its PyTorch environment and links the saved
graph. In Lens, expand blocks, inspect shapes, and play the captured forward calls.
Playback is illustrative, not a timing measurement. Saved graphs can also be
viewed without PyTorch or project setup.
