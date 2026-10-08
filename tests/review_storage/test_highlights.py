"""Persistence checks: preserve intent, detect stale writers, and fail atomically."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Barrier

import pytest

from src.highlights.models import (
    EventReview, EventTiming, HighlightPlan, HighlightState, HighlightTreatment,
    HighlightValidationError, MusicalEvent, PlanContext,
)
from src.review.storage import highlights
from src.review.storage.assignments import save_full_session, save_session


SONG = "aabbccddeeff0011"
SOURCE = "a" * 64


def sample_state():
    event = MusicalEvent("wash-1", SOURCE, "manual-1", "wash", EventTiming(8250, 10100, 9700))
    return HighlightState(SOURCE, 16000, events=(EventReview(event, status="accepted", locked=True),))


def test_no_sidecar_preserves_legacy_songs(state_dir):
    save_full_session(SONG, {"sections": [], "assignments": []})
    assert highlights.load_highlights(SONG) is None


def test_manual_edits_survive_reload_and_session_replacement(state_dir):
    first = highlights.save_highlights(SONG, sample_state(), expected_revision=0)
    reviewed = replace(first.events[0], timing_override=EventTiming(8273, 10113, 9719), note="Corrected by ear")
    second = highlights.save_highlights(SONG, replace(first, events=(reviewed,)), expected_revision=1)
    save_full_session(SONG, {"sections": [], "assignments": [], "lyrics": ["preserve"]})
    save_session(SONG, [], [])
    save_full_session(SONG, {"sections": [], "assignments": []})  # reanalysis replaces the session
    assert highlights.load_highlights(SONG) == second
    assert second.revision == 2
    assert second.events[0].locked is True
    assert second.events[0].effective_timing.start_ms == 8273
    assert second.events[0].event.timing.start_ms == 8250


def test_dismiss_restore_and_remove_keep_revision_history_explicit(state_dir):
    first = highlights.save_highlights(SONG, sample_state(), expected_revision=0)
    dismissed = replace(first.events[0], status="dismissed", locked=False)
    second = highlights.save_highlights(SONG, replace(first, events=(dismissed,)), expected_revision=1)
    third = highlights.save_highlights(SONG, replace(second, events=first.events), expected_revision=2)
    removed = highlights.save_highlights(SONG, replace(third, events=()), expected_revision=3)
    assert removed.revision == 4
    assert highlights.load_highlights(SONG).events == ()


def test_new_draft_and_review_edits_preserve_accepted_snapshots_on_disk(state_dir):
    state = sample_state()
    context = PlanContext(
        source_sha256=SOURCE, duration_ms=16000, analysis_revision="manual-1",
        sections_sha256="b" * 64, layout_sha256="c" * 64,
        themes_sha256="d" * 64, catalog_sha256="e" * 64,
        baseline_sha256="f" * 64, variation_seed=42,
    )
    accepted = HighlightPlan(
        "plan-1", 1, context, events=state.events,
        treatments=(HighlightTreatment("t1", "wash-1", "sustained_wash", ("02_GEO_Left",)),),
    )
    previous = replace(accepted, plan_id="previous-plan")
    first = highlights.save_highlights(
        SONG, replace(state, accepted_plan=accepted, previous_accepted_plan=previous, enabled=True),
        expected_revision=0,
    )
    edited = replace(state.events[0], timing_override=EventTiming(8300, 10200, 9800))
    draft = replace(accepted, revision=2, events=(edited,))
    highlights.save_highlights(
        SONG, replace(first, events=(edited,), draft_plan=draft), expected_revision=1,
    )
    loaded = highlights.load_highlights(SONG)
    assert loaded.accepted_plan == accepted
    assert loaded.previous_accepted_plan == previous
    assert loaded.draft_plan == draft
    assert loaded.accepted_plan.stale_reasons(context, loaded.events) == ("event.wash-1",)
    assert loaded.draft_plan.stale_reasons(context, loaded.events) == ()


def test_old_tab_cannot_overwrite_newer_review(state_dir):
    old = sample_state()
    saved = highlights.save_highlights(SONG, old, expected_revision=0)
    with pytest.raises(highlights.HighlightRevisionConflict):
        highlights.save_highlights(SONG, old, expected_revision=0)
    assert highlights.load_highlights(SONG) == saved


def test_competing_same_revision_writes_have_one_winner(state_dir):
    first = highlights.save_highlights(SONG, sample_state(), expected_revision=0)
    barrier = Barrier(2)

    def write(note):
        state = replace(first, events=(replace(first.events[0], note=note),))
        barrier.wait(timeout=5)
        try:
            return highlights.save_highlights(SONG, state, expected_revision=1)
        except highlights.HighlightRevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, note) for note in ("first", "second")]
        results = [future.result(timeout=10) for future in futures]
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert highlights.load_highlights(SONG) == winners[0]
    assert winners[0].revision == 2


def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(state_dir, monkeypatch):
    first = highlights.save_highlights(SONG, sample_state(), expected_revision=0)
    original_bytes = highlights.highlight_path(SONG).read_bytes()

    def fail_replace(*args):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(highlights.os, "replace", fail_replace)
    with pytest.raises(OSError, match="storage failure"):
        highlights.save_highlights(SONG, replace(first, events=()), expected_revision=1)
    assert highlights.highlight_path(SONG).read_bytes() == original_bytes
    assert not list(highlights.highlight_path(SONG).parent.glob(".highlights-*.tmp"))


@pytest.mark.parametrize("content", [
    "not json", "[]", '{"schema_version":999}',
    '{"revision":0,"revision":1}', '{"revision":NaN}',
])
def test_corrupt_state_is_reported_and_never_overwritten_as_empty(state_dir, content):
    path = highlights.highlight_path(SONG)
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with pytest.raises(highlights.HighlightStorageError):
        highlights.load_highlights(SONG)
    with pytest.raises(highlights.HighlightStorageError):
        highlights.save_highlights(SONG, sample_state(), expected_revision=0)
    assert path.read_text() == content


def test_changed_recording_cannot_reuse_existing_review(state_dir):
    first = highlights.save_highlights(SONG, sample_state(), expected_revision=0)
    replacement = HighlightState("b" * 64, 16000, revision=1)
    with pytest.raises(HighlightValidationError, match="different recording"):
        highlights.save_highlights(SONG, replacement, expected_revision=1)
    assert highlights.load_highlights(SONG) == first


@pytest.mark.parametrize("song_id", ["../escape", "a/b", "a\\b", "", None])
def test_invalid_song_ids_cannot_select_other_files(state_dir, song_id):
    with pytest.raises(HighlightValidationError):
        highlights.save_highlights(song_id, sample_state(), expected_revision=0)


@pytest.mark.parametrize("revision", [True, -1, 1.0, "0"])
def test_invalid_expected_revisions_are_rejected(state_dir, revision):
    with pytest.raises(HighlightValidationError):
        highlights.save_highlights(SONG, sample_state(), expected_revision=revision)


def test_unknown_fields_do_not_silently_drop_user_state(state_dir):
    path = highlights.highlight_path(SONG)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(sample_state().to_dict() | {"future_field": "value"}))
    with pytest.raises(highlights.HighlightStorageError):
        highlights.load_highlights(SONG)


def test_invalid_encoding_is_reported_as_corrupt_state(state_dir):
    path = highlights.highlight_path(SONG)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(highlights.HighlightStorageError, match="UTF-8"):
        highlights.load_highlights(SONG)
