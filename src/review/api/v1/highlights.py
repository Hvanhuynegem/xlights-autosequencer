"""Manual event review API. Plan acceptance requires the future recipe compiler.

PUT edits only reviewed events; it cannot replace or enable plan snapshots.
Audio identity and bounds are measured server-side, independent of analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from flask import jsonify, request

from . import api_v1
from src.highlights.models import EventReview, HighlightState, HighlightValidationError
from src.review.storage.highlights import (
    HighlightRevisionConflict, HighlightStorageError, load_highlights, save_highlights,
)
from src.review.storage.library import load_library

_MAX_BODY_BYTES = 2 * 1024 * 1024


class _Issue(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class _Source:
    path: Path
    source_sha256: str
    duration_ms: int

    def to_dict(self):
        # Local filesystem paths are implementation details, not API input.
        return {"source_sha256": self.source_sha256, "duration_ms": self.duration_ms}


def _source_path(song_id: str) -> Path:
    song = next((s for s in load_library()["songs"] if s["song_id"] == song_id), None)
    if song is None:
        raise _Issue("song_not_found", "Song not found", 404)
    path = next((Path(p) for p in song.get("source_paths", []) if Path(p).is_file()), None)
    if path is None:
        raise _Issue("source_unavailable", "Locate the song's audio before editing highlights")
    return path


def _digest(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise _Issue("source_unavailable", "The song's audio could not be read") from exc


def _read_source(song_id: str) -> _Source:
    from src.analyzer.audio import load

    path = _source_path(song_id)
    digest = _digest(path)
    try:
        _audio, _sr, metadata = load(str(path))
    except ValueError as exc:
        raise _Issue("source_unreadable", "The song's audio could not be decoded") from exc
    if metadata.duration_ms <= 0:
        raise _Issue("source_unreadable", "The song has no usable audio duration")
    source = _Source(path, digest, metadata.duration_ms)
    _check_source(song_id, source)
    return source


def _check_source(song_id: str, source: _Source) -> None:
    if _source_path(song_id) != source.path or _digest(source.path) != source.source_sha256:
        raise _Issue("source_changed", "Audio changed during this request; reload highlights")


def _state_issues(state: HighlightState, source: _Source) -> list[dict]:
    issues = []
    if state.source_sha256 != source.source_sha256:
        issues.append({"code": "source_changed", "message": "Saved highlights belong to different audio"})
    if state.duration_ms != source.duration_ms:
        issues.append({"code": "duration_changed", "message": "Audio duration differs from saved highlights"})
    current_events = {review.event.event_id: review for review in state.events}
    for name in ("draft_plan", "accepted_plan"):
        plan = getattr(state, name)
        if plan is not None:
            changed = [review.event.event_id for review in plan.events
                       if current_events.get(review.event.event_id) != review]
            if changed:
                issues.append({"code": "plan_events_changed", "plan": name, "event_ids": changed})
    return issues


def _response(state: HighlightState, source: _Source):
    has_plan = any((state.draft_plan, state.accepted_plan, state.previous_accepted_plan))
    return jsonify({
        "state": state.to_dict(),
        "source": source.to_dict(),
        "issues": _state_issues(state, source),
        "plan_validation": {
            "status": "unavailable" if has_plan else "no_plan",
            "reason": "Recipe compilation and generation-context validation are not available yet",
        },
    })


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HighlightValidationError("Duplicate JSON fields are not allowed")
        result[key] = value
    return result


def _invalid_constant(value):
    raise HighlightValidationError("Non-finite JSON numbers are not allowed")


def _body() -> dict:
    if not request.is_json:
        raise HighlightValidationError("Expected an application/json request")
    if request.content_length is not None and request.content_length > _MAX_BODY_BYTES:
        raise _Issue("request_too_large", "Highlight edits must fit within 2 MiB", 413)
    # Read at most the limit plus one even when Content-Length is absent.
    raw = request.stream.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        raise _Issue("request_too_large", "Highlight edits must fit within 2 MiB", 413)
    try:
        body = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise HighlightValidationError("Invalid highlight JSON") from exc
    required = {"expected_revision", "source_sha256", "duration_ms", "events"}
    if type(body) is not dict or set(body) != required:
        raise HighlightValidationError("Required fields: expected_revision, source_sha256, duration_ms, events")
    if type(body["expected_revision"]) is not int or body["expected_revision"] < 0:
        raise HighlightValidationError("expected_revision must be a nonnegative integer")
    if type(body["events"]) is not list or len(body["events"]) > 2000:
        raise HighlightValidationError("events must be an array with at most 2000 reviews")
    return body


def _put(song_id: str, source: _Source, state: HighlightState, body: dict):
    reviews = tuple(EventReview.from_dict(item) for item in body["events"])
    # Validate shape/bounds before comparing client identity with actual source.
    submitted = HighlightState(body["source_sha256"], body["duration_ms"], events=reviews)
    if submitted.source_sha256 != source.source_sha256 or state.source_sha256 != source.source_sha256:
        raise _Issue("source_changed", "Audio identity differs; reload and review the saved highlights")
    if submitted.duration_ms != source.duration_ms or state.duration_ms != source.duration_ms:
        raise _Issue("duration_changed", "Audio duration differs; reload and review the saved highlights")
    if body["expected_revision"] != state.revision:
        raise HighlightRevisionConflict("Highlights changed; reload before saving")
    originals = {review.event.event_id: review.event for review in state.events}
    for review in reviews:
        old = originals.get(review.event.event_id)
        if old is not None and old != review.event:
            raise HighlightValidationError("Original events are immutable; edit timing_override or review fields")
        if old is None and review.event.provenance != "manual":
            raise HighlightValidationError("New events must have manual provenance")
    candidate = replace(state, events=reviews)
    _check_source(song_id, source)
    saved = save_highlights(song_id, candidate, expected_revision=body["expected_revision"])
    return _response(saved, source), 200


def _handle(song_id: str, *, edit: bool):
    try:
        body = _body() if edit else None
        source = _read_source(song_id)
        state = load_highlights(song_id)
        if state is None:
            state = HighlightState(source.source_sha256, source.duration_ms)
        return _put(song_id, source, state, body) if edit else (_response(state, source), 200)
    except _Issue as exc:
        return jsonify({"error": {"code": exc.code, "message": exc.message}}), exc.status
    except HighlightRevisionConflict as exc:
        return jsonify({"error": {"code": "revision_conflict", "message": str(exc)}}), 409
    except HighlightStorageError:
        return jsonify({"error": {"code": "highlight_state_unreadable",
                                  "message": "Saved highlights are corrupt or unsupported; restore a valid sidecar"}}), 409
    except HighlightValidationError as exc:
        return jsonify({"error": {"code": "invalid_highlights", "message": str(exc)}}), 400


@api_v1.route("/songs/<song_id>/highlights", methods=["GET"])
def get_highlights(song_id: str):
    return _handle(song_id, edit=False)


@api_v1.route("/songs/<song_id>/highlights", methods=["PUT"])
def put_highlights(song_id: str):
    return _handle(song_id, edit=True)
