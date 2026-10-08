# Proposal: AI Highlights foundation and first manual sequence

Status: **Foundation, manual-event API, two recipes, and compiler/XSQ support implemented; live context and enabled-state export implemented; public acceptance, preview and rendering pending.**  
Prepared: **2026-10-08**, against source commit `7510e89`.

## Goal

Let a user save a precisely timed exceptional sound and turn it into a valid, replayable lighting treatment, establishing the same contracts that later automatic detectors and an AI director will use.

Read the [reviewable design](design.html), [caller inventory](callers.md), [implementation tasks](tasks.md), and [benchmark protocol](../../../docs/ai-highlights/benchmark.md).

## First slice

The planned first slice introduces typed event/plan records, separate persistent highlight state, a minimal manual API, and two initial recipes: a sustained wash/sweep and an isolated impact. The active export path loads the accepted plan, validates its input identity, compiles normal effect placements, and serializes them through the existing writer.

It is deliberately possible to use this slice without automatic highlight detection, a provider SDK, or credentials. This is the first usable vertical slice in the [roadmap](../../../AI_HIGHLIGHTS_ROADMAP.md), not a claim to complete its full P1–P4 phases. API control precedes the fuller timeline editor. Background ducking, additional recipes, broad conflict arbitration, portable bundle extensions, and automatic reanalysis remapping remain explicit follow-up tasks.

## Design choices

- Store manual/reviewed state in a versioned `highlights.json` sidecar under the existing per-song state directory. Source inspection found that `analysis._analyze_in_background` and `commit_analyze` write replacement session payloads. A separate sidecar avoids losing highlights without forcing a session-storage refactor now.
- Identify audio by its actual content hash. The UI's shortened SHA-256 song ID and the hierarchy's MD5 source hash are different identifiers; never compare them directly.
- Use immutable accepted plan snapshots containing all required event timing and context fingerprints. Reanalysis or theme/layout changes make a plan stale rather than silently reinterpreting its IDs.
- Add optional fields with defaults to generator models and thread them through the real API → runner → config → plan → writer path. Baseline callers retain disabled behavior.
- Compile onto existing eligible targets using real library definitions. Unsupported recipes, stale plans, invalid timing, protected-content conflicts, or invalid references produce an explicit validation result.
- Keep source timing unsnapped. Frame alignment occurs only when compiling output. Preserve the configured output interval and record actual placement timing.
- Apply highlight compilation to an assembled baseline plan after its ordinary curves/transitions/fades. Initial recipes avoid protected content and start/end fade regions; broader dimming and overlap composition need P4.3's separate implementation.

## Alternatives considered

1. **Deterministic detector/recipe improvements alone:** retained as a valid operating mode; insufficient for the later whole-song creative-direction goal.
2. **A text model reviewing raw XSQ:** rejected as the first step because it cannot recover unrepresented audio events and would have to reason about low-level layer details.
3. **Direct audio-model sequencing:** deferred to P10 because sound recognition, timing accuracy, cost, and repeatability require separate evidence.
4. **Embedding all state in `session.json`:** simpler backup integration, but current reanalysis replaces sessions and multiple writers would need immediate changes. A sidecar narrows the first regression surface; bundle support must then be added explicitly before release.
5. **Editing current detector thresholds first:** deferred until benchmark labels exist. The native baseline's missing detectors cannot be fixed by tuning thresholds.

## Historical and environmental evidence

- The existing detector comments/proposals describe stale-schema misses (bug-265), candidate suppression and recording-specific overfitting (bug-266), reversed layer assumptions (bug-248/569), and fill-placement target collisions (bug-514 context). See the design's evidence table.
- `.wolf/OPENWOLF.md`, `.wolf/anatomy.md`, `.wolf/cerebrum.md`, and `.wolf/buglog.json` remain absent; their history could not be checked. No claim of “no matching bugs” is made.
- The native baseline completed actual analysis/export with missing optional capabilities and produced two identical XSQ files. It does not validate detection accuracy or visual quality.

## Acceptance for this slice

- One manual off-beat sustained event and one separate impact can be saved, loaded, and compiled from a real request.
- An unchanged accepted snapshot replays deterministically without a provider call.
- Disabled/no-plan mode matches the existing generator's behavior.
- Invalid or stale plans cannot partially modify the baseline or overwrite an accepted plan.
- Same-revision concurrent updates in the supported single-backend deployment have one winner; unrelated session writes do not erase sidecar state.
- XML inspection proves the compiled timing and target references reach the package, and an actual xLights render proves the intended wash/impact is visible.

The last item remains a required completion criterion even if rendering is unavailable in a coding session. Record implementation and render validation separately.

## Authorization and implementation status

The concrete design and baseline were prepared before code changes. The user then requested “continue”; the contracts and sidecar storage portion proceeded under that authorization. A further user continuation implemented synthetic fixtures and the manual-event API; see [the endpoint detail](manual-api.md). See [tasks](tasks.md) for the remaining work. No provider integration was attempted.

[CLAUDE.md, Design-First Gate](../../../CLAUDE.md#design-first-gate) says: “Before writing or editing project code for any change that does not qualify as trivial ... you must produce a written design and receive explicit user approval.” The user’s continuation authorized work on this prepared first slice; later provider integration and broader detector work remain roadmap phases with their own details.
