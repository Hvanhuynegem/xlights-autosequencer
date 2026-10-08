"""Generate full-mix timing fixtures, without detector, stems, or private audio.

Labels are author-specified sound construction times; they are not listening
benchmark annotations. Source SHA-256 is measured from the generated WAV.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import wave

import numpy as np

from src.highlights.models import (
    EventEvidence, EventReview, EventTiming, HighlightPlan, HighlightState,
    HighlightTreatment, MusicalEvent, PlanContext,
)

_FIXTURES = Path(__file__).parent


@dataclass(frozen=True)
class SyntheticHighlightFixture:
    audio_path: Path
    state: HighlightState
    plan: HighlightPlan
    stems_available: tuple = ()


def build_fixture(directory: Path, case: str = "sweep_impact") -> SyntheticHighlightFixture:
    """Write generated WAV + portable state/plan JSON into a test-owned directory."""
    spec = json.loads((_FIXTURES / "synthetic_cases.json").read_text())
    definition = spec["cases"][case]
    sr, duration_ms = spec["sample_rate"], spec["duration_ms"]
    audio = np.zeros(sr * duration_ms // 1000, dtype=np.float64)
    rng = np.random.default_rng(spec["noise_seed"])

    def add(start_ms, signal):
        start = round(start_ms * sr / 1000)
        length = min(len(signal), len(audio) - start)
        audio[start:start + length] += signal[:length]

    # 120 BPM alternating kick/snare. Leave the exceptional sweep interval clear
    # and stop the ordinary pattern at 14 seconds for a quiet tail.
    t = np.arange(round(.08 * sr)) / sr
    for index, start in enumerate(range(0, 14000, 500)):
        if case == "sweep_impact" and 8000 <= start <= 10500:
            continue
        sound = np.sin(2 * np.pi * 100 * t) if index % 2 == 0 else rng.uniform(-1, 1, len(t))
        add(start, .18 * sound * np.exp(-50 * t))

    for event in definition["events"]:
        if event["kind"] == "sweep":
            start = round(event["start_ms"] * sr / 1000)
            end = round(event["end_ms"] * sr / 1000)
            peak = round(event["peak_ms"] * sr / 1000) - start
            envelope = np.interp(np.arange(end - start), [0, peak, end - start - 1], [0, .7, 0])
            noise = rng.uniform(-1, 1, end - start)
            # Difference emphasizes the noisy high-frequency "shhh" texture.
            noise = np.diff(noise, prepend=noise[0]) * .5
            add(event["start_ms"], noise * envelope)
        else:
            length = round(event["end_offset_ms"] * sr / 1000)
            t = np.arange(length) / sr
            pulse = .55 * np.cos(2 * np.pi * 75 * t) + .35 * rng.uniform(-1, 1, length)
            add(event["start_ms"], pulse * np.exp(-25 * t))

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case}.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sr)
        output.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    source = hashlib.sha256(path.read_bytes()).hexdigest()
    reviews, treatments = [], []
    for item in definition["events"]:
        event = MusicalEvent(
            item["event_id"], source, "synthetic-v1", item["kind"],
            EventTiming(item["start_ms"], item["end_ms"], item["peak_ms"]),
            evidence=(EventEvidence("synthetic-construction", "1", note=definition["description"]),),
        )
        reviews.append(EventReview(event, status="accepted", importance=2))
        treatments.append(HighlightTreatment(
            f"treatment-{item['event_id']}", item["event_id"], item["recipe_id"],
            (item["target"],), end_offset_ms=item["end_offset_ms"],
        ))

    def digest(label):
        return hashlib.sha256(label.encode()).hexdigest()

    layout = _FIXTURES.parent / "reference" / "layout.xml"
    context = PlanContext(
        source, duration_ms, "synthetic-v1", digest("synthetic-sections-v1"),
        hashlib.sha256(layout.read_bytes()).hexdigest(), digest("synthetic-themes-v1"),
        digest("synthetic-catalog-v1"), digest("synthetic-baseline-v1"), spec["noise_seed"],
    )
    plan = HighlightPlan(f"synthetic-{case}", 1, context, tuple(reviews), tuple(treatments))
    # Draft intent only: no assertion that a real catalog/compiler has accepted it.
    state = HighlightState(source, duration_ms, events=tuple(reviews), draft_plan=plan)
    for suffix, record in (("state", state), ("plan", plan)):
        (directory / f"{case}.{suffix}.json").write_text(json.dumps(record.to_dict(), indent=2) + "\n")
    return SyntheticHighlightFixture(path, state, plan)
