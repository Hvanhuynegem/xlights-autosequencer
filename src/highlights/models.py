"""Versioned, immutable records for reviewed musical events and choreography.

These records validate saved intent. They do not establish that a target exists
in a layout, that a recipe can render, or that an AI suggestion is musically
correct; the generator must validate those properties before accepting a plan.
Times remain on the source-audio clock. Output quantization belongs to the
compiler, not these records.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
import re
from typing import Any, ClassVar


SCHEMA_VERSION = 1
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EVENT_KINDS = frozenset({
    "impact", "sweep", "wash", "fill", "energy_surge", "energy_drop",
    "silence", "vocal_entry", "vocal_exit", "instrument_entry",
    "texture_shift", "unknown_texture", "chorus_arrival",
})
RECIPE_IDS = frozenset({"sustained_wash", "isolated_impact"})


class HighlightValidationError(ValueError):
    """A highlight record violates its versioned data contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HighlightValidationError(message)


def _integer(value: Any, name: str, low: int = 0, high: int | None = None) -> None:
    _require(type(value) is int, f"{name} must be an integer")
    _require(value >= low and (high is None or value <= high), f"{name} is out of range")


def _text(value: Any, name: str, *, maximum: int = 1000, empty: bool = False) -> None:
    _require(isinstance(value, str), f"{name} must be a string")
    _require((empty or bool(value.strip())) and len(value) <= maximum,
             f"{name} must contain {'0' if empty else '1'}–{maximum} characters")


def _identifier(value: Any, name: str) -> None:
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None,
             f"{name} must be a valid identifier")


def _hash(value: Any, name: str) -> None:
    _require(isinstance(value, str) and _SHA256.fullmatch(value) is not None,
             f"{name} must be a lowercase SHA-256 digest")


def _choice(value: Any, name: str, choices) -> None:
    _require(isinstance(value, str) and value in choices, f"Invalid {name}")


def _score(value: Any, name: str) -> None:
    if value is not None:
        _require(type(value) in (int, float) and 0 <= value <= 1 and math.isfinite(value),
                 f"{name} must be finite and between 0 and 1, or null")


def _boolean(value: Any, name: str) -> None:
    _require(type(value) is bool, f"{name} must be a boolean")


def _records(value: Any, kind: type, name: str, maximum: int = 2000) -> None:
    _require(isinstance(value, tuple) and len(value) <= maximum,
             f"{name} must be a tuple with at most {maximum} entries")
    _require(all(isinstance(item, kind) for item in value), f"Invalid entry in {name}")


def _list_of(kind):
    def parse(value):
        _require(type(value) is list, "Expected a JSON array")
        _require(len(value) <= 2000, "Too many highlight records")
        return tuple(kind.from_dict(item) if issubclass(kind, _Record) else item for item in value)
    return parse


def _optional(kind):
    return lambda value: None if value is None else kind.from_dict(value)


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class _Record:
    _parsers: ClassVar[dict] = {}

    def to_dict(self) -> dict:
        return _json_value(asdict(self))

    @classmethod
    def from_dict(cls, data: dict):
        _require(type(data) is dict, f"{cls.__name__} must be an object")
        allowed = {field.name for field in fields(cls)}
        _require(not set(data) - allowed, f"Unknown fields in {cls.__name__}")
        values = dict(data)
        for key, parser in cls._parsers.items():
            if key in values:
                values[key] = parser(values[key])
        try:
            return cls(**values)
        except TypeError as exc:
            raise HighlightValidationError(f"Missing or invalid fields in {cls.__name__}") from exc


@dataclass(frozen=True)
class EventTiming(_Record):
    start_ms: int
    end_ms: int
    peak_ms: int | None = None

    def __post_init__(self):
        _integer(self.start_ms, "start_ms")
        _integer(self.end_ms, "end_ms", self.start_ms)
        if self.peak_ms is not None:
            _integer(self.peak_ms, "peak_ms", self.start_ms, self.end_ms)


@dataclass(frozen=True)
class EventEvidence(_Record):
    source: str
    revision: str
    stem: str | None = None
    note: str = ""

    def __post_init__(self):
        _text(self.source, "evidence.source", maximum=128)
        _text(self.revision, "evidence.revision", maximum=128)
        if self.stem is not None:
            _text(self.stem, "evidence.stem", maximum=64)
        _text(self.note, "evidence.note", empty=True)


