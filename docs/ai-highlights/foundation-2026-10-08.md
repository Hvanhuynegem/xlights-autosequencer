# AI Highlights foundation — 2026-10-08

Status: **Event/plan contracts and sidecar persistence implemented and tested. No user-facing highlights yet.**

The user requested continuation after the concrete first-slice design was prepared. This session implemented its data and persistence portion. See the [design](../../openspec/changes/ai-highlights-foundation/design.html), [remaining tasks](../../openspec/changes/ai-highlights-foundation/tasks.md), [benchmark protocol](benchmark.md), and [native baseline](baseline-2026-10-08.md).

## Delivered contracts

- [models.py](../../src/highlights/models.py): immutable source events, optional peak/evidence/scores, separate review corrections and locks, bounded event-relative treatment anchors, plan provenance, context fingerprints, and accepted/draft/previous snapshots. All stored timestamps retain the source clock without beat or frame snapping.
- [highlights.py](../../src/review/storage/highlights.py): versioned `highlights.json` next to the existing song session, atomic replacement, optimistic revision checking, same-process writer serialization, and explicit corrupt/unsupported-data errors. Reanalysis session replacement cannot erase this independent sidecar.
- Missing sidecars return `None`. Existing analysis, story, session, generator, and bundle schemas were not modified. New contracts reject unknown fields and versions; schema migration is not yet needed or implemented.
- Detection score, intensity, and salience are optional finite 0–1 values, not calibrated probabilities. Importance overrides are 0–3. Missing peak evidence remains absent. Treatments can reference only measured anchors and offsets within ±2 seconds; resolved positive durations must fit the recording.
- `HighlightPlan.stale_reasons(current_context, current_events)` compares all context fields and the saved reviewed-event snapshot. It reports changed/missing events instead of silently remapping IDs. Applications must call it before replaying saved intent.

These records reserve `sustained_wash` and `isolated_impact` recipe identifiers; neither recipe renders yet. Validation currently checks data shape, bounds, identity, and references within a plan. Layout membership, actual catalog parameters, protected targets, layering, and musical quality need the compiler. Stored locks are intent for future editors/directors to honor; storage does not enforce editorial permissions.

## Verification

**119 tests passed** across new contracts/storage and existing session, bundle, story, and generation-configuration checks. Coverage includes unsnapped edits, missing peaks, invalid scores/timestamps, unknown versions, immutable snapshots, staleness, old songs, session replacement, accepted/draft separation after disk reload, same-revision races, failed atomic replacement, malformed files, and source mismatch.

Exact successful command from the repository root:

```sh
.venv/bin/python - <<'PY'
import logging
from unittest.mock import patch
import pytest
with patch('src.log.get_logger', side_effect=logging.getLogger):
    raise SystemExit(pytest.main([
        'tests/unit/test_highlight_models.py',
        'tests/review_storage/test_highlights.py',
        'tests/review_storage/test_assignments_json.py',
        'tests/review_storage/test_bundle_roundtrip.py',
        'tests/unit/test_story_serialization.py',
        'tests/unit/test_generation_config.py',
        '-q',
    ]))
PY
```

The initial unpatched command hit 14 existing story-test setup errors because `src.log.get_logger` creates log files under the real home directory, outside the writable sandbox. The test invocation above substitutes standard-library loggers before imports. It isolates only logging; highlight, story, storage, and configuration code run normally. Product logging and `HOME` were not changed. Test song state uses existing temporary-directory fixtures.

Separately, the real baseline API analysis/export produced two byte-identical XSQs at the same seed, with optional native analysis components absent. No provider call, frontend check, full repository acceptance gate, or xLights render was run for this foundation. Docker's daemon was not running. No listening labels or detection-quality scores are claimed.

## Remaining work and next session

1. Add the synthetic rhythmic sweep → impact fixture (P1.4), using hand-authored measured timing and an empty/missing-stem case.
2. Wire validated manual-event GET/PUT endpoints (P3.1), deriving source identity and current context server-side. Map revision conflicts and stale plans to useful responses. Preserve accepted snapshots when draft generation or validation fails.
3. Implement the two recipes and connect accepted state through the actual export and preview paths (P4.1–P4.2). Verify catalog support and target membership before accepting plans. Test baseline equality when disabled and inspect serialized placements when enabled.
4. Render the manual highlight in xLights and check its visibility/timing before expanding detectors or adding a provider.
5. Complete real listening annotations and additional recordings for P0.1; the four pending worksheets are not scored negatives. Capture a full-capability baseline and timestamped render evidence for P0.2.

P1 remains partial: optional section/repetition references, chorus/background treatment contracts, automatic reanalysis matching, pipeline caches, and portable bundle integration are outstanding. Full backups currently omit the sidecar. Concurrent storage writes are coordinated within one backend process only; separate writing processes need interprocess locking. Acceptance/history transitions are caller responsibilities; storage preserves the explicitly supplied snapshots and advances the state revision.
