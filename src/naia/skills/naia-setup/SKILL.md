---
name: naia-setup
description: Set up NAIA (Nazir's AI Assistant) in a project using its installed CLI. Use when asked to initialize NAIA, configure its Codex or Claude integration, or complete NAIA onboarding.
---

# Set up NAIA

NAIA is a local project-management CLI, not an AI model. This skill handles
onboarding; project-specific workflow rules are installed separately.

1. Read the project's existing assistant instructions and inspection exclusions.
   Resolve the intended project root; ask if it is ambiguous.
2. Run `naia --help` and `naia policy`. If `naia` is unavailable, read the
   `installation.json` beside this skill for the installing environment's Python
   executable, then use that executable with `-m naia.cli`. If it no longer works,
   ask for the NAIA environment; do not install packages or change environments
   silently. Reuse the working executable prefix for all commands below.
3. Use `naia --project ROOT` for project commands below, with the resolved root
   quoted as needed. Check whether this project already has `.lab/project.json`.
   Preserve confirmed answers. A malformed or incomplete workspace needs inspection, not
   deletion or replacement. Do not adopt an ancestor's workspace if the user
   intends to initialize a separate project.
4. Use the user's choice of Codex, Claude, or both; ask only if unspecified.
   For requested setup, run `naia --project ROOT init --assistant CHOICE`,
   passing existing inspection exclusions through repeatable `--exclude PATH`
   options, or `--no-scan` if discovery is not permitted. In an initialized
   project, use `naia --project ROOT instructions install --assistant CHOICE`
   if integration needs updating. Read the resulting `AGENTS.md` and/or `CLAUDE.md` now; existing
   project instructions still apply. With both assistants, ask about optional
   roles without choosing a lead automatically.
5. Read `naia --project ROOT context questions` and available discovery evidence.
   Infer the goal, execution, evaluation, configuration and hardware from permitted
   files. Use `naia --project ROOT context propose` with file citations and show
   one concise summary for confirmation; ask only about missing, uncertain or conflicting settings.
   Do not change the project's configuration system as part of onboarding.
6. Record proposals, answers and backends as confirmed only after the user
   approves them. Complete `naia --project ROOT context confirm --by NAME` when
   its prerequisites are satisfied, then run `naia --project ROOT doctor`. Setup
   does not authorize experiments, evaluations, publishing or destructive changes.
7. Summarize what is configured and what is pending. Offer
   `naia --project ROOT ui` for review; follow the installed project rules for
   future tasks and suites. Do not create extra notes, runbooks or reports.