@dataclass(frozen=True)
class MusicalEvent(_Record):
    event_id: str
    source_sha256: str
    source_revision: str
    kind: str
    timing: EventTiming
    provenance: str = "manual"
    detection_score: float | None = None
    intensity: float | None = None
    salience: float | None = None
    evidence: tuple[EventEvidence, ...] = ()

    _parsers = {"timing": EventTiming.from_dict, "evidence": _list_of(EventEvidence)}

    def __post_init__(self):
        _identifier(self.event_id, "event_id")
        _hash(self.source_sha256, "source_sha256")
        _text(self.source_revision, "source_revision", maximum=128)
        _choice(self.kind, "event kind", _EVENT_KINDS)
        _require(isinstance(self.timing, EventTiming), "Invalid event timing")
        _choice(self.provenance, "event provenance", {"manual", "detector", "audio_model"})
        for name in ("detection_score", "intensity", "salience"):
            _score(getattr(self, name), name)
        _records(self.evidence, EventEvidence, "evidence", maximum=32)


@dataclass(frozen=True)
class EventReview(_Record):
    event: MusicalEvent
    status: str = "candidate"
    timing_override: EventTiming | None = None
    importance: int | None = None
    locked: bool = False
    note: str = ""

    _parsers = {"event": MusicalEvent.from_dict, "timing_override": _optional(EventTiming)}

    def __post_init__(self):
        _require(isinstance(self.event, MusicalEvent), "Invalid reviewed event")
        _choice(self.status, "review status", {"candidate", "accepted", "dismissed"})
        _require(self.timing_override is None or isinstance(self.timing_override, EventTiming),
                 "Invalid timing override")
        if self.importance is not None:
            _integer(self.importance, "importance", 0, 3)
        _boolean(self.locked, "locked")
        _text(self.note, "review note", empty=True)

    @property
    def effective_timing(self) -> EventTiming:
        return self.timing_override or self.event.timing


@dataclass(frozen=True)
class PlanContext(_Record):
    source_sha256: str
    duration_ms: int
    analysis_revision: str
    sections_sha256: str
    layout_sha256: str
    themes_sha256: str
    catalog_sha256: str
    baseline_sha256: str
    variation_seed: int
    recipe_version: str = "1"

    def __post_init__(self):
        for name in ("source_sha256", "sections_sha256", "layout_sha256", "themes_sha256",
                     "catalog_sha256", "baseline_sha256"):
            _hash(getattr(self, name), name)
        _integer(self.duration_ms, "duration_ms", 1)
        _integer(self.variation_seed, "variation_seed", 0, 2**32 - 1)
        _text(self.analysis_revision, "analysis_revision", maximum=128)
        _text(self.recipe_version, "recipe_version", maximum=64)


@dataclass(frozen=True)
class HighlightTreatment(_Record):
    treatment_id: str
    event_id: str
    recipe_id: str
    targets: tuple[str, ...]
    intensity: float = 0.7
    start_anchor: str = "start"
    end_anchor: str = "end"
    start_offset_ms: int = 0
    end_offset_ms: int = 0
    palette_source: str = "section"
    locked: bool = False
    rationale: str = ""

    _parsers = {"targets": _list_of(str)}

    def __post_init__(self):
        _identifier(self.treatment_id, "treatment_id")
        _identifier(self.event_id, "treatment.event_id")
        _choice(self.recipe_id, "recipe_id", RECIPE_IDS)
        _records(self.targets, str, "targets", maximum=32)
        _require(bool(self.targets), "A treatment needs at least one target")
        for target in self.targets:
            _text(target, "target", maximum=256)
        _require(len(set(self.targets)) == len(self.targets), "Duplicate treatment targets")
        _require(self.intensity is not None, "Treatment intensity is required")
        _score(self.intensity, "treatment intensity")
        _choice(self.start_anchor, "start_anchor", {"start", "peak", "end"})
        _choice(self.end_anchor, "end_anchor", {"start", "peak", "end"})
        _integer(self.start_offset_ms, "start_offset_ms", -2000, 2000)
        _integer(self.end_offset_ms, "end_offset_ms", -2000, 2000)
        _choice(self.palette_source, "palette_source", {"section"})
        _boolean(self.locked, "treatment.locked")
        _text(self.rationale, "rationale", maximum=500, empty=True)

    def resolve_timing(self, timing: EventTiming) -> tuple[int, int]:
        start = getattr(timing, self.start_anchor + "_ms")
        end = getattr(timing, self.end_anchor + "_ms")
        _require(start is not None and end is not None, "Treatment references an unmeasured peak")
        return start + self.start_offset_ms, end + self.end_offset_ms


@dataclass(frozen=True)
class PlanProvenance(_Record):
    origin: str = "manual"
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None

    def __post_init__(self):
        _choice(self.origin, "plan origin", {"manual", "local", "ai"})
        for name in ("provider", "model", "prompt_version"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name, maximum=128)
        if self.origin == "ai":
            _require(all((self.provider, self.model, self.prompt_version)),
                     "AI provenance requires provider, model, and prompt_version")
        else:
            _require(all(getattr(self, name) is None for name in ("provider", "model", "prompt_version")),
                     "Non-AI provenance cannot name an AI provider/model/prompt")


