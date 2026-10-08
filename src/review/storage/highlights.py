"""Atomic, revision-checked highlight sidecars for the single-backend app.

Keeping this state separate from session.json preserves manual intent when
reanalysis replaces a session. This module validates data contracts only;
callers must perform layout/recipe validation before saving accepted plans.
Portable song/library bundle integration is a separate step.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock

from src.highlights.models import HighlightState, HighlightValidationError
from .paths import song_session_path


# Covers read/check/replace as one operation within one backend process. Atomic
# replacement also protects readers from partial files. Multiple writers in
# separate backend processes need interprocess locking before being supported.
_WRITE_LOCK = Lock()
_SONG_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class HighlightStorageError(ValueError):
    """The stored sidecar is corrupt or uses an unsupported schema."""


class HighlightRevisionConflict(ValueError):
    """A writer attempted to replace a newer revision of user intent."""


def highlight_path(song_id: str) -> Path:
    if not isinstance(song_id, str) or _SONG_ID.fullmatch(song_id) is None:
        raise HighlightValidationError("Invalid song_id")
    return song_session_path(song_id).with_name("highlights.json")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HighlightStorageError("Duplicate keys in highlight data")
        result[key] = value
    return result


def _invalid_constant(value):
    raise HighlightStorageError("Non-finite number in highlight data")


def load_highlights(song_id: str) -> HighlightState | None:
    """Return saved intent, or None for a song without a sidecar.

    Corruption is never treated as an empty state: doing so could erase the
    user's accepted plan on the next save.
    """
    path = highlight_path(song_id)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError as exc:
        raise HighlightStorageError("Highlight data is not valid UTF-8") from exc
    try:
        data = json.loads(content, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
        return HighlightState.from_dict(data)
    except (json.JSONDecodeError, HighlightValidationError) as exc:
        raise HighlightStorageError("Invalid or unsupported highlight data") from exc


def save_highlights(song_id: str, state: HighlightState, *, expected_revision: int) -> HighlightState:
    """Save a validated state only if its base revision still exists.

    New songs use revision 0. The stored result advances by one. A caller can
    keep a previous accepted plan while editing events; staleness must then be
    checked against current generation inputs before replaying that snapshot.
    """
    if type(expected_revision) is not int or expected_revision < 0:
        raise HighlightValidationError("expected_revision must be a nonnegative integer")
    if not isinstance(state, HighlightState):
        raise HighlightValidationError("state must be HighlightState")
    if state.revision != expected_revision:
        raise HighlightRevisionConflict("Submitted state is not based on expected_revision")
    path = highlight_path(song_id)
    with _WRITE_LOCK:
        current = load_highlights(song_id)
        current_revision = current.revision if current is not None else 0
        if current_revision != expected_revision:
            raise HighlightRevisionConflict(f"Expected revision {expected_revision}; current is {current_revision}")
        if current is not None and current.source_sha256 != state.source_sha256:
            raise HighlightValidationError("Cannot replace highlights with a different recording")
        saved = replace(state, revision=expected_revision + 1)
        data = json.dumps(saved.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".highlights-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return saved
