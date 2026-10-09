# Public highlight acceptance — 2026-10-09

The manual-event API now supports preparing and accepting real compiled plans,
rejecting drafts, disabling/re-enabling accepted intent, and undoing acceptance.
This advances P4.4 and the backend portion of P7.3. Preview, UI and real xLights
visual verification remain unfinished.

## Implementation

- `src/review/api/v1/generation_inputs.py` extracts the existing export argument
  assembly: source fallback, committed layout, themes/sliders, story, lyrics,
  words/phonemes, vocal options, preferences, video and other extra occurrences.
  Export and highlight actions share it; no approximate baseline is constructed.
- `src/evaluation/generator_runner.py` accepts an optional `HighlightDraftRequest`.
  It captures context from the actual baseline, assigns a server plan ID, compiles
  treatments with the loaded layout/catalog, and serializes the result before
  returning the immutable plan. Ordinary calls still return XSQ bytes. Runner
  pipelines share a process lock because they seed global random generators;
  simultaneous runner calls cannot reseed each other's baseline assembly.
- `src/review/api/v1/highlights.py` adds revision-checked lifecycle endpoints.
  Acceptance, re-enable and undo rebuild and compile against current inputs.
  Session/library/source/layout/story changes detected during generation prevent
  the write; storage compare-and-swap catches intervening highlight edits.
  Rejected proposals and failed validation preserve existing saved intent.
- `src/review/api/v1/export.py` uses the accepted seed for enabled replay when the
  request omits a seed/reroll. Explicit baseline exports retain the existing song
  default. Explicit different seeds/rerolls remain subject to stale-plan rejection.
- Tests add public workflow coverage and concurrent-runner seed isolation.
  The existing GET validation-status assertion was updated to the new truthful
  `not_checked` response. No golden files or failure markers were changed.

Design and regression analysis: [acceptance.md](../../openspec/changes/ai-highlights-foundation/acceptance.md).
The historical `.wolf/` files remain unavailable.

## API contract

All actions are `POST /api/v1/songs/<song_id>/highlights/<action>` with JSON.
Save event reviews first using the existing PUT highlights route. Every action
requires the current integer `expected_revision`; successful writes advance it.

| Action | Additional fields | Result |
|---|---|---|
| `draft` | `treatments` (1–500), optional uint32 `variation_seed` | Compiles/saves a draft; preserves accepted/enabled state |
| `accept` | `plan_id` of the saved draft | Revalidates, enables the draft, retains previous accepted plan |
| `reject` | `plan_id` of the saved draft | Clears only the draft |
| `disable` | None | Disables replay, preserves all snapshots |
| `enable` | None | Revalidates and enables the accepted plan |
| `undo` | None | Revalidates and swaps accepted/previous plans; clears draft |

Example draft body (the event and target must already exist):

```json
{
  "expected_revision": 1,
  "variation_seed": 42,
  "treatments": [{
    "treatment_id": "wash_1",
    "event_id": "manual_sweep",
    "recipe_id": "sustained_wash",
    "targets": ["MatrixCenter"],
    "intensity": 0.7
  }]
}
```

Use the returned state revision and draft plan ID to accept. Clients cannot
submit context fingerprints, plan snapshots, provenance, XML, or enable flags.
Unknown fields, duplicate JSON keys, nonfinite numbers, oversized requests and
invalid scalar types are rejected. Event timing/recipe/target and conflict
validation still use the existing compiler. Empty draft submissions are rejected;
disable is the explicit baseline control (the compiler still supports no-op plans).

Responses retain `state`, `source`, `issues`, and `plan_validation`. Successful
compile actions report `valid` with the validated `plan_id`. GET/event edits report
`not_checked` when snapshots exist: loading JSON does not validate the current
layout, themes or source context. Reject/disable return `source: null` because
they deliberately do not decode audio; they work even when audio/layout is missing.
A fresh accepted state is loaded from disk on each subsequent action/export.

Defaults match export: vocal diarization and extra timing enabled. Drafts use the
accepted seed when one exists, otherwise the deterministic song seed, unless
explicitly overridden. Nondefault generation options are not separately persisted
by this slice; callers changing export options may need to replan. There are no
AI calls, automatic treatment selection, progress jobs, cancellation or UI yet.

## Verification

Initial focused run: **125 passed, 1 skipped**. Final selected regression run,
including the shared-input and concurrent-seed tests: **1171 passed, 4 skipped,
4 non-strict xpasses, 5 warnings**, in 8.72 seconds.

