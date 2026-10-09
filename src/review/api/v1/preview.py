"""Validated section previews for the v1 song/session/export workflow.

Synchronous by design: cached serialization still requires fresh baseline/context
validation. Legacy brief-based previews remain a separate API.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from threading import Lock
from uuid import uuid4
import zipfile

from flask import jsonify, send_file

from . import api_v1
from .generation_inputs import generation_inputs
from .highlights import _Issue, _json_body
from .layout import get_committed_layout
from src.evaluation.generator_runner import (
    GeneratedSectionPreview, GeneratorError, SectionPreviewRequest, _derive_seed, run,
)
from src.generator.highlight_context import file_digest
from src.generator.highlights import HighlightCompileError
from src.highlights.models import HighlightValidationError
from src.review.storage.assignments import load_session
from src.review.storage.highlights import HighlightStorageError, load_highlights
from src.review.storage.library import load_library


@dataclass(frozen=True)
class _Artifact:
    song_id: str
    options: dict
    request_key: str
    generated: GeneratedSectionPreview

    @property
    def size(self):
        return len(self.generated.xsq) + sum(len(data) for _, data in self.generated.assets)


_artifacts: OrderedDict[str, _Artifact] = OrderedDict()
_cache_lock = Lock()
_MAX_ENTRIES = 16
_MAX_BYTES = 64 * 1024 * 1024


def _options():
    body = _json_body()
    allowed = {'section_index', 'highlights', 'variation_seed', 'vocal_diarization', 'include_extra_timing'}
    if set(body) - allowed:
        raise HighlightValidationError('Unknown preview fields')
    for key in ('highlights', 'vocal_diarization', 'include_extra_timing'):
        if key in body and type(body[key]) is not bool:
            raise HighlightValidationError(f'{key} must be a boolean')
    index = body.get('section_index')
    if index is not None and (type(index) is not int or index < 0):
        raise HighlightValidationError('section_index must be a nonnegative integer or null')
    if 'variation_seed' in body:
        seed = body['variation_seed']
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise HighlightValidationError('variation_seed must be an integer between 0 and 2**32 - 1')
    return body


def _snapshot(song_id, options):
    library = load_library()
    song = next((s for s in library['songs'] if s['song_id'] == song_id), None)
    if song is None:
        raise _Issue('song_not_found', 'Song not found', 404)
    session = load_session(song_id)
    if song.get('status') != 'themed' or session is None:
        raise _Issue('incomplete_theming', 'Complete song theming before previewing')
    layout = get_committed_layout()
    if layout is None:
        raise _Issue('layout_missing', 'The committed xLights layout is unavailable')
    choice = options.get('highlights')
    state = load_highlights(song_id) if choice is not False else None
    enabled = state if state is not None and state.enabled else None
    if choice is True and enabled is None:
        raise _Issue('highlights_unavailable', 'No enabled accepted highlight plan is available')
    seed = options.get('variation_seed')
    if seed is None:
        seed = enabled.accepted_plan.context.variation_seed if enabled else _derive_seed(song_id)
    prefs = library.get('preferences') or {}
    inputs = generation_inputs(
        song, session, layout, genre=prefs.get('genre') or 'pop',
        occasion=prefs.get('occasion') or 'general', variation_seed=seed,
        vocal_diarization=options.get('vocal_diarization', True),
        include_extra_timing=options.get('include_extra_timing', True),
    )
    if not inputs['audio_path']:
        raise _Issue('source_unavailable', "Locate the song's audio before previewing")
    files = {key: file_digest(Path(inputs[key]))
             for key in ('audio_path', 'layout_path', 'story_path') if inputs[key]}
    identity = dict(song=song, session=session, inputs=inputs, files=files, options=options,
                    state=state.to_dict() if state else None)
    serialized = json.dumps(identity, default=str, sort_keys=True, separators=(',', ':'), allow_nan=False)
    key = hashlib.sha256(serialized.encode()).hexdigest()
    return key, inputs, enabled, session.get('sections', []), state.revision if state else None


def _generate(song_id, options, snapshot, cached=None):
    key, inputs, state, sections, _revision = snapshot
    generated = run(**inputs, highlight_state=state, highlight_reviewed_sections=sections,
                    section_preview=SectionPreviewRequest(options.get('section_index'), cached))
    if _snapshot(song_id, options)[0] != key:
        raise _Issue('generation_inputs_changed', 'Song inputs changed during preview; retry')
    return generated


def _errors(operation):
    try:
        return operation()
    except _Issue as exc:
        return jsonify(error=dict(code=exc.code, message=exc.message)), exc.status
    except HighlightStorageError:
        return jsonify(error=dict(code='highlight_state_unreadable',
                                  message='Saved highlights are unreadable; restore them or request highlights: false')), 409
    except HighlightValidationError as exc:
        return jsonify(error=dict(code='invalid_preview', message=str(exc))), 400
    except (GeneratorError, HighlightCompileError) as exc:
        return jsonify(error=dict(code=exc.code or 'generation_failed', message=str(exc))), 409


@api_v1.route('/songs/<song_id>/preview', methods=['POST'])
def create_preview(song_id):
    def create():
        options = _options()
        snapshot = _snapshot(song_id, options)
        key = snapshot[0]
        with _cache_lock:
            candidate = next(((ident, item) for ident, item in reversed(_artifacts.items())
                              if item.song_id == song_id and item.request_key == key), None)
        generated = _generate(song_id, options, snapshot, candidate[1].generated if candidate else None)
        artifact = _Artifact(song_id, dict(options), key, generated)
        if artifact.size > _MAX_BYTES:
            raise _Issue('preview_too_large', 'Preview package exceeds the 64 MiB cache limit', 413)
        ident = candidate[0] if candidate and generated.reused else uuid4().hex
        with _cache_lock:
            _artifacts[ident] = artifact
            _artifacts.move_to_end(ident)
            while len(_artifacts) > _MAX_ENTRIES or sum(a.size for a in _artifacts.values()) > _MAX_BYTES:
                _artifacts.popitem(last=False)
        result = generated.result.to_json()
        result['artifact_url'] = f'/api/v1/songs/{song_id}/preview/{ident}/download'
        return jsonify(preview_id=ident, cached=generated.reused, status='done', result=result,
                       variation_seed=snapshot[1]['variation_seed'], highlights=snapshot[2] is not None,
                       highlight_revision=snapshot[4]), 200
    return _errors(create)


@api_v1.route('/songs/<song_id>/preview/<preview_id>/download', methods=['GET'])
def download_preview(song_id, preview_id):
    def download():
        with _cache_lock:
            artifact = _artifacts.get(preview_id)
        if artifact is None or artifact.song_id != song_id:
            raise _Issue('preview_not_found', 'Preview expired or does not exist; generate it again', 404)
        snapshot = _snapshot(song_id, artifact.options)
        if snapshot[0] != artifact.request_key:
            raise _Issue('stale_preview', 'Song inputs changed; generate a new preview')
        generated = _generate(song_id, artifact.options, snapshot, artifact.generated)
        if not generated.reused:
            raise _Issue('stale_preview', 'Generation context changed; generate a new preview')
        package = io.BytesIO()
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('preview.xsq', generated.xsq)
            seen = {'preview.xsq'}
            for name, data in generated.assets:
                if name in seen:
                    raise _Issue('preview_asset_collision', 'Preview assets have duplicate filenames')
                seen.add(name)
                archive.writestr(name, data)
        package.seek(0)
        return send_file(package, as_attachment=True, download_name=f'preview_{song_id}.xsqz',
                         mimetype='application/zip', max_age=0)
    response = _errors(download)
    # Validation must run on every download rather than reusing a browser copy.
    from flask import make_response
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-store'
    return response
