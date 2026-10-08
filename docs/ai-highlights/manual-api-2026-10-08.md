# Manual highlight API — 2026-10-08

The backend can now save and review precisely timed musical events for imported songs, including songs that have not been analyzed. The timeline UI, lighting compiler, plan acceptance and enhanced export remain pending. No AI key or stems are needed for these endpoints.

This increment follows the [approved first-slice design](../../openspec/changes/ai-highlights-foundation/design.html) and its [manual API detail](../../openspec/changes/ai-highlights-foundation/manual-api.md). The [tracker](../../AI_HIGHLIGHTS_ROADMAP.md) records outstanding acceptance conditions.

## GET current state

`GET /api/v1/songs/<song_id>/highlights` returns:

- `source`: actual audio SHA-256 and decoded `duration_ms`, derived server-side using the production loader.
- `state`: versioned reviews and saved plan snapshots; absent sidecar returns revision 0, empty events, disabled highlights. GET does not create a sidecar.
- `issues`: changed source/duration or saved-plan event snapshots that differ from current reviews.
- `plan_validation`: `no_plan`, or `unavailable` when snapshots exist. The latter means full layout/catalog/generation context has not been validated; it must never be treated as approval to render.

The source resolver follows playback's first existing library source path, including a relocated copy. Names and library container durations are not audio identity. Import normally retains a canonical source; export currently selects its first source path, so compiler integration must reconcile resolution when the canonical path is missing. Different audio bytes require explicit future reconciliation; this endpoint does not silently reset saved intent.

## PUT manual reviews

`PUT /api/v1/songs/<song_id>/highlights` requires **exactly** these fields. Copy `expected_revision` from GET's `state.revision`, and source fields from GET's `source`:

```json
{
  "expected_revision": 0,
  "source_sha256": "<full SHA-256 from GET>",
  "duration_ms": 16000,
  "events": [
    {
      "event": {
        "event_id": "manual-sweep-1",
        "source_sha256": "<same full SHA-256>",
        "source_revision": "manual-1",
        "kind": "sweep",
        "timing": {"start_ms": 8273, "peak_ms": 9719, "end_ms": 10113},
        "provenance": "manual"
      },
      "status": "accepted",
      "importance": 2,
      "locked": true,
      "note": "Highlight this unusual sustained sound"
    }
  ]
}
```

This is a full replacement of the reviewed-event list. Omit an event to delete it; change `status` to `dismissed` or `accepted` to reject/restore it. Add a new uniquely identified manual event to create one. An accepted **event** expresses musical importance; it does not accept a lighting plan or enable generation.

Existing `event` objects are immutable evidence. Correct timing through a sibling `timing_override` object with `start_ms`, `end_ms`, and optional `peak_ms`. Importance, note and locked status are editable by this explicit manual request. New detector/audio-model events cannot be invented through this manual route. Subsequent automatic editors must honor locks; the current API permits the user to edit their own locked review.

On success the response has the same shape as GET and advances `state.revision`. Accepted/draft/previous plans and enabled state are preserved verbatim. PUT rejects submitted plan or enable fields; acceptance awaits semantic validation in the recipe compiler. Editing reviews can make preserved snapshots stale, and the response reports event mismatches.

## Errors and limits

| Status | Code | Meaning |
|---|---|---|
| 400 | `invalid_highlights` | Wrong shape/types, invalid timing, nonmanual new event, changed original evidence, duplicate IDs, or attempted plan injection |
| 404 | `song_not_found` | Song is absent from the library |
| 409 | `revision_conflict` | Another edit won; reload before applying the user's changes |
| 409 | `source_changed` / `duration_changed` | Request or stored state does not match current audio; review/reconcile first |
| 409 | `source_unavailable` / `source_unreadable` | Locate or repair the source audio |
| 409 | `highlight_state_unreadable` | Corrupt or unsupported sidecar; preserve it and restore a valid copy |
| 413 | `request_too_large` | Request exceeds 2 MiB |

At most 2000 events are accepted. Invalid requests leave saved state intact. Revision checking and atomic replacement protect simultaneous edits in one backend process; multiple writing processes remain unsupported. Audio is hashed/decoded on each request and checked again before saving. This prioritizes correctness for manual edits; a later cache must retain content and decoder identity. Filesystem audio replacement is not transactional with sidecar writes, so the eventual compiler must revalidate before replay.

## Fixtures and validation

The [synthetic fixture builder](../../tests/fixtures/highlights/synthetic.py) generates three full-mix recordings and hand-authored draft plans: sweep/impact, near-end impact, and ordinary rhythm with no exceptional events. All lack stems. Targets exist in the reference layout; draft generation-context placeholders must be replaced with actual compiler inputs. No detector accuracy, audible quality, or visible lighting is claimed.

Local generated examples are under ignored `analysis/ai-highlights-synthetic/2026-10-08/`. Source hashes from this run:

| Case | WAV SHA-256 |
|---|---|
| `sweep_impact` | `905d69dd1434527e05940e115766ed26f346041df61f6241c95eb61c895ef9e5` |
| `near_end` | `564fe9e360c40843a58b74feeb29ae0eaf958835b7da4f0fa2d71bce86ca93e7` |
| `rhythm_only` | `ad418aa0488789a0d12d5aad6879749c3b05a6def772351e75ae038c49489c54` |

Tests import real generated WAVs through the normal multipart endpoint and call the new routes without mocking source identity, decoding, storage or event logic. They cover exact off-beat corrections, reload, session replacement, deletion/restoration, empty/boundary events, revision races, invalid plans, changed audio during commit, renamed files, malformed payloads and missing/corrupt sources or state.

The broader regression command is:

```sh
NUMBA_CACHE_DIR=/private/tmp/xlight-numba .venv/bin/python - <<'PY'
import logging
from unittest.mock import patch
import pytest
with patch('src.log.get_logger', side_effect=logging.getLogger):
    raise SystemExit(pytest.main([
        'tests/unit/test_highlight_models.py', 'tests/unit/test_highlight_fixture.py',
        'tests/review_storage/test_highlights.py', 'tests/review/test_api_highlights.py',
        'tests/review/test_api_import.py', 'tests/review/test_api_sections.py',
        'tests/review_storage/test_assignments_json.py', 'tests/review_storage/test_bundle_roundtrip.py',
        'tests/unit/test_story_serialization.py', 'tests/unit/test_generation_config.py', '-q',
    ]))
PY
```

As in the foundation session, the command substitutes standard-library loggers to keep existing story setup from writing outside the sandbox. It does not patch application logic. Existing section tests use their own stub analysis fixture; the new highlight routes do not invoke analysis at all. The initial combined run had 179 passes and one existing section-test failure while its two-second poll expired; all six section tests passed immediately when rerun in isolation. **Final combined result: 180 passed, 5 warnings in 3.81 seconds.** Warnings are dependency deprecations and decoder fallback on deliberately invalid audio. No existing test was changed.

No frontend, provider, generator placement, full acceptance gate, or xLights render was exercised in this increment. Next: catalog-backed wash/impact compilation, real context fingerprints, plan validation/acceptance, and accepted-state forwarding through export and preview.
