# AI Highlights listening benchmark

Status: **Inventory and annotation format prepared; listening labels pending.**

See [the benchmark protocol](../../../docs/ai-highlights/benchmark.md) for the scoring rules and [the project tracker](../../../AI_HIGHLIGHTS_ROADMAP.md) for current progress.

`manifest.json` pins the four existing CC0 fixture recordings by content hash and reserves two additional real-recording slots. It assigns development and holdout splits before any new highlight-detector tuning. Descriptions indicate intended coverage, not verified events. The existing CC0 corpus has previously been used by this repository; its holdout assignment is specific to this new feature, not a claim that the music was never used in earlier development.

`annotations/*.json` contains draft listening worksheets. **An empty `events` array with `review_status: pending` is unannotated data, not a verified negative example.** None of these worksheets is eligible for scoring until its continuous windows have been listened to, labeled, and signed off.

Audio is downloaded into the existing ignored `tests/fixtures/cc0_music/` directory. No audio bytes are added to version control. From the repository root:

```bash
.venv/bin/python -m tests.validation.download_fixtures
```

If the macOS Python installation has no trusted CA path, use an installed CA bundle via `SSL_CERT_FILE`; keep certificate verification enabled. The 2026-10-08 preparation used the host's installed `certifi` bundle and verified all four existing SHA-256 values without changing the source manifest.

The production loader `src.analyzer.audio.load` defines the annotation clock. Durations and sample counts in the inventory were measured with that loader, not copied from the approximate corpus descriptions. Record the loader/dependency versions when refreshing metadata; a decoder change is a benchmark revision.

## Listening workflow

1. Read the matching annotation JSON and play the exact hash-pinned file in the application's timeline or another player showing time from the recording start.
2. Listen to every listed window in full, with surrounding context. Write down exceptional events before looking at detector predictions.
3. Give each event start/peak/end timestamps, event-presence certainty, highlight importance, and listening notes using the format in the protocol. Repeated ordinary beats can be recorded as a routine-pattern interval rather than hundreds of event rows.
4. Label negative intervals where there are no desired highlights. Mark genuine uncertainty explicitly; do not guess what an instrument is.
5. Fill the reviewer/date fields and set only fully reviewed windows to `complete`. Unreviewed windows remain excluded from scoring.
6. Use development recordings for tuning. Keep holdout labels and outcomes out of detector/prompt tuning; promote a consumed holdout to development and reserve new recordings if repeated iteration uses it.

Private additional recordings should be stored outside tracked fixture data (for example under ignored `songs/`). Commit hashes and nonprivate annotation metadata only when appropriate; do not copy private library paths or audio into shared fixtures.

## Synthetic integration fixtures

[synthetic_cases.json](synthetic_cases.json) hand-authors an off-beat sweep (8273–10113 ms, envelope peak 9719 ms), a separate point impact (10500 ms, 250 ms treatment), a near-end impact (15751 ms, treatment ending at 16000 ms), and a rhythm-only case with no highlights. All cases have a full mix with ordinary rhythm and no stems. They are independent of the real listening split above.

[synthetic.py](synthetic.py) writes a deterministic 16-second mono PCM WAV and versioned state/plan JSON into a directory you choose. Tests use temporary directories. To generate local examples:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
from tests.fixtures.highlights.synthetic import build_fixture
for case in ('sweep_impact', 'near_end', 'rhythm_only'):
    build_fixture(Path('analysis/ai-highlights-synthetic/2026-10-08'), case)
PY
```

These files were generated locally under that ignored directory. Construction times are accurate to the nearest source sample; the event model retains the authored integer milliseconds. The sweep's `peak_ms` is its designed amplitude-envelope peak, not a detector output or a listener estimate. A point impact deliberately lacks a measured peak; its treatment adds a bounded duration.

The plan targets models in [the reference layout](../reference/layout.xml). Its source and layout hashes are real; section/theme/catalog/baseline fingerprints explicitly represent synthetic placeholders. The fixture is draft intent for compiler development, not a plan accepted against the application's actual catalog. Compiler integration must supply the real context and validate eligibility before replay. Generation is repeatable in the pinned local environment; the WAV digest is measured after writing, not guessed or copied from another case.

## Compile a local XSQ example

Run `.venv/bin/python -m tests.fixtures.highlights.compile_example --output analysis/ai-highlights-compiler/2026-10-08` to compile the sweep/impact against a simple authored baseline and the real catalog. This saves the source WAV, layout, baseline and enhanced XSQs, a reloaded plan, and a replay/hash report. See [compiler evidence](../../../docs/ai-highlights/compiler-2026-10-08.md). This helper does not use the application export API or render xLights.
