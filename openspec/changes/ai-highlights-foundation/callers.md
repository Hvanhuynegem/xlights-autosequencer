# Caller inventory — 2026-10-08

The implemented foundation adds `src/highlights/models.py` and `src/review/storage/highlights.py`; it changes no existing public signatures. They are now called by `src/review/api/v1/highlights.py` (registered through the existing Blueprint), the synthetic fixture builder, and their tests. Existing generator signatures/callers remain unchanged.

The manual API adds `get_highlights` and `put_highlights`; Flask route dispatch is their runtime caller. `src/review/server.py:create_app` continues to register the same `api_v1` Blueprint. `tests/review/test_api_highlights.py` exercises real import and route registration. No existing route signature changed.

For the remaining manual-to-export slice, the search below inventories existing constructor/function references across source and tests, including definitions and comments. Re-run and inspect each relevant call before integration; this is a search snapshot, not proof that all routes are wired.

```sh
rg -n 'build_plan\(|GenerationConfig\(|SequencePlan\(|write_xsq\(|run_generator\(|generator_runner\.run\(|run_section_preview\(' src tests
rg -n 'src.highlights|load_highlights|save_highlights' src tests
```

## Integration decisions

- `src/review/api/v1/export.py` → `src/evaluation/generator_runner.py` → `GenerationConfig` → `build_plan` → `SequencePlan` → `write_xsq`: thread a validated accepted snapshot through this active path. Keep defaults disabled for old callers.
- `src/generator/preview.py` and preview routes: preserve highlight placements when making scoped plans; include the accepted revision and context in cache identity. Current scoped plans omit song-level effect collections.
- CLI/wizard, validation, microscope, and legacy generation callers: keep constructors compatible and default behavior unchanged. Explicit support remains P7.4.
- Analysis/session replacement paths: the separate sidecar needs no changes to session serialization. It must still be checked for stale input before generation.
- `src/review/storage/bundle.py` and single-song bundle endpoints: accepted highlights are not portable yet; extend and test both before declaring P1.3 complete.
- New storage functions support one backend process. The thread lock does not coordinate separate server processes.

## Existing references

| File | Matching line numbers |
|---|---|
| [src/cli/evaluate.py](../../../src/cli/evaluate.py) | 130 |
| [src/cli_old.py](../../../src/cli_old.py) | 1933 |
| [src/evaluation/compare.py](../../../src/evaluation/compare.py) | 475 |
| [src/evaluation/generator_runner.py](../../../src/evaluation/generator_runner.py) | 243, 280, 285 |
| [src/generator/models.py](../../../src/generator/models.py) | 162, 181, 190, 227, 286, 348 |
| [src/generator/plan.py](../../../src/generator/plan.py) | 143, 682, 1101, 1106, 1236, 1243 |
| [src/generator/preview.py](../../../src/generator/preview.py) | 272, 281, 323, 356, 382 |
| [src/generator/transitions.py](../../../src/generator/transitions.py) | 310 |
| [src/generator/xsq_writer.py](../../../src/generator/xsq_writer.py) | 409 |
| [src/generator_wizard.py](../../../src/generator_wizard.py) | 47 |
| [src/microscope/runner.py](../../../src/microscope/runner.py) | 207 |
| [src/review/api/v1/export.py](../../../src/review/api/v1/export.py) | 69, 127, 186, 306 |
| [src/review/generate_routes.py](../../../src/review/generate_routes.py) | 349 |
| [src/review/preview_routes.py](../../../src/review/preview_routes.py) | 85, 184 |
| [src/validation/scenarios.py](../../../src/validation/scenarios.py) | 47 |
| [tests/evaluation/test_generator_runner.py](../../../tests/evaluation/test_generator_runner.py) | 66, 70, 113, 117, 140, 161, 165, 186, 209, 213 |
| [tests/integration/test_duration_scaling.py](../../../tests/integration/test_duration_scaling.py) | 3, 45, 75, 304, 359, 453, 483, 542 |
| [tests/integration/test_generate_with_curves.py](../../../tests/integration/test_generate_with_curves.py) | 1, 103, 110, 256, 263, 273 |
| [tests/integration/test_generator_equivalence.py](../../../tests/integration/test_generator_equivalence.py) | 152, 172, 175 |
| [tests/integration/test_palette_restraint.py](../../../tests/integration/test_palette_restraint.py) | 111, 121 |
| [tests/integration/test_phase1_metrics.py](../../../tests/integration/test_phase1_metrics.py) | 44 |
| [tests/integration/test_section_preview.py](../../../tests/integration/test_section_preview.py) | 138, 171, 491 |
| [tests/integration/test_sequence_generation.py](../../../tests/integration/test_sequence_generation.py) | 125, 131, 133, 231, 236 |
| [tests/review/test_api_export.py](../../../tests/review/test_api_export.py) | 570 |
| [tests/unit/test_beat_accents.py](../../../tests/unit/test_beat_accents.py) | 1008, 1016, 1448, 1455 |
| [tests/unit/test_brief_persistence.py](../../../tests/unit/test_brief_persistence.py) | 140 |
| [tests/unit/test_generation_config.py](../../../tests/unit/test_generation_config.py) | 23, 29, 35, 41, 47, 53, 59, 65, 71, 78 |
| [tests/unit/test_generator/test_crash_accents_placement.py](../../../tests/unit/test_generator/test_crash_accents_placement.py) | 202, 209 |
| [tests/unit/test_generator/test_picture_effects.py](../../../tests/unit/test_generator/test_picture_effects.py) | 606, 613 |
| [tests/unit/test_generator/test_plan.py](../../../tests/unit/test_generator/test_plan.py) | 155, 162, 182, 189, 208, 217, 230, 237, 239, 279, 287, 322, 330, 344, 352, 374, 384, 405, 411, 415, 422 |
| [tests/unit/test_generator/test_xsq_writer.py](../../../tests/unit/test_generator/test_xsq_writer.py) | 104, 114, 1476, 1533, 1553, 1576, 1588, 1628, 1645, 1690, 1700, 1714, 1728, 1753, 1764, 1777, 1809, 1826, 1849, 1946, 1990, 2009, 2039, 2041, 2086, 2128, 2140, 2178, 2199, 2213, 2225, 2244, 2257, 2269, 2279, 2295, 2320, 2330, 2354, 2379, 2394, 2423, 2453, 2473, 2576, 2612 |
| [tests/unit/test_render_panel.py](../../../tests/unit/test_render_panel.py) | 21, 42, 49 |
| [tests/unit/test_section_assignment.py](../../../tests/unit/test_section_assignment.py) | 5, 73, 95, 104 |
| [tests/validation/test_real_audio.py](../../../tests/validation/test_real_audio.py) | 250, 257, 261, 345, 352 |
| [tests/validation/test_scenarios.py](../../../tests/validation/test_scenarios.py) | 44 |
| [tests/validation/test_sequence_validation.py](../../../tests/validation/test_sequence_validation.py) | 237, 281, 307, 325, 621, 627, 640, 648, 656 |