def _validate_events(events: tuple[EventReview, ...], source_sha256: str, duration_ms: int) -> None:
    _records(events, EventReview, "events")
    ids = [review.event.event_id for review in events]
    _require(len(ids) == len(set(ids)), "Duplicate event IDs")
    for review in events:
        _require(review.event.source_sha256 == source_sha256, "Event belongs to a different recording")
        _require(review.event.timing.end_ms <= duration_ms and review.effective_timing.end_ms <= duration_ms,
                 "Event timing exceeds recording duration")


@dataclass(frozen=True)
class HighlightPlan(_Record):
    plan_id: str
    revision: int
    context: PlanContext
    events: tuple[EventReview, ...] = ()
    treatments: tuple[HighlightTreatment, ...] = ()
    provenance: PlanProvenance = PlanProvenance()
    schema_version: int = SCHEMA_VERSION

    _parsers = {"context": PlanContext.from_dict, "events": _list_of(EventReview),
                "treatments": _list_of(HighlightTreatment), "provenance": PlanProvenance.from_dict}

    def __post_init__(self):
        _require(type(self.schema_version) is int and self.schema_version == SCHEMA_VERSION,
                 "Unsupported highlight plan schema_version")
        _identifier(self.plan_id, "plan_id")
        _integer(self.revision, "plan revision", 1)
        _require(isinstance(self.context, PlanContext), "Invalid plan context")
        _require(isinstance(self.provenance, PlanProvenance), "Invalid plan provenance")
        _validate_events(self.events, self.context.source_sha256, self.context.duration_ms)
        _records(self.treatments, HighlightTreatment, "treatments", maximum=500)
        ids = [t.treatment_id for t in self.treatments]
        _require(len(ids) == len(set(ids)), "Duplicate treatment IDs")
        by_id = {r.event.event_id: r for r in self.events}
        for treatment in self.treatments:
            _require(treatment.event_id in by_id, "Treatment references an unknown event")
            review = by_id[treatment.event_id]
            _require(review.status != "dismissed", "Treatment references a dismissed event")
            start, end = treatment.resolve_timing(review.effective_timing)
            _require(0 <= start < end <= self.context.duration_ms,
                     "Resolved treatment timing is outside the recording or has no duration")

    def stale_reasons(self, context: PlanContext, events: tuple[EventReview, ...]) -> tuple[str, ...]:
        """Compare this snapshot to current inputs; never remap event IDs silently."""
        reasons = [f"context.{f.name}" for f in fields(PlanContext)
                   if getattr(self.context, f.name) != getattr(context, f.name)]
        _validate_events(events, context.source_sha256, context.duration_ms)
        current = {r.event.event_id: r for r in events}
        for review in self.events:
            if current.get(review.event.event_id) != review:
                reasons.append(f"event.{review.event.event_id}")
        return tuple(reasons)


@dataclass(frozen=True)
class HighlightState(_Record):
    source_sha256: str
    duration_ms: int
    revision: int = 0
    events: tuple[EventReview, ...] = ()
    draft_plan: HighlightPlan | None = None
    accepted_plan: HighlightPlan | None = None
    previous_accepted_plan: HighlightPlan | None = None
    enabled: bool = False
    schema_version: int = SCHEMA_VERSION

    _parsers = {"events": _list_of(EventReview), "draft_plan": _optional(HighlightPlan),
                "accepted_plan": _optional(HighlightPlan),
                "previous_accepted_plan": _optional(HighlightPlan)}

    def __post_init__(self):
        _require(type(self.schema_version) is int and self.schema_version == SCHEMA_VERSION,
                 "Unsupported highlight state schema_version")
        _hash(self.source_sha256, "source_sha256")
        _integer(self.duration_ms, "duration_ms", 1)
        _integer(self.revision, "state revision")
        _boolean(self.enabled, "enabled")
        _validate_events(self.events, self.source_sha256, self.duration_ms)
        for name in ("draft_plan", "accepted_plan", "previous_accepted_plan"):
            plan = getattr(self, name)
            if plan is not None:
                _require(isinstance(plan, HighlightPlan), f"Invalid {name}")
                _require(plan.context.source_sha256 == self.source_sha256,
                         f"{name} belongs to a different recording")
        _require(not self.enabled or self.accepted_plan is not None,
                 "Highlights cannot be enabled without an accepted plan")
        for plan in (self.accepted_plan, self.previous_accepted_plan):
            if plan is not None:
                reviews = {r.event.event_id: r for r in plan.events}
                _require(all(reviews[t.event_id].status == "accepted" for t in plan.treatments),
                         "Accepted plans require accepted event reviews")