```sh
NUMBA_CACHE_DIR=/private/tmp/xlight-numba .venv/bin/python - <<'PY'
import logging
from unittest.mock import patch
import pytest
with patch('src.log.get_logger', side_effect=logging.getLogger):
    raise SystemExit(pytest.main([
        'tests/unit/test_generator', 'tests/evaluation/test_generator_runner.py',
        'tests/review/test_highlight_acceptance.py', 'tests/review/test_highlight_export.py',
        'tests/review/test_api_export.py', 'tests/review/test_api_highlights.py',
        'tests/review_storage/test_highlights.py', 'tests/unit/test_highlight_models.py',
        'tests/unit/test_generation_config.py', 'tests/integration/test_section_preview.py',
        '-q', '--tb=short', '--show-capture=no',
    ]))
PY
```

Logger substitution prevents existing logger setup from writing into the home
directory. Tests isolate state via `XLIGHT_STATE_HOME`. The end-to-end acceptance
fixture uses generated audio, known synthetic hierarchy and a deliberately quiet
theme; grouping, decoding, context capture, compilation, serialization and export
are real. Other tests intentionally fake the runner to isolate input forwarding.

Public PUT → draft → accept → export twice produces equal XSQ bytes at seed 42,
with wash segments at **8275–9725 and 9725–10125 ms** on MatrixCenter. Explicit
baseline output differs from enhanced output. Tests also cover lifecycle history,
stale source/layout/sections/events, missing inputs for recovery actions, invalid
targets/contracts, corrupt sidecars, wrong IDs/revisions, changes during generation,
and the full saved-option mapping shared with export.

Generated workflow artifacts live in pytest's temporary directories. Earlier
retained compiler/baseline artifacts remain linked in the roadmap. No frontend
build, full acceptance gate, old-golden comparison, live provider request, listening
benchmark or xLights render was run. Existing skips/xpasses are unchanged; the
previously documented legacy golden drift was not reevaluated by this command.

## Limits and next work

This is a synchronous local API workflow. Arbitrary external file edits and
writers in other processes are not transactional. The runner lock does not cover
legacy code that independently seeds global RNGs outside this runner. Export
revalidates saved context again rather than trusting acceptance forever.

Next: thread enabled accepted state/revision into scoped preview and cache identity,
preserve/clamp relevant song-level highlight placements, then complete actual
xLights rendering. Busy overlapping groups remain conservatively rejected until
P4.3 compositor work. Portable sidecar backup, timeline controls, individual
acceptance/regeneration, listening labels and automatic detection remain pending.

## Small preview follow-up

`src/generator/preview.py` now passes its already parsed layout into build_plan.
This removes a missing prerequisite for highlight context validation; accepted
state, scoped highlight placements and cache identity are still pending.
Added one regression in tests/integration/test_section_preview.py. Ran the same
logger-isolated pytest command above with only that test file: **14 passed**.
The initial test exposed an unused legacy fixture missing TimingMark confidence;
the new test now uses a minimal hierarchy stub and does not change that fixture.
The test checks the real parsed layout handoff, with plan/writer stubbed.

## Scoped XSQ timestamp bounds follow-up

The writer now intersects model-effect times (including highlights) with an
explicit preview window and omits empty intersections. Full-song serialization
and source placements remain unchanged. Six boundary cases cover inside,
outside, both clipped edges and a spanning highlight; each also verifies an
unchanged subsequent full export. Partial effect envelopes are not resampled,
and timing tracks are not clipped by this step. Actual preview state/cache
forwarding and visual verification remain pending.

Verification: **189 passed, 4 warnings**. Use the logger-isolated pytest invocation
above with `tests/unit/test_generator/test_xsq_writer.py` and
`tests/integration/test_section_preview.py` only; flags remain
`-q --tb=short --show-capture=no`. `git diff --check` passed.

## Scoped highlight preservation follow-up

Section preview now retains already compiled highlights intersecting its window
and includes them in placement_count. Source placements remain unchanged; the
writer handles their offset and timestamp clipping. The layout-handoff test now
covers baseline and enhanced cases using a known plan and real XSQ writer, with
analysis and plan assembly stubbed. Both boundary crossings, an interior highlight
and exclusion of outside placements are verified. Initial test timings assumed a
15-second window; they were corrected to the existing 20-second preview limit.

The preceding logger-isolated command with preview integration and XSQ writer
tests passed **190 tests, 4 warnings**. Route-level accepted-state/cache forwarding,
other song-level collections, partial-envelope fidelity and rendering remain pending.
