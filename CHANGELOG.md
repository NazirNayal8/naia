# Release notes

## 0.1.0a9

- Inline editing of marked report text and static captions with Save/Cancel.
- Scroll-preserving, unboxed editing; add, remove, restore, and rearrange sections and visuals.
- Source-only patches, conflict detection, and one recoverable previous HTML version.
- Report data, charts, metadata, and offline exports remain read-only.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.

Verified: 326 tests, 28 local/exported browser checks, package builds, and isolated installation.

## 0.1.0a8

- Shared SVG report kit: bars, lines, scatter plots, tables, controls, and keyboard tooltips.
- Explicit metrics and dimensions; missing values and duplicate rows are not silently aggregated.
- `naia report new` creates a draft; `export` produces one offline HTML file without overwriting work.
- Responsive figures, accessible numbers and tooltips, and report-writing instructions for assistants.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.

Verified: 289 tests, local/exported browser checks, offline export, package builds, and isolated installation.

## 0.1.0a7

- Reports tab with text search, tag filters, and automatic folder discovery.
- Isolated report viewer with themes, bookmarked controls, and suite/task links.
- `naia report list` and `check`, configurable limits, and report workflow instructions.
- Protected report assets and loopback write APIs; reports cannot modify project records.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.
The shared chart kit and standalone export are planned for the next phase.

Verified: 250 tests, browser parity/security checks, package builds, and isolated installation.

## 0.1.0a6

- Project-aware names for major components and inputs/outputs, with cited evidence in the inspector.
- Assistant instructions infer meanings from project sources and ask when uncertain;
  internal layers keep type-based labels.
- `naia arch annotate` adds names to an existing capture without rerunning the model
  or changing its connections and tensor sizes. Capture also accepts `--semantics`.
- Semantic names work across hierarchy, search, comparisons, both themes, and SVG export.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.
Previously saved graphs need annotations to show semantic names.

Verified: 212 tests, browser checks, package builds, and isolated installation.

## 0.1.0a5

- Compact layer pictograms and short type captions replace information cards.
- Full tensor sizes appear on draggable arrow chips; module details stay in the inspector.
- Clearer colours and silhouettes, including photo-frame inputs, vector bars,
  circular arithmetic, convolution hexagons, pooling funnels, and projection wedges.
- Image symbols require declared layout or recorded spatial-processing evidence.
- Both themes, hierarchy, dragging, playback, comparison, and SVG export remain supported.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.

Verified: 195 tests, browser checks, package builds, and isolated installation.

## 0.1.0a4

- Reusable catalogue of 64 block types with coordinated colours, shapes, and pictograms.
- Built-in searchable glossary; block labels show computational types, with model names
  and paths kept in the inspector. Verified size changes control tapered shapes.
- More precise module and operation classification, including arithmetic distinctions
  and neutral fallbacks for custom layers.
- Dragging, playback, comparison, both themes, and SVG export remain supported.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.

Verified: 188 tests, browser checks, package builds, and isolated installation.

## 0.1.0a3

- Optional, user-confirmed roles for Codex and Claude: peers, either lead/support direction,
  or custom responsibilities and boundaries, reflected in each assistant's instruction file.
- Role updates preserve existing project settings and instructions, with rollback on write failure.
- Explicit assistant workflow for adding models to Lens: inspect, capture, validate, register,
  and verify access in the Architecture tab.

Existing projects refresh managed instructions with `naia instructions install` after upgrading.

Verified: 165 tests, package builds, and isolated installation.

## 0.1.0a2

- Sample capture follows tensor dependencies by default, including branches and residual updates.
- Flow and Hierarchy views separate execution from ownership; layers show type-based names,
  distinct glyphs, and observed input/output sizes.
- Assistant instructions cover source/config inspection, grounded sample inputs, and readable aliases.
- Explicit structure-only capture, tracing opt-out, and partial-capture warnings remain available.

Existing hierarchy-only graphs need recapturing to show tensor dependencies.

Verified: 149 tests, real-capture Chromium checks, package builds, and isolated installation.

## 0.1.0a1

- Existing-project setup collects bounded repository evidence for assistant review.
- Assistants propose context with file references; users confirm or correct it.
  Discovery keeps proposals unconfirmed and preserves confirmed settings.
- Scan exclusions and manual setup without scanning are available.
- Restored the local research UI's dark task deck and draggable suite graph,
  including task editing, archiving, status controls, and rendered suite cards.
- Replaced the tree-only Lens screen with a draggable, color-coded graph,
  hierarchy levels, shape inspection, playback, saved layouts, comparison, and SVG export.
- Removed the separate project-context tab; onboarding records are unchanged.

Verified: 114 tests, Chromium dashboard/viewer checks, package builds, and isolated installation.

## 0.1.0a0

Initial alpha release:

- One MIT-licensed package with no mandatory runtime dependencies.
- Project context and instructions for Codex, Claude, or both.
- Task queue, experiment suites, result syncing, and review tasks.
- Local execution and Slurm submission with dependent evaluations and duplicate checks.
- Analysis assignments with evidence references.
- Browser dashboard and Lens model inspection, with suite/task links.
- Standalone architecture commands and compatibility with the earlier command names.

Verified: 74 tests in Python 3.10 with PyTorch, package builds and isolated
installation, and Chromium checks for the dashboard and both Lens viewers.

Real-cluster validation, interrupted-run recovery, migration, and PyPI publication
are pending. Task and suite editing improvements are included in 0.1.0a1.
See [TODO](TODO.md).
