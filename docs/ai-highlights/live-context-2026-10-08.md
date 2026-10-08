# Live context and accepted-plan export — 2026-10-08

The actual generation/export path now validates and compiles enabled saved highlight plans. It computes context from current inputs instead of trusting a plan's claimed fingerprints. Plan creation/acceptance through the public API and section preview are **not yet implemented**; the existing manual-event API continues to reject plan/enable fields. This is internal replay support, not the completed user workflow.

## Changes

- [highlight_context.py](../../src/generator/highlight_context.py) measures actual audio SHA-256/MD5 and production-decoder duration. It rejects a hierarchy from different bytes or a different audio clock. It fingerprints the current hierarchy, effective/reviewed sections and story, layout tree and resolved groups/props, effect/theme libraries, recipes, seed/settings and assembled baseline. Referenced FILEPICKER assets and configured video use file-content identity. Unsupported/nonfinite context values and unavailable assets fail explicitly.
- [build_plan](../../src/generator/plan.py) appends context/compilation after complete baseline assembly. `GenerationConfig.highlight_state=None` and `capture_highlight_context=False` preserve the old path with no new hashing/decoding. Setting capture true returns `SequencePlan.highlight_context` for future plan preparation. Enabled state requires matching source/duration and passes its accepted plan/current reviews to the compiler against newly computed context.
- [generator_runner](../../src/evaluation/generator_runner.py) forwards optional immutable state and reviewed sections. Failures retain an issue code such as `stale_plan`, `analysis_source_mismatch`, or `generation_inputs_changed`. Audio/layout identity is checked across generation and writing.
- [export](../../src/review/api/v1/export.py) snapshots enabled sidecars, forwards them through the real runner/config/build/compiler/writer path, and checks review/session/library inputs again before publishing. It resolves the first existing audio path, matching playback and manual-event editing. It preserves the exact layout bytes used by an enhanced export in its downloaded package.

Appended defaulted fields/arguments preserve old constructor/function call sites. Defaults still export the baseline when there is no enabled state. Renaming the audio or changing the output directory/display title does not by itself change highlight identity. Fingerprints conservatively include complete loaded catalogs and actual placements; even a change that ultimately has little visual impact can require revalidation.

Source/layout identity is checked around generation; referenced assets are checked during context construction. These checks do not make arbitrary external file writes transactional. The future acceptance endpoint must revalidate current inputs when committing, not copy a previously captured context and assume it is still current.

## Export contract

Existing `POST /api/v1/songs/<id>/export` accepts an optional `highlights` boolean:

| Request | Behavior |
|---|---|
| Omitted | Replay enabled accepted state, otherwise baseline |
| `false` | Explicit baseline export; do not read the sidecar |
| `true` | Require enabled accepted state, otherwise 409 `highlights_unavailable` |
| Wrong type | 400 `invalid_highlights` |

An unreadable/unsupported sidecar produces 409 `highlight_state_unreadable` unless baseline export was explicitly requested. A changed/stale plan fails the asynchronous job with an issue `code` and message; it does not silently produce baseline output or modify the saved accepted plan. Review/session/source changes during export prevent publication. Older jobs keep their own in-memory snapshots.

Public plan acceptance remains gated: developer tests construct/save accepted snapshots only after actual baseline-context capture. No user should have to hand-edit these files as the finished workflow. The next endpoint must prepare/compile a draft against precisely the same export settings, validate it again on acceptance, preserve previous accepted intent, and honor revision checks. A rerolled seed invalidates the saved context.

## Verification

**1137 passed, 4 skipped, 4 non-strict xpasses, 5 warnings** in the initial selected regression run. A final explicit-null flag rejection test was then added; the export-specific rerun passed **14 tests**. The full selected command is:

```sh
NUMBA_CACHE_DIR=/private/tmp/xlight-numba .venv/bin/python - <<'PY'
import logging
from unittest.mock import patch
import pytest
with patch('src.log.get_logger', side_effect=logging.getLogger):
    raise SystemExit(pytest.main([
        'tests/unit/test_generator', 'tests/evaluation/test_generator_runner.py',
        'tests/review/test_highlight_export.py', 'tests/review/test_api_export.py',
        'tests/review/test_api_highlights.py', 'tests/review_storage/test_highlights.py',
        'tests/unit/test_highlight_models.py', 'tests/unit/test_generation_config.py',
        'tests/integration/test_section_preview.py', '-q', '--tb=short', '--show-capture=no',
    ]))
PY
```

The existing logger substitution isolates home-directory writes. The broader suite verifies generator behavior, storage/manual editing, actual export forwarding and existing preview behavior. It does not mean highlights now appear in preview.

New tests demonstrate:

- Live build_plan context and nonempty highlight replay without mutating the baseline; changed theme, sliders, reviewed sections, layout, analysis, catalog or seed invalidate the accepted plan.
- Disabled state avoids context work. Renames and output locations leave identity unchanged. Missing/mismatched audio analysis, changed layout during generation and changed/missing referenced assets are detected.
- Real runner/config/build_plan/compiler/writer replay emits the expected 8275–9725/9725–10125 ms wash and 10500–10750 ms impact, and repeated output is equal.
- Real export endpoint → runner → compiler → writer → download package preserves those placements and the generation-time layout. The end-to-end test uses known synthetic analysis and a deliberately quiet fixture theme; the real grouper/decoder/generator/serializer run. Test threads run synchronously. Other export-policy tests stub the runner intentionally to isolate errors/races. This is not automatic detection or render validation.

The first attempt at the runner integration test used an empty group list with a regular theme, exposing the existing fallback target `ALL_MODELS`, absent from the fixture layout. The compiler correctly rejected that dangling target. The final integration test uses actual grouping and an explicitly quiet fixture theme; it does not weaken target or overlap checks.

Old golden-file drift remains unresolved and was not included in this selected command. Instead, the four actual generator equivalence configurations were generated using unchanged HEAD models/writer/plan and current code in separate processes. All four canonical XSQ hashes still match exactly. [Audit script and outputs](../../analysis/ai-highlights-live-context/2026-10-08/compatibility/) are retained locally; the audit loaded tracked modules using `git show HEAD:<path>` without editing working files. HEAD: `7510e892cb4a819754e507a4b1a59eaceac6d6b5`.

No golden file, old test expectation, or failure marker was changed. No full acceptance gate, frontend build, live AI provider request or xLights render was run.

## Next session

1. Add a draft preparation/acceptance API sharing the exact runner/export input builder. Capture current context and compile the submitted supported treatments before saving. Revalidate on commit, enforce expected revision, retain previous accepted plan, and report rejected operations without destroying accepted intent.
2. Thread enabled state/context through section preview and its cache identity; preserve/clamp song-level highlight placements in scoped plans.
3. Resolve compositor arbitration for ordinary effects on overlapping groups. Current compiler deliberately rejects those cases and protected media/fades; most busy real layouts need this work before useful emphasis is guaranteed.
4. Verify actual xLights visibility/timing and complete real listening annotations. Add portable sidecar backup before release.
