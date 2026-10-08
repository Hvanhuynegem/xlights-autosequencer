# Manual-event API implementation detail

Continuation of the approved foundation design, 2026-10-08. This increment completes the synthetic fixture and manual-event transport portion. Plan acceptance stays deferred until the compiler can verify layout/catalog/context; the API must not accept unchecked plans merely to complete an endpoint checklist.

## Contract

- GET `/api/v1/songs/<id>/highlights` returns `state`, current `source` (`source_sha256`, decoded `duration_ms`), `issues`, and `plan_validation`. Missing sidecar is an empty disabled revision-0 state; unknown song is 404. Draft songs can have manual events before analysis.
- PUT to the same route requires exactly `expected_revision`, `source_sha256`, `duration_ms`, and `events` (full replacement of reviewed events). These source fields echo GET and must match the server's current audio. New events must be manual. Existing events retain their original evidence/timing; corrections use the separate review override. Removing, dismissing, restoring, or explicitly unlocking a review is a user edit.
- Preserve all existing accepted/draft/previous plans and enabled state during event edits. No acceptance or enable controls are exposed by this increment. Return `plan_validation.status=unavailable` if a saved plan exists: full generation context cannot yet be verified. Event-only changes can still report snapshot-event mismatches.
- Return structured 400 contract errors, 404 unknown songs, 409 revision/source/duration conflicts and unavailable/corrupt source/state errors. No failed request overwrites state. Bound request bodies and event counts.
- Resolve the first existing library source path (as playback does), hash its full bytes, decode using the production loader clock, and verify it did not change during decode. Recheck the selected library path and bytes immediately before save. The sidecar's atomic compare/write still arbitrates simultaneous event writers. External filesystem changes are not transactional with JSON; replay must revalidate again in the future compiler. Do not claim cross-process coordination.

## Files and regression surface

Add `src/review/api/v1/highlights.py`, `tests/review/test_api_highlights.py`, synthetic fixture builder/data under `tests/fixtures/highlights/`, and `tests/unit/test_highlight_fixture.py`. Register the new route module in `src/review/api/v1/__init__.py`. Existing app registration (`src/review/server.py:create_app`) and its callers stay unchanged. Reuse storage and model signatures unchanged. Existing sessions, analysis, export, generator and frontend are not modified in this increment.

Alternative: accept the complete sidecar in PUT. Rejected because clients could replace accepted snapshots or assert unsupported catalog/context validity. Alternative: trust library duration/song ID. Rejected because imported container durations can differ from the decoder clock, and song IDs are shortened hashes (video IDs can also identify video instead of extracted audio).

## Verification and risks

Import generated full-mix WAV through the real import endpoint, GET server-derived identity, PUT off-beat sweep and separate impact, reload, correct/dismiss/restore/delete, and replace the ordinary session. Check concurrent revision conflicts, wrong source, changed audio, moved source, invalid timing, corrupt sidecar, absent source, malformed payload and attempted plan injection. Verify accepted plans survive API edits and are explicitly unvalidated. Existing import and storage tests cover the registration regression surface.

Synthetic audio: regular low-amplitude kick/snare context, shaped noise sweep, separate stronger impact, quiet tail; additional near-end and empty/rhythm-only cases; no stems. Hand-authored labels establish timing contracts, not detector accuracy. Generate into temporary test directories; never label these as real listening benchmark results.

Historical risks remain those recorded in design.html: session replacement loses embedded state; source identity differs across application layers; successful serialization is not visible rendering. `.wolf` history remains absent. The pre-mortem outcome is to expose event editing only until semantic compiler validation exists, and retain partial task status for plan acceptance and the final render.
