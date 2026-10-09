"""Manual event review and validated highlight-plan lifecycle API.

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
from src.highlights.models import EventReview, HighlightState, HighlightTreatment, HighlightValidationError
from src.evaluation.generator_runner import GeneratorError, HighlightDraftRequest
from src.generator.highlights import HighlightCompileError
from .generation_inputs import generation_inputs
from .layout import get_committed_layout
from src.review.storage.assignments import load_session
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
    path: Path | None
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


def _response(state: HighlightState, source: _Source | None, *, validated_plan=None):
    has_plan = any((state.draft_plan, state.accepted_plan, state.previous_accepted_plan))
    return jsonify({
        "state": state.to_dict(),
        "source": source.to_dict() if source else None,
        "issues": _state_issues(state, source) if source else [],
        "plan_validation": {
            "status": "valid" if validated_plan else "not_checked" if has_plan else "no_plan",
            "plan_id": validated_plan.plan_id if validated_plan else None,
            "reason": ("Compiled against current generation inputs" if validated_plan else
                       "Generation-context validation has not been run for this response"),
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


def _json_body() -> dict:
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
    if type(body) is not dict:
        raise HighlightValidationError("Expected a JSON object")
    return body


def _body() -> dict:
    body = _json_body()
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


def _handle(song_id: str, *, edit: bool = False, action: str | None = None):
    try:
        if action is not None:
            return _plan_action(song_id, action)
        body = _body() if edit else None
        source = _read_source(song_id)
        state = load_highlights(song_id)
        if state is None:
            state = HighlightState(source.source_sha256, source.duration_ms)
        return _put(song_id, source, state, body) if edit else (_response(state, source), 200)
    except _Issue as exc:
        return jsonify({"error": {"code": exc.code, "message": exc.message}}), exc.status
    except (GeneratorError, HighlightCompileError) as exc:
        return jsonify({"error": {"code": exc.code or "generation_failed", "message": str(exc)}}), 409
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


def _action_body(action: str) -> dict:
    body = _json_body()
    required = {"expected_revision"}
    optional = set()
    if action == "draft":
        required.add("treatments")
        optional.add("variation_seed")
    elif action in {"accept", "reject"}:
        required.add("plan_id")
    if not required <= set(body) or set(body) - required - optional:
        raise HighlightValidationError("Invalid fields for highlight " + action)
    revision = body["expected_revision"]
    if type(revision) is not int or revision < 0:
        raise HighlightValidationError("expected_revision must be a nonnegative integer")
    if "plan_id" in body and not isinstance(body["plan_id"], str):
        raise HighlightValidationError("plan_id must be a string")
    if "variation_seed" in body:
        seed = body["variation_seed"]
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise HighlightValidationError("variation_seed must be an integer between 0 and 2**32 - 1")
    if action == "draft":
        if type(body["treatments"]) is not list or not 1 <= len(body["treatments"]) <= 500:
            raise HighlightValidationError("treatments must contain 1–500 supported treatments")
        body["treatments"] = tuple(HighlightTreatment.from_dict(t) for t in body["treatments"])
    return body


def _validate_generation(song_id, state, song, library, *, treatments=None, plan=None, seed=None):
    """Generate using export's inputs, then guard publication of the saved intent."""
    from src.evaluation.generator_runner import _derive_seed, run
    from src.generator.highlight_context import file_digest

    session = load_session(song_id)
    if song.get("status") != "themed" or session is None:
        raise _Issue("incomplete_theming", "Complete song theming before preparing highlights")
    layout = get_committed_layout()
    if layout is None:
        raise _Issue("layout_missing", "The committed xLights layout is unavailable")
    prefs = library.get("preferences", {}) or {}
    if seed is None:
        seed = (plan.context.variation_seed if plan else
                state.accepted_plan.context.variation_seed if state.accepted_plan else _derive_seed(song_id))
    options = dict(genre=prefs.get("genre") or "pop", occasion=prefs.get("occasion") or "general",
                   variation_seed=seed)
    inputs = generation_inputs(song, session, layout, **options)
    if not inputs["audio_path"]:
        raise _Issue("source_unavailable", "Locate the song's audio before validating highlights")
    paths = [Path(inputs[k]) for k in ("audio_path", "layout_path", "story_path") if inputs[k]]
    files = {p: file_digest(p) for p in paths}
    kwargs = {"highlight_reviewed_sections": session.get("sections", [])}
    if treatments is not None:
        kwargs["highlight_draft"] = HighlightDraftRequest(state, treatments)
    else:
        kwargs["highlight_state"] = replace(state, accepted_plan=plan, enabled=True)
    result = run(**inputs, **kwargs)

    current_library = load_library()
    current_song = next((s for s in current_library["songs"] if s["song_id"] == song_id), None)
    current_prefs = current_library.get("preferences", {}) or {}
    if (load_session(song_id) != session or current_song != song or
            (current_prefs.get("genre") or "pop") != options["genre"] or
            (current_prefs.get("occasion") or "general") != options["occasion"] or
            get_committed_layout() != layout or
            generation_inputs(song, session, layout, **options) != inputs or
            any(file_digest(p) != digest for p, digest in files.items())):
        raise _Issue("generation_inputs_changed", "Song inputs changed during validation; retry")
    return result if treatments is not None else plan


