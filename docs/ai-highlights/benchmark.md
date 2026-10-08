# AI Highlights benchmark protocol v1

Date: **2026-10-08**. Scope: roadmap P0.1, P0.2, and P0.4.

**Protocol status:** initial evaluation rules fixed before new highlight tuning. Thresholds below are provisional engineering targets, not measured performance or a completed listening validation. Revisions must be dated and justified before another held-out evaluation; never rewrite criteria silently to fit a result.

## Available evidence

- [Inventory and split](../../tests/fixtures/highlights/manifest.json): four downloaded, hash-verified recordings; two further real-recording slots reserved.
- [Listening worksheets](../../tests/fixtures/highlights/annotations): timestamps and labels are intentionally empty until someone listens and annotates them.
- [Baseline report](baseline-2026-10-08.md): a real import → analysis → theme acceptance → export run on Funshine, including two byte-identical XSQ exports at the same seed. No visual or listening validation is claimed.

The four existing recordings alone do not establish coverage for noise sweeps, isolated crashes, dense percussion, and vocal choruses. The reserved recordings and listening pass must fill those gaps before P0.1 is marked complete. Source metadata and filenames are not auditory evidence.

## Corpus and split rules

| Recording | Split | Intended use, pending listening |
|---|---|---|
| Funshine | Development | Rhythmic full mix; ordinary-beat negatives and possible transitions. |
| Maple Leaf Rag | Development | Repeated musical material without assuming it is a vocal chorus. |
| Nostalgic Piano | Holdout | Melodic phrases, quieter changes, restraint. |
| Space Ambience | Holdout | Sustained textures and sparse-event behavior. |
| User motivating example, recording not selected yet | Development | The unusual “shhh” and surrounding beat pattern. |
| Independent rhythmic recording, not selected yet | Holdout | Fills/crashes/dense percussion and repeated chorus behavior, as listening confirms. |

The minimum target is six real recordings. Add another if these do not cover all required musical cases. Split at recording/song level: excerpts, stems, re-encodings, and synthetic variants of one source must not appear on both sides. Different recordings of the same composition should stay in one split unless a separately reported cross-recording test deliberately needs them.

For the four fixed recordings, the first 120 seconds and the final 30 seconds are preselected as continuous review windows. This provides ordinary passages as well as potential highlights and includes the ending without selecting windows after seeing detector results. Windows are half-open `[start_ms, end_ms)`; merge overlap for shorter added tracks. Listen with at least five seconds of context where available, but score only the declared windows. Later additions require a dated manifest revision before inspecting their predictions.

Synthetic beat/sweep/impact/gap fixtures will supplement timing and compiler tests in P1.4. Their designed event times do not count as human-reviewed musical ground truth or toward the six-recording target.

## Annotation format

Draft files use `annotation_schema_version: 1`. This is a benchmark-data format, not the proposed application event schema. The currently committed drafts are parseable worksheets; a runtime validator/evaluator has not been implemented yet.

Top-level fields:

| Field | Meaning |
|---|---|
| `recording_id`, `source_sha256` | Link to exactly one manifest recording and exact audio bytes. |
| `duration_ms`, `clock` | Production-loader duration; milliseconds from recording start, before output-frame quantization. |
| `review_status` | `pending`, `partial`, or `complete`. Empty pending files must never be scored. |
| `reviewer`, `reviewed_on` | Actual listener and date; null until reviewed. Do not enter an AI as a listener if it did not process the audio. |
| `scored_windows` | Stable window IDs, start/end, and per-window `review_status`. Only complete windows enter scoring. |
| `events` | Individual present or uncertain musical events, described below. |
| `routine_patterns` | Intervals describing ordinary repeated beats, hi-hats, or other ongoing textures. |
| `negative_intervals` | Explicitly reviewed intervals in which no exceptional highlight is wanted. |
| `ignore_intervals` | Ambiguous/corrupt intervals excluded before evaluation, with a reason. |
| `sections` | Optional reviewed roles and repetition groups; never populate these from unreviewed model labels as truth. |
| `notes` | Listening limitations, source observations, and adjudication history. |

Each event must include:

- A unique `event_id` stable within that annotation revision.
- `start_ms`, `peak_ms`, `end_ms` as integer timestamps, with `0 <= start <= peak <= end <= duration`; a point event may use equal times. Actual placement minimum duration is a separate generator concern.
- `timing_shape`: `attack`, `sustained`, `gap`, or `reentry`. Gap boundaries are measurable even though there is no positive acoustic peak; use `peak_ms: start_ms` and document that convention.
- `label`: a descriptive type such as `noise_sweep`, `cymbal_wash`, `fill`, `instrument_entry`, or `unknown_texture`. Unknown identity is acceptable when the event itself is clear.
- `event_present`: `yes` or `uncertain`, plus `presence_certainty`: `high`, `medium`, or `low`.
- `highlight_importance`: `0` ordinary/undesired, `1` optional accent, `2` important, or `3` defining moment. This is a listener preference, not acoustic loudness.
- `timing_certainty`: `high`, `medium`, or `low`; optional boundary uncertainty ranges when needed.
- `notes` explaining the musical evidence, desired emphasis, and uncertainty; optional `related_event_ids` for a sweep followed by a separate impact.

Example for explaining the format only; it is not a claim about any recording:

