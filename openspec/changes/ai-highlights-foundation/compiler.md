# Initial recipe compiler detail — 2026-10-08

Continues the approved first-slice design. This increment implements and verifies the compiler → normal placements → XSQ portion. Live context construction, accepted-plan API, config/runner/export forwarding, and preview integration remain separate unfinished tasks; do not enable saved snapshots until those exist.

## Recipes

Both initial recipes use the real catalog `On` / `eff_ON` effect and its authored start/end brightness, transparency, cycles and shimmer parameters. A wash comprises contiguous rise and decay placements split at a measured/manual interior peak, using a single inherited color. An impact comprises one start-bright/end-dark pulse. No guessed peak, fabricated xLights effect, strobe, or brightness value curve is needed. The XSQ writer currently caps fade durations and only emits E-prefixed value curves, so those mechanisms cannot reliably express a long envelope and are deliberately avoided.

- `sustained_wash`: sweep/wash/unknown_texture, 250–30000 ms after alignment, interior peak with at least one frame on either side.
- `isolated_impact`: impact, 50–1000 ms after alignment; no measured peak required. A point event needs an explicit positive end offset.
- Intensity is positive and at most 1; brightness endpoints are capped at 100. First recipes are additive, nonspatial accents. A spatial sweep, background ducking, and three additional roadmap recipes remain future work.

## Compiler boundary

Add `src/generator/highlights.py`: `compile_highlights(baseline, plan, *, context, events, layout, effect_library)` returns a new placement dictionary. It validates stale snapshot inputs, recipe version, accepted event reviews, baseline duration, actual targets/catalog, timing, palette, and collisions before returning. It never mutates baseline or saved intent. `context` must eventually be supplied by the server's live context builder; passing the plan's own context is not live validation.

Add default-empty `SequencePlan.highlight_effects` **at the end** of the dataclass to preserve positional callers. Extend `write_xsq` gathering only; no public function signature changes. Existing empty collections must serialize byte-identically. Inspection/tests also found that `EffectPlacement.__post_init__` and the writer header hardcode 25 ms. Append an optional `EffectPlacement.frame_interval_ms` defaulting to 25, retain its old default rounding behavior, pass the configured interval from the compiler, and emit the plan interval in both XSQ header fields. Existing baseline effects must already be on that frame grid; reject incompatible timing. Do not introduce inactive GenerationConfig flags before their wiring exists.

Use integer nearest-frame rounding (half frames round up), bounded to the last complete frame inside audio. Preserve source timestamps in event records; reject collapsed intervals or peaks. Reject a treatment crossing a reviewed section boundary for now; select one section palette, honoring anchor/pinned theme, color shift, and brightness/hit-strength. Prefer an existing active same-target baseline palette to preserve effective colors. Exactly one inherited color per treatment prevents repeated palette cycles within the envelope.

Resolve raw layout groups recursively, including nested groups and conservative whole-model membership for submodels. Reject unknown/cyclic/empty groups and ambiguous names. DMX and dedicated singing models are ineligible. Validate catalog suitability for every member. Preserve explicit target choices; never silently retarget onto an unrelated prop.

Layer order is only meaningful within the same target's EffectLayers. Place highlights on a new frontmost additive layer (lower index), leaving baseline layers untouched. Reject temporally overlapping targets sharing physical members, protected media/vocals/crash/moving-head content, Min/Max masking or start/end fade regions, and ordinary cross-group overlap whose compositor precedence cannot be guaranteed. This conservative rule can make some busy layouts unavailable until P4.3; do not claim general compositor safety from layer numbers alone.

## Validation and callers

Existing constructor/writer callers are recorded in callers.md; re-search before edits. New callers are compiler tests and an explicit synthetic XSQ artifact generation script. Runtime build_plan/runner/export/preview callers are untouched in this increment. Tests cover real catalog contracts, frame intervals/rounding, near-end behavior, missing peak, unavailable targets/catalog, nested shared membership, protected content, no mutation on failure, replay determinism, serialized envelope/layer order, and empty-plan baseline equality.

Historical echoes: reversed layer direction (bug-248/569), lost song-level collections in previews, writer fade clamping, and mistaken cross-group layering. `.wolf` remains absent. Verdict: compiler and XML behavior can be verified independently, but live acceptance and visual success remain pending. No frontend or provider additions in this step.