def _plan_action(song_id: str, action: str):
    body = _action_body(action)
    library = load_library()
    song = next((s for s in library["songs"] if s["song_id"] == song_id), None)
    if song is None:
        raise _Issue("song_not_found", "Song not found", 404)
    state = load_highlights(song_id)
    if state is None:
        raise _Issue("highlights_unavailable", "Save reviewed events before preparing a highlight plan")
    if body["expected_revision"] != state.revision:
        raise HighlightRevisionConflict("Highlights changed; reload before saving")
    validated = None
    if action in {"accept", "reject"}:
        if state.draft_plan is None or state.draft_plan.plan_id != body["plan_id"]:
            raise _Issue("draft_unavailable", "This draft is no longer available; reload highlights")
    if action == "draft":
        validated = _validate_generation(song_id, state, song, library,
                                         treatments=body["treatments"], seed=body.get("variation_seed"))
        candidate = replace(state, draft_plan=validated)
    elif action == "reject":
        candidate = replace(state, draft_plan=None)
    elif action == "disable":
        candidate = replace(state, enabled=False)
    else:
        plan = {"accept": state.draft_plan, "enable": state.accepted_plan,
                "undo": state.previous_accepted_plan}[action]
        if plan is None:
            raise _Issue("plan_unavailable", "No saved plan is available for " + action)
        validated = _validate_generation(song_id, state, song, library, plan=plan)
        candidate = replace(state, accepted_plan=plan, enabled=True)
        if action in {"accept", "undo"}:
            candidate = replace(candidate, draft_plan=None, previous_accepted_plan=state.accepted_plan)
    saved = save_highlights(song_id, candidate, expected_revision=body["expected_revision"])
    # The generation path measured source identity; avoid decoding again after
    # committing a state (an unrelated decode failure must not mask a saved edit).
    source = _Source(None, saved.source_sha256, saved.duration_ms) if validated else None
    return _response(saved, source, validated_plan=validated), 200


@api_v1.route("/songs/<song_id>/highlights/draft", methods=["POST"])
def prepare_highlight_draft(song_id: str):
    return _handle(song_id, action="draft")


@api_v1.route("/songs/<song_id>/highlights/accept", methods=["POST"])
def accept_highlight_plan(song_id: str):
    return _handle(song_id, action="accept")


@api_v1.route("/songs/<song_id>/highlights/reject", methods=["POST"])
def reject_highlight_draft(song_id: str):
    return _handle(song_id, action="reject")


@api_v1.route("/songs/<song_id>/highlights/disable", methods=["POST"])
def disable_highlights(song_id: str):
    return _handle(song_id, action="disable")


@api_v1.route("/songs/<song_id>/highlights/enable", methods=["POST"])
def enable_highlights(song_id: str):
    return _handle(song_id, action="enable")


@api_v1.route("/songs/<song_id>/highlights/undo", methods=["POST"])
def undo_highlight_plan(song_id: str):
    return _handle(song_id, action="undo")
