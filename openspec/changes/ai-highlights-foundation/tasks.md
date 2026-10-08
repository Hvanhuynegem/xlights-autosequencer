# First-slice implementation tasks

Status: **Contracts, sidecar storage, synthetic fixtures, and manual-event API, compiler/XSQ support, and live accepted-plan export implemented; full manual-to-render slice incomplete.** These refine the roadmap; do not mark a whole roadmap phase complete merely because this slice passes.

- [x] Prepare [the concrete design](design.html), including sidecar storage and explicitly deferred bundle support; user subsequently requested “continue”.
- [x] Add strict typed event/review/plan records and round-trip validation in `src/highlights/models.py`; cover absent timing evidence, invalid types/ranges, and unsupported versions.
- [x] Add a deterministic synthetic sweep → impact fixture with ordinary rhythmic context and known timing, plus an empty/no-stem case. Keep actual music benchmark labels separate.
- [x] Implement versioned sidecar storage under the song state directory, atomic writes, optimistic revision checks, and preservation of accepted/draft states.
- [x] Add/register GET/PUT manual-event endpoints with event validation, server-measured source identity/duration, revision conflicts, and preservation of plan snapshots.
- [ ] Extend the API to plan validation/acceptance once real compiler/context validation exists; report full generation-context staleness.
- [x] Implement two catalog-backed recipes with validation of explicit targets, palette inheritance, frame alignment, and rejection of unsupported/protected targets. Cross-group ambiguity remains a rejection until compositor arbitration exists.
- [x] Add default-empty `SequencePlan.highlight_effects` and writer gathering. Add defaulted placement frame intervals and honor the sequence clock in XSQ headers; verify unchanged default output.
- [x] Add default-disabled `GenerationConfig.highlight_state`, explicit context capture and reviewed-section inputs; compute live fingerprints from actual generation inputs.
- [x] Wire enabled accepted state through export → generator runner → config → plan compiler → XSQ writer with fresh context. Reject stale/changed inputs and preserve generation-time layout in the package. Public acceptance remains pending.
- [ ] Thread the accepted revision into preview input/cache identity; preserve relevant song-level highlight placements when building a section preview, without changing unrelated preview behavior.
- [ ] Test real endpoint plumbing with isolated state, old/no-highlight songs, concurrent revision conflicts, stale inputs, empty plans, bounds, layers, and unchanged-baseline behavior.
- [ ] Export twice at the same inputs/seed and compare normalized placements/XML; record accepted plan, source hash, layout, catalog, and recipe versions.
- [ ] Render the manual sweep and impact in xLights and document visible timing, target coverage, and recovery. Keep this task pending if rendering cannot be performed.
- [ ] Update the roadmap and handoff with completion evidence and follow-ups: more recipes, controlled background dimming, portable backup support, automatic reanalysis matching, and the timeline editor.

2026-10-08 evidence: see [foundation validation and next steps](../../../docs/ai-highlights/foundation-2026-10-08.md). Roadmap phases remain incomplete where their broader acceptance criteria are unmet.

2026-10-08 continuation: [manual API contract and validation](../../../docs/ai-highlights/manual-api-2026-10-08.md); 180 tests passed after an existing asynchronous section-test timeout was rerun. Plan acceptance remains pending.

2026-10-08 compiler continuation: [compiler/XSQ evidence](../../../docs/ai-highlights/compiler-2026-10-08.md), saved synthetic artifacts, and identical replay. Broad checks: 1070 passed; four legacy golden failures reproduced with unchanged HEAD; current baseline outputs match HEAD across all four configurations. No live export/preview integration or render yet.

2026-10-08 live replay continuation: [context/export evidence](../../../docs/ai-highlights/live-context-2026-10-08.md), 1137 selected tests passed; all four actual default-generation configurations still match HEAD. Known old-golden failures were not rerun in that selected command. Public plan acceptance, preview and render remain pending.