## Compiler increment caller audit

`compile_highlights` is new; only its tests and `tests/fixtures/highlights/compile_example.py` call it so far. `write_xsq` keeps its signature and gathers a default-empty collection. `SequencePlan` appends that defaulted field; existing references above remain untouched. `EffectPlacement` appends `frame_interval_ms=25` and preserves default constructor behavior; the compiler opts into its plan clock. The following constructor files were found with `rg -l 'EffectPlacement\(' src tests` before that change (all retain defaults except the new compiler):

- [tests/validation/test_sequence_validation.py](../../../tests/validation/test_sequence_validation.py)
- [tests/integration/test_section_preview.py](../../../tests/integration/test_section_preview.py)
- [src/generator/moving_head.py](../../../src/generator/moving_head.py)
- [src/generator/highlights.py](../../../src/generator/highlights.py)
- [tests/integration/test_generate_with_curves.py](../../../tests/integration/test_generate_with_curves.py)
- [src/generator/effect_placer.py](../../../src/generator/effect_placer.py)
- [src/generator/plan.py](../../../src/generator/plan.py)
- [src/generator/xsq_writer.py](../../../src/generator/xsq_writer.py)
- [tests/integration/test_palette_restraint.py](../../../tests/integration/test_palette_restraint.py)
- [tests/unit/test_transitions.py](../../../tests/unit/test_transitions.py)
- [tests/unit/test_generator/test_highlights.py](../../../tests/unit/test_generator/test_highlights.py)
- [tests/unit/test_generator/test_value_curves.py](../../../tests/unit/test_generator/test_value_curves.py)
- [tests/unit/test_generator/test_effect_placer.py](../../../tests/unit/test_generator/test_effect_placer.py)
- [tests/unit/test_generator/test_moving_head_pattern_accents.py](../../../tests/unit/test_generator/test_moving_head_pattern_accents.py)
- [tests/unit/test_generator/test_moving_head_crash_accents.py](../../../tests/unit/test_generator/test_moving_head_crash_accents.py)
- [tests/unit/test_generator/test_plan_validator.py](../../../tests/unit/test_generator/test_plan_validator.py)
- [tests/unit/test_generator/test_moving_head_keyword_accents.py](../../../tests/unit/test_generator/test_moving_head_keyword_accents.py)
- [tests/unit/test_generator/test_direction_alternation.py](../../../tests/unit/test_generator/test_direction_alternation.py)
- [tests/unit/test_generator/test_moving_head_moves.py](../../../tests/unit/test_generator/test_moving_head_moves.py)
- [tests/unit/test_generator/test_xsq_writer.py](../../../tests/unit/test_generator/test_xsq_writer.py)
- [tests/unit/test_generator/test_moving_head_ending_punches.py](../../../tests/unit/test_generator/test_moving_head_ending_punches.py)

Frame headers now honor the plan interval. All four actual generator equivalence configurations were compared with HEAD models/writer and matched byte-for-byte after canonicalization; their pre-existing old-golden failures remain recorded. See [compiler evidence](../../../docs/ai-highlights/compiler-2026-10-08.md).

## Live context and export caller audit

`build_plan` keeps its signature; default config state does not capture context. `GenerationConfig` and `SequencePlan` append defaulted fields. `generator_runner.run/_run_pipeline` append optional state/reviewed-section arguments. Export passes them only for enabled state, keeping existing default call shapes unchanged. `_run_export` appends a snapshot argument; start_export supplies it by keyword only when enabled. `GeneratorError` adds an optional issue code. Constructor signatures for previous positional users remain compatible.

Searched with `rg -n 'run_generator\(|generator_runner\.run\(|_run_pipeline\(|_run_export\(' src tests`. Files found:

- [src/cli/evaluate.py](../../../src/cli/evaluate.py)
- [src/evaluation/compare.py](../../../src/evaluation/compare.py)
- [src/evaluation/generator_runner.py](../../../src/evaluation/generator_runner.py)
- [src/review/api/v1/export.py](../../../src/review/api/v1/export.py)
- [tests/evaluation/test_generator_runner.py](../../../tests/evaluation/test_generator_runner.py)
- [tests/review/test_api_export.py](../../../tests/review/test_api_export.py)

New tests: `tests/unit/test_generator/test_highlight_context.py`, `tests/review/test_highlight_export.py`, and additional runner checks. Legacy CLI/preview callers remain baseline-only until explicitly wired. Download-package uses a saved layout snapshot for enhanced exports; baseline package behavior stays unchanged.
