"""Synthetic input contracts for the upcoming recipe compiler."""
import hashlib
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from src.analyzer.audio import load
from src.highlights.models import HighlightPlan, HighlightState
from tests.fixtures.highlights.synthetic import build_fixture


@pytest.mark.parametrize("case", ["sweep_impact", "near_end", "rhythm_only"])
def test_synthetic_fixture_roundtrips_on_production_audio_clock(tmp_path, case):
    fixture = build_fixture(tmp_path, case)
    audio, sr, metadata = load(str(fixture.audio_path))
    assert metadata.duration_ms == fixture.state.duration_ms == 16000
    assert sr == 22050
    assert fixture.state.source_sha256 == hashlib.sha256(fixture.audio_path.read_bytes()).hexdigest()
    assert HighlightPlan.from_dict(json.loads((tmp_path / f"{case}.plan.json").read_text())) == fixture.plan
    assert HighlightState.from_dict(json.loads((tmp_path / f"{case}.state.json").read_text())) == fixture.state
    assert fixture.stems_available == ()
    assert np.max(np.abs(audio)) < 1  # no clipped source
    assert np.any(audio[:sr] != 0)  # ordinary rhythmic context
    assert fixture.state.enabled is False and fixture.state.accepted_plan is None


def test_sweep_is_off_beat_shaped_and_separate_from_impact(tmp_path):
    fixture = build_fixture(tmp_path)
    audio, sr, _ = load(str(fixture.audio_path))
    sweep, impact = fixture.state.events
    assert (sweep.effective_timing.start_ms, sweep.effective_timing.peak_ms,
            sweep.effective_timing.end_ms) == (8273, 9719, 10113)
    assert sweep.effective_timing.end_ms < impact.effective_timing.start_ms
    assert impact.effective_timing.peak_ms is None
    assert [t.resolve_timing(r.effective_timing) for t, r in zip(fixture.plan.treatments, fixture.state.events)] == [(8273, 10113), (10500, 10750)]
    def rms(start, end):
        return np.sqrt(np.mean(audio[round(start * sr):round(end * sr)] ** 2))
    assert rms(9.6, 9.8) > 3 * rms(8.3, 8.5)
    assert np.all(audio[14 * sr:] == 0)


def test_boundary_and_empty_cases(tmp_path):
    near_end = build_fixture(tmp_path, "near_end")
    assert near_end.plan.treatments[0].resolve_timing(near_end.state.events[0].effective_timing) == (15751, 16000)
    empty = build_fixture(tmp_path, "rhythm_only")
    assert empty.plan.events == empty.plan.treatments == ()


def test_fixture_is_repeatable_and_targets_reference_layout(tmp_path):
    first = build_fixture(tmp_path / "first")
    second = build_fixture(tmp_path / "second")
    assert first.audio_path.read_bytes() == second.audio_path.read_bytes()
    assert first.plan == second.plan
    layout = ET.parse("tests/fixtures/reference/layout.xml")
    names = {model.get("name") for model in layout.findall(".//model")}
    assert all(set(t.targets) <= names for t in first.plan.treatments)