```json
{
  "event_id": "example-sweep-01",
  "start_ms": 8250,
  "peak_ms": 9700,
  "end_ms": 10100,
  "timing_shape": "sustained",
  "label": "unknown_texture",
  "event_present": "yes",
  "presence_certainty": "high",
  "highlight_importance": 2,
  "timing_certainty": "medium",
  "related_event_ids": [],
  "notes": "Illustration only: an off-beat wash rises above a repeating rhythm."
}
```

Every routine/negative/ignore interval needs start/end and a reason. A negative interval must not overlap an important event; resolve disagreements before scoring. Unreviewed regions are not negative examples. An annotation revision may be corrected after discovering a mistake, but retain the prior revision and report the reason separately from detector performance.

## Event matching and metrics

1. Verify content hashes, duration/clock, schema versions, completed review windows, and nonoverlapping interval definitions. Stop if they do not match.
2. Evaluate candidate detection and final lighting selection separately. Include only targets with `event_present: yes`, at least medium presence certainty, and sufficient timing certainty. Exclude uncertain target regions using recorded ignore intervals, not ad hoc exclusions after seeing predictions.
3. A prediction belongs to the window containing its anchor: start for attacks/reentries/gaps and peak for sustained events. Use full intervals for matching even if they extend beyond the scoring window. Deduplicate window membership; do not count the same event twice.
4. Construct admissible prediction/target pairs using compatible timing shape and these tolerances: attack/reentry onset error <= 200 ms; sustained interval intersection-over-union >= 0.5 with peak error <= 500 ms; gap intersection-over-union >= 0.5 with start/end errors <= 300 ms. These are initial v1 matching tolerances, not required lighting offsets. Report boundary errors even when a match passes.
5. Choose a maximum-cardinality one-to-one matching, then minimize normalized timing error, then break ties by stable IDs. A second prediction for one already matched target is a duplicate false positive. A predicted sweep and its subsequent impact match two separately annotated events, not one broad interval.
6. Use type-agnostic acoustic descriptions within compatible timing shapes for event detection. Report semantic-label accuracy separately so `unknown_texture` can correctly find an exceptional wash without falsely claiming it is a cymbal.

Report these quantities with raw numerators and denominators:

- **Candidate recall:** matched important events (`highlight_importance >= 2`) / eligible important events. Also report recall over all individually annotated sound events and candidates per minute.
- **Selected-highlight precision:** selected predictions matched to important events / all selected predictions inside reviewed scoring regions. Matches to importance 1 are reported as optional, but do not inflate this strict precision metric.
- **Selected-highlight recall:** important events matched by selected predictions / eligible important events.
- **False highlights per minute:** unmatched or non-important selected predictions / reviewed non-ignored minutes. Report this separately on negative intervals.
- **Timing:** signed error (to reveal lateness), median absolute error, 90th percentile absolute error, and sustained-event start/peak/end errors.
- **Duplicates, abstentions, and coverage:** duplicate rate, unselected important events, no-event songs, missing-stem capability profile, and number of scorable recordings/windows/events.

Zero denominators produce `not applicable`, not 100%. A song with no important events still measures false highlights. Report pooled counts and per-recording metrics so a dense track cannot hide regressions elsewhere. A wrong semantic label is not a second timing false positive when the acoustic event was correctly matched.

## Initial acceptance targets

Before claiming core detector quality, require at least three held-out recordings, at least 20 eligible important held-out events across the key sound types, and at least three minutes of reviewed negative material. This means an additional held-out recording may be needed beyond the six-track starting inventory. Until then, label results preliminary and show sample counts.

- Important-event candidate recall >= 85%.
- Selected-highlight precision >= 80% and important-event recall >= 75%.
- Sharp-event median absolute onset error <= 100 ms; 90th percentile <= 200 ms.
- False highlights <= 1 per minute on reviewed negative intervals, with per-song results shown.
- All compiled placements stay in bounds, reference valid targets, and satisfy output-frame rules; empty plans remain valid.
- Disabled mode and replayed accepted plans preserve their documented deterministic behavior.

These targets are intentionally separate from provisional density defaults. A system cannot pass by emitting no highlights, nor by treating every onset as exceptional. A missed mandatory sound type or systematically late visual impact requires investigation even if the pooled average passes.

## Listening and visual assessment

Compare baseline, local recipes, and AI-directed treatments with the same input audio, layout, theme settings, and seed. Use at least five seconds before and after each target. Randomize A/B order where practical.

Rate musical fit, visibility, timing, restraint, return to the underlying rhythm, and chorus coherence on a 1–5 scale with timestamped comments. A treatment passes its individual visual check when the listener considers it musically appropriate, the intended emphasis is visible in the actual xLights render, and it introduces no distracting extra accent or persistent dimming. Preserve dislikes and disagreements; do not average away an unacceptable effect.

Browser approximations and XML inspection are useful checks, but blend/layer visibility requires a real render. The [render tooling](../../tools/render/README.md) describes the repository's headless path. No render has been performed for the initial baseline.

## What remains before P0.1/P0.2 are complete

- Identify and annotate the motivating recording and an independent rhythmic recording; add a third held-out recording before final quality claims.
- Listen to all continuous windows and sign off their labels, including routine and negative intervals.
- Capture the full-capability deployment baseline when Docker is available. The native baseline omits optional analyzers/stems.
- Render representative baseline excerpts and trace at least one user-confirmed target moment through analysis, selection, serialization, and visible output.
