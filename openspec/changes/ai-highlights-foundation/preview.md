# Accepted-state v1 section preview — 2026-10-09

Goal: preview accepted highlights using exactly the v1 export inputs, with fresh
validation before cache reuse and artifact delivery. This continues the authorized
manual-to-render slice. The legacy `/api/song/<hash>/preview` uses a different
library identity and brief configuration; feeding v1 snapshots to that route
would produce mismatched contexts. Add a v1 endpoint instead, leaving its legacy
contract intact. No frontend is currently wired to either new highlights or v1
preview; UI integration remains a subsequent task.

## Design

- POST `/api/v1/songs/<id>/preview` accepts optional section_index (null auto-picks),
  highlights (omitted honors enabled state; false explicitly baseline; true
  requires accepted enabled intent), variation_seed, vocal_diarization and
  include_extra_timing. Strict bounded JSON. Use export's generation_inputs.
- Extend runner.run/_run_pipeline with optional SectionPreviewRequest. Existing
  byte-returning and draft callers retain defaults. Preview mode captures a live
  baseline context, validates enabled intent, then serializes the selected window.
  Seeding remains inside the existing runner lock.
- Extract write_section_preview from the legacy runner's assembled-plan tail.
  Include intersecting adjacent sections when minimum duration extends a window,
  and all song-level collections. Deep-copy the scoped plan because the writer
  rewrites video/shader parameters. Do not apply transitions again to an already
  completed baseline. Recalculate clipped highlight On envelope endpoints on the
  copied placements. Other clipped effect phases remain approximate and reported.
- Clip timing tracks as well as model effects in explicitly scoped output.
- Return a typed GeneratedSectionPreview containing context, selected index,
  result metadata, XSQ bytes and copied sibling media/layout bytes. Deliver an
  XSQZ package so video/shader assets created by serialization survive temp cleanup.
- Cache bounded artifacts by server-generated ID, request input identity (including
  full current session, enabled choice and sidecar revision), and live PlanContext.
  Every POST and GET download builds/validates the current baseline first. Reuse
  serialization only when fresh context and selected index match the candidate.
  Baseline assembly/analysis cache cost remains; avoiding it safely needs a future
  complete dependency manifest. Never use saved context as current context.
- POST is synchronous like current acceptance. Return metadata and download URL.
  GET download verifies original request snapshot and regenerates context; stale
  artifacts fail 409 instead of silently serving/regenerating a different preview.
  Cache is bounded by count and byte size; eviction returns 404 on old URLs.
  Check session/library/state and source/layout/story identity before publication.
  No persistence changes to accepted intent. Explicit baseline bypasses corrupt
  sidecars. No provider/network calls, job progress or cancellation in this slice.

## Files / regression surface

Add src/review/api/v1/preview.py and preview tests/evidence. Modify api/v1/__init__.py
only to register routes. Extend generator_runner.run/_run_pipeline with appended
optional request argument (callers: export.py, highlights.py, cli/evaluate.py,
evaluation/compare.py and tests/evaluation; unchanged unless opting in).
Modify generator/preview.py run_section_preview to delegate scoped serialization;
legacy preview_routes.py and integration tests retain its signature. New helper
also serves the runner. Append defaulted scoped_duration_ms to writer's private
_emit_timing_layer; its three calls are within write_xsq, existing writer callers
retain unscoped behavior. Update roadmap/tasks/evidence.

Caller search: rg for run_section_preview, _run_pipeline, _emit_timing_layer and
preview throughout src/tests. Read current handoff, writer media-copy logic and
preview window policy (10–20 s). `.wolf/` still absent; historical bugs cannot be
independently checked. Prior layer-order evidence remains in models.py comments.

## Pre-mortem and validation

Risks: wrong legacy identity, duplicate generation settings, stale cache despite
unchanged revision, lost song-level extras, mutated source plan, shortened windows
restarting wash brightness, missing packaged media, secondary sections dropped,
and global RNG collisions. Shared production runner/context, cloned scoped plans,
full snapshot checks, package bytes and focused regressions address these.
Filesystem changes and independent legacy RNG users are not globally transactional.
Baseline and enhanced comparisons must use the same explicit seed/options; baseline
without a seed keeps export's deterministic default. Tests cover actual public
acceptance -> preview -> package, baseline comparison, cache reuse only after
validation, changed events/themes/layout/audio/sections/seed/assets, races and
sidecar corruption; scoped extras/adjacent sections/timing/envelope invariants and
no source mutation. Run selected generator/review/preview regression suite. Real
xLights rendering remains required before visual fidelity claims.
