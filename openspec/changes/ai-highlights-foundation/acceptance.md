# Public draft and acceptance workflow — 2026-10-09

Continuation of the approved first manual-to-render slice, explicitly named in
its handoff. Goal: create, validate, accept, reject, disable, re-enable and undo
manual plans through the API using the actual export generation inputs.

## Approach and alternatives

Extract export's input assembly into `src/review/api/v1/generation_inputs.py`.
Both export and highlight actions use the same theme/slider, story, vocal,
extras, source/layout and seed arguments. Add an optional typed draft request
to the runner: build the real baseline with context capture, create a server
owned snapshot, compile with the loaded layout/catalog, serialize to verify,
and return the plan. Existing runner calls still return XSQ bytes. Acceptance,
re-enable and undo run normal enabled replay against freshly loaded inputs;
never accept client fingerprints. Rejecting a draft and disabling need no
working audio/analysis/layout, so users can recover from stale inputs.

Alternative: build a second approximate baseline in the route. Rejected because
it would drift from export settings. An asynchronous job system is deferred:
these initial local API actions are synchronous; cancellation/progress/UI belong
to the later review workflow. No network provider is involved.

Draft takes expected_revision, treatments and optional uint32 variation_seed.
The server selects current saved events, provenance and plan ID. Actions use
expected_revision; accept/reject also require plan_id. Draft preparation and
acceptance preserve the currently accepted plan; accepting rotates it into
previous_accepted_plan. Undo swaps accepted/previous only after replay validation.
Disable preserves all snapshots. Enable validates the saved accepted plan.
All writes compare revisions. Invalid recipes/targets/collisions fail as a whole.
Use export defaults for vocal/timing options; a changed export setting can still
invalidate a plan. Omitted export seed uses enabled accepted intent's seed;
explicit seed/reroll still requests revalidation and can fail stale.

## Files and regression surface

- Add generation_inputs.py and acceptance API tests/evidence.
- Modify export.py: `_run_export` delegates argument assembly, signature unchanged;
  called by start_export and test_api_export/test_highlight_export. start_export
  selects the accepted seed only for enabled replay with no requested seed.
- Modify generator_runner.py: append optional `highlight_draft` to `run` and
  `_run_pipeline`. Existing callers in src/cli/evaluate.py,
  src/evaluation/compare.py, export.py and evaluation tests remain byte-returning.
  New route explicitly requests plan preparation. `_run_pipeline` direct callers
  in tests/evaluation/test_generator_runner.py retain defaults.
- Modify highlights.py: reuse bounded strict JSON parsing; retain GET/PUT event
  semantics. Add POST draft/accept/reject/disable/enable/undo routes on the existing
  blueprint. GET reports validation not checked (it does not run generation).
- Update AI_HIGHLIGHTS_ROADMAP.md, first-slice tasks and evidence; no schema change.

Caller searches: `rg -n 'generator_runner|run_generator|_run_pipeline|_run_export'
src tests -g '*.py'`; `rg -n '_body\(|plan_validation' src tests`.

## Pre-mortem / historical echoes

.wolf/OPENWOLF.md, anatomy.md, cerebrum.md and buglog.json remain absent. No
historical bug-log claims can be verified. Export's documented bug-172 warns
against falling back to the global layout or forwarding unsupported runner args;
shared assembly retains the committed-layout requirement. Existing live-context
evidence warns that JSON validation alone cannot establish valid choreography.

Hidden assumptions: global RNG seeding is already shared by concurrent runner
calls; serialize runner pipelines with a process lock to avoid overlapping export
and preparation corrupting deterministic context. This cannot cover independent
legacy callers outside the runner or external processes. Sidecar CAS prevents
lost intent. Compare session/library and source/layout/story bytes after generation
before saving, and rerun compilation at acceptance. Arbitrary external edits are
not globally transactional. Context catches theme/catalog/assets at generation;
no promise of filesystem transactions is made.

Tests: public manual event → draft → accept → repeated export with real generator,
known analysis and quiet fixture theme; nondefault seed; reject/disable/enable/undo;
stale input/event changes; invalid recipes/targets; corrupt state; strict JSON;
revision changes during generation; unavailable source/layout; default export
regressions. No visual-quality claim without xLights rendering. Preview/cache,
broader overlap arbitration, automatic detection and UI stay pending.

## Small preview prerequisite — 2026-10-09

Pass the already parsed layout from `run_section_preview` to `build_plan` so
future context capture can validate real targets. Re-parsing inside build_plan
would duplicate work and risk a different input snapshot. Modify
src/generator/preview.py and add one regression in
 tests/integration/test_section_preview.py. The function signature and its
preview_routes.py caller remain unchanged; current integration callers retain
baseline behavior. Existing historical limitations above apply. This is within
the authorized preview integration slice; state/cache forwarding remains pending.

## Scoped writer bounds — 2026-10-09

Goal: prevent negative or out-of-window model-effect timestamps in scoped XSQs.
In xsq_writer.write_xsq, intersect shifted placement intervals with the explicit
scoped duration and omit empty intersections before creating Effect elements.
Keep unscoped serialization unchanged and never mutate source placements.
Doing this in each caller instead would duplicate the writer's time-offset logic.
Signature/callers are unchanged (preview.run_section_preview and writer tests;
full exports do not request scoped duration). Add parametrized writer regressions
for both boundaries, outside/inside/spanning effects and source-plan preservation.
This implements timestamp bounds only: partial effect envelopes are not resampled,
and timing-track clipping and preview state/cache forwarding remain separate work.
Existing historical limitations above apply; no visual-fidelity claim is made.

## Scoped highlight handoff — 2026-10-09

Preserve already compiled highlights that intersect the selected preview window
when constructing its SequencePlan. Keep source timestamps/placements unchanged;
the writer performs clipping and offsetting. Count retained highlight placements
in PreviewResult. Modifies preview.run_section_preview (signature/callers unchanged)
and extends its layout-handoff regression with baseline/enhanced cases and real
XSQ serialization. Recompilation after section extraction is rejected because it
would validate a different baseline. Historical limitations above still apply.
This is within the authorized preview slice; route state/cache integration and
partial-envelope fidelity remain pending.

## Frontend API prerequisite — 2026-10-09

Add typed event/plan/state/preview contracts and small API wrappers in
src/review/frontend/src/api/highlights.ts, using the existing api/client request
and ApiError behavior. Add focused Vitest checks for unsnapped event edits,
revision-bearing lifecycle requests, baseline versus default preview choices,
and actionable error propagation. No shared public signatures are changed;
these are new exports with no screen callers until UI integration. Alternative:
inline fetch calls in each future control would duplicate payload and error
handling. Scope is the already authorized review UI prerequisite; historical
.wolf files remain absent. Existing desktop bootstrap routes relative API fetches
to the configured backend. No UI completion or runtime schema validation claim.
