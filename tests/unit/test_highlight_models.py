"""Contract and replay checks for saved musical intent, with no AI dependency."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from src.highlights.models import (
    EventEvidence, EventReview, EventTiming, HighlightPlan, HighlightState,
    HighlightTreatment, HighlightValidationError, MusicalEvent, PlanContext,
    PlanProvenance,
)


SOURCE = "a" * 64


def context(**changes):
    values = dict(source_sha256=SOURCE, duration_ms=16000, analysis_revision="manual-1",
                  sections_sha256="b" * 64, layout_sha256="c" * 64,
                  themes_sha256="d" * 64, catalog_sha256="e" * 64,
                  baseline_sha256="f" * 64, variation_seed=42)
    return PlanContext(**(values | changes))


def wash_review(**changes):
    event = MusicalEvent("wash-1", SOURCE, "manual-1", "unknown_texture",
                         EventTiming(8250, 10100, 9700),
                         evidence=(EventEvidence("manual", "1", note="Off-beat shhh"),))
    return EventReview(event, **(dict(status="accepted", importance=2) | changes))


def wash_plan(**changes):
    values = dict(plan_id="plan-1", revision=1, context=context(), events=(wash_review(),),
                  treatments=(HighlightTreatment("t1", "wash-1", "sustained_wash",
                                                 ("02_GEO_Left",)),))
    return HighlightPlan(**(values | changes))


def test_manual_timing_survives_json_without_beat_or_frame_snapping():
    review = wash_review(timing_override=EventTiming(8273, 10113, 9719))
    plan = wash_plan(events=(review,))
    loaded = HighlightPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert loaded == plan
    assert loaded.events[0].event.timing.start_ms == 8250
    assert loaded.events[0].effective_timing.start_ms == 8273
    assert loaded.events[0].effective_timing.peak_ms == 9719
    assert loaded.treatments[0].resolve_timing(loaded.events[0].effective_timing) == (8273, 10113)
    assert loaded.events[0].event.detection_score is None


def test_accepted_plan_snapshot_is_immutable_and_independent_of_review_edits():
    plan = wash_plan()
    edited = replace(plan.events[0], timing_override=EventTiming(8300, 10200, 9800))
    assert plan.stale_reasons(context(), (edited,)) == ("event.wash-1",)
    assert plan.events[0].effective_timing.start_ms == 8250
    with pytest.raises(FrozenInstanceError):
        plan.events[0].importance = 3
    exported = plan.to_dict()
    exported["events"][0]["event"]["timing"]["start_ms"] = 0
    assert plan.events[0].effective_timing.start_ms == 8250


def test_point_impact_has_no_invented_peak_and_can_have_bounded_effect_duration():
    event = MusicalEvent("hit", SOURCE, "manual-1", "impact", EventTiming(10500, 10500))
    review = EventReview(event, status="accepted")
    treatment = HighlightTreatment("t2", "hit", "isolated_impact", ("08_HERO_Star",),
                                   end_offset_ms=250)
    plan = wash_plan(events=(wash_review(), review), treatments=(wash_plan().treatments[0], treatment))
    assert plan.events[1].effective_timing.peak_ms is None
    assert treatment.resolve_timing(event.timing) == (10500, 10750)
    with pytest.raises(HighlightValidationError, match="unmeasured peak"):
        replace(plan, treatments=(replace(treatment, start_anchor="peak"),))


@pytest.mark.parametrize("timing", [
    {"start_ms": True, "end_ms": 1000},
    {"start_ms": "100", "end_ms": 1000},
    {"start_ms": -1, "end_ms": 1000},
    {"start_ms": 1000, "end_ms": 900},
    {"start_ms": 1000, "end_ms": 2000, "peak_ms": 999},
    {"start_ms": 1000, "end_ms": 2000, "peak_ms": float("nan")},
])
def test_invalid_source_times_are_rejected(timing):
    with pytest.raises(HighlightValidationError):
        EventTiming.from_dict(timing)


@pytest.mark.parametrize("score", [True, "0.5", float("nan"), float("inf"), -0.1, 1.1, 10**400])
def test_invalid_scores_never_enter_saved_intent(score):
    with pytest.raises(HighlightValidationError):
        replace(wash_review().event, salience=score)


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(schema_version=2),
    lambda p: p.update(schema_version=True),
    lambda p: p.update(api_key="must-not-be-persisted"),
    lambda p: p.pop("context"),
    lambda p: p["events"][0]["event"].update(source_sha256="truncated-song-id"),
    lambda p: p["events"][0]["event"].update(kind="imagined_new_instrument"),
    lambda p: p["events"][0].update(importance=True),
    lambda p: p["events"][0].update(locked="yes"),
    lambda p: p["treatments"][0].update(targets="All Lights"),
    lambda p: p["treatments"][0].update(targets=[]),
    lambda p: p["treatments"][0].update(targets=["same", "same"]),
    lambda p: p["treatments"][0].update(recipe_id="execute_custom_xml"),
    lambda p: p["treatments"][0].update(intensity=None),
])
def test_untrusted_or_future_plan_data_is_rejected(mutate):
    data = wash_plan().to_dict()
    mutate(data)
    with pytest.raises(HighlightValidationError):
        HighlightPlan.from_dict(data)


def test_cross_recording_events_and_out_of_bounds_overrides_are_rejected():
    wrong_source = replace(wash_review(), event=replace(wash_review().event, source_sha256="1" * 64))
    with pytest.raises(HighlightValidationError, match="different recording"):
        wash_plan(events=(wrong_source,))
    with pytest.raises(HighlightValidationError, match="exceeds recording"):
        wash_plan(events=(wash_review(timing_override=EventTiming(8200, 17000)),))
    with pytest.raises(HighlightValidationError, match="outside the recording"):
        wash_plan(context=context(duration_ms=10200),
                  treatments=(replace(wash_plan().treatments[0], end_offset_ms=500),))


def test_duplicate_ids_unknown_refs_and_dismissed_events_are_rejected():
    with pytest.raises(HighlightValidationError, match="Duplicate event"):
        wash_plan(events=(wash_review(), wash_review()))
    with pytest.raises(HighlightValidationError, match="Duplicate treatment"):
        wash_plan(treatments=wash_plan().treatments * 2)
    with pytest.raises(HighlightValidationError, match="unknown event"):
        wash_plan(treatments=(replace(wash_plan().treatments[0], event_id="missing"),))
    with pytest.raises(HighlightValidationError, match="dismissed"):
        wash_plan(events=(wash_review(status="dismissed"),))


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "1" * 64), ("duration_ms", 17000), ("analysis_revision", "manual-2"),
    ("sections_sha256", "1" * 64), ("layout_sha256", "1" * 64),
    ("themes_sha256", "1" * 64), ("catalog_sha256", "1" * 64),
    ("baseline_sha256", "1" * 64), ("variation_seed", 43), ("recipe_version", "2"),
])
def test_each_relevant_input_change_invalidates_a_saved_plan(field, value):
    plan = wash_plan()
    current_context = replace(context(), **{field: value})
    events = plan.events
    if field == "source_sha256":
        events = (replace(events[0], event=replace(events[0].event, source_sha256=value)),)
    assert f"context.{field}" in plan.stale_reasons(current_context, events)


def test_identical_inputs_reuse_snapshot_but_deleted_event_is_stale():
    plan = HighlightPlan.from_dict(wash_plan().to_dict())
    assert not plan.stale_reasons(context(), plan.events)
    assert plan.stale_reasons(context(), ()) == ("event.wash-1",)


def test_empty_plan_and_old_no_highlight_state_are_valid_noops():
    plan = HighlightPlan("empty", 1, context())
    state = HighlightState(SOURCE, 16000, accepted_plan=plan, enabled=True)
    assert HighlightState.from_dict(state.to_dict()) == state
    assert HighlightState(SOURCE, 16000).enabled is False
    assert plan.treatments == ()


def test_drafts_do_not_implicitly_become_accepted():
    draft = wash_plan(events=(wash_review(status="candidate"),))
    state = HighlightState(SOURCE, 16000, events=draft.events, draft_plan=draft)
    assert state.accepted_plan is None
    with pytest.raises(HighlightValidationError, match="without an accepted"):
        replace(state, enabled=True)
    with pytest.raises(HighlightValidationError, match="accepted event reviews"):
        replace(state, accepted_plan=draft)


def test_provenance_cannot_claim_ai_without_recording_which_request_configuration():
    with pytest.raises(HighlightValidationError, match="requires"):
        PlanProvenance(origin="ai")
    with pytest.raises(HighlightValidationError):
        PlanProvenance(origin="manual", provider="example")
    ai = PlanProvenance("ai", "example-provider", "example-model", "prompt-1")
    assert PlanProvenance.from_dict(ai.to_dict()) == ai


def test_json_records_cannot_hide_mutable_lists_in_frozen_models():
    with pytest.raises(HighlightValidationError):
        wash_plan(events=[wash_review()])
    with pytest.raises(HighlightValidationError):
        HighlightTreatment("t1", "wash-1", "sustained_wash", ["group"])
