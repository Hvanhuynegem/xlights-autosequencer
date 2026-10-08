"""Saved-intent forwarding and failure policy at the real export endpoint."""
from dataclasses import replace
from pathlib import Path

import pytest

from src.evaluation.generator_runner import GeneratorError
from src.review.api.v1 import export as routes
from src.review.storage.assignments import save_full_session
from src.review.storage.highlights import highlight_path, load_highlights, save_highlights
from src.review.storage.library import load_library, save_library
from tests.fixtures.highlights.synthetic import build_fixture


@pytest.fixture()
def ready(client, tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / 'audio')
    song_id = fixture.state.source_sha256[:16]
    song = {'song_id': song_id, 'title': 'Synthetic', 'artist': 'Fixture', 'status': 'themed',
            'source_paths': [str(fixture.audio_path)], 'duration_ms': 16000}
    library = load_library()
    library['songs'] = [song]
    save_library(library)
    session = {'sections': [{'start_ms': 0, 'end_ms': 16000}], 'assignments': []}
    save_full_session(song_id, session)
    layout = {'xml_path': str(Path('tests/fixtures/reference/layout.xml').resolve())}
    monkeypatch.setattr(routes, 'get_committed_layout', lambda: layout)
    class ImmediateThread:
        def __init__(self, *, target, args, kwargs=None, daemon=True):
            self.target, self.args, self.kwargs = target, args, kwargs or {}
        def start(self):
            self.target(*self.args, **self.kwargs)
    monkeypatch.setattr(routes.threading, 'Thread', ImmediateThread)
    state = replace(fixture.state, accepted_plan=fixture.plan, draft_plan=None, enabled=True)
    return song, fixture, session, state


def stored(ready):
    return save_highlights(ready[0]['song_id'], ready[3], expected_revision=0)


def request_export(client, ready, **body):
    return client.post(f"/api/v1/songs/{ready[0]['song_id']}/export", json=body)


def job(response):
    return routes._exports[response.get_json()['export_id']]


def test_enabled_snapshot_and_reviewed_sections_reach_runner(client, ready, monkeypatch):
    state = stored(ready)
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return b'<xsequence/>'
    monkeypatch.setattr('src.evaluation.generator_runner.run', run)
    response = request_export(client, ready, variation_seed=42)
    assert response.status_code == 202
    assert job(response).status == 'done'
    assert captured['highlight_state'] == state
    assert captured['highlight_reviewed_sections'] == ready[2]['sections']
    assert captured['variation_seed'] == 42


@pytest.mark.parametrize('mode', ['missing', 'disabled', 'explicit_baseline'])
def test_baseline_exports_do_not_forward_snapshots(client, ready, monkeypatch, mode):
    if mode == 'disabled':
        save_highlights(ready[0]['song_id'], replace(ready[3], enabled=False), expected_revision=0)
    elif mode == 'explicit_baseline': stored(ready)
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return b'<xsequence/>'
    monkeypatch.setattr('src.evaluation.generator_runner.run', run)
    response = request_export(client, ready, **({'highlights': False} if mode == 'explicit_baseline' else {}))
    assert response.status_code == 202 and job(response).status == 'done'
    assert 'highlight_state' not in captured and 'highlight_reviewed_sections' not in captured


def test_unreadable_state_requires_explicit_baseline_choice(client, ready, monkeypatch):
    path = highlight_path(ready[0]['song_id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('invalid')
    response = request_export(client, ready)
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'highlight_state_unreadable'
    monkeypatch.setattr('src.evaluation.generator_runner.run', lambda **k: b'<xsequence/>')
    assert job(request_export(client, ready, highlights=False)).status == 'done'
    assert path.read_text() == 'invalid'


def test_stale_plan_failure_has_code_and_never_publishes_partial_output(client, ready, monkeypatch):
    state = stored(ready)
    def run(**kwargs):
        raise GeneratorError('Changed inputs: context.themes_sha256', code='stale_plan')
    monkeypatch.setattr('src.evaluation.generator_runner.run', run)
    response = request_export(client, ready)
    assert job(response).status == 'failed' and job(response).output_path is None
    assert job(response).events[-1]['code'] == 'stale_plan'
    assert load_highlights(ready[0]['song_id']) == state


@pytest.mark.parametrize('changed', ['state', 'session', 'preferences'])
def test_edits_during_export_prevent_publication(client, ready, monkeypatch, changed):
    state = stored(ready)
    def run(**kwargs):
        if changed == 'state':
            save_highlights(ready[0]['song_id'], replace(state, enabled=False), expected_revision=1)
        elif changed == 'session':
            save_full_session(ready[0]['song_id'], {**ready[2], 'sections': []})
        else:
            lib = load_library(); lib['preferences']['genre'] = 'rock'; save_library(lib)
        return b'<xsequence/>'
    monkeypatch.setattr('src.evaluation.generator_runner.run', run)
    response = request_export(client, ready)
    assert job(response).status == 'failed' and job(response).output_path is None
    assert job(response).events[-1]['code'] == 'generation_inputs_changed'


def test_relocated_audio_uses_first_existing_path(client, ready, monkeypatch):
    library = load_library()
    library['songs'][0]['source_paths'].insert(0, '/missing/original.wav')
    save_library(library)
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return b'<xsequence/>'
    monkeypatch.setattr('src.evaluation.generator_runner.run', run)
    response = request_export(client, ready)
    assert job(response).status == 'done'
    assert captured['audio_path'] == str(ready[1].audio_path)


@pytest.mark.parametrize('choice,code,status', [('yes', 'invalid_highlights', 400),
                                               (None, 'invalid_highlights', 400),
                                               (True, 'highlights_unavailable', 409)])
def test_explicit_flag_validation(client, ready, choice, code, status):
    response = request_export(client, ready, highlights=choice)
    assert response.status_code == status
    assert response.get_json()['error']['code'] == code


def test_endpoint_runner_compiler_writer_and_package_replay(client, ready, monkeypatch):
    """Real generation with known analysis and an intentionally quiet fixture theme."""
    import hashlib
    import io
    import xml.etree.ElementTree as ET
    import zipfile
    from src.analyzer.result import HierarchyResult, TimingMark
    from src.generator.plan import build_plan as actual_build_plan
    from src.themes.library import ThemeLibrary
    from src.themes.models import Theme
    song, fixture, session, _ = ready
    hierarchy = HierarchyResult('2.7.0', str(fixture.audio_path),
                               hashlib.md5(fixture.audio_path.read_bytes()).hexdigest(), 16000, 120,
                               sections=[TimingMark(time_ms=0, confidence=1, label='verse', duration_ms=16000)])
    monkeypatch.setattr('src.analyzer.orchestrator.run_orchestrator', lambda *a, **k: hierarchy)
    quiet = Theme(name='Quiet', mood='structural', occasion='general', genre='any', intent='fixture',
                  layers=[], palette=['#3366CC', '#FFAA00'])
    monkeypatch.setattr('src.themes.library.load_theme_library', lambda **k: ThemeLibrary('1', {'Quiet': quiet}))
    captured = {}
    def capture(config, *args, **kwargs):
        config.capture_highlight_context = True
        config.highlight_reviewed_sections = session['sections']
        result = actual_build_plan(config, *args, **kwargs)
        captured['context'] = result.highlight_context
        return result
    monkeypatch.setattr('src.generator.plan.build_plan', capture)
    baseline_response = request_export(client, ready, variation_seed=42)
    assert job(baseline_response).status == 'done'
    baseline = Path(job(baseline_response).output_path).read_bytes()
    plan = replace(fixture.plan, context=captured['context'])
    state = save_highlights(song['song_id'], replace(fixture.state, draft_plan=None, accepted_plan=plan, enabled=True),
                            expected_revision=0)
    first = request_export(client, ready, variation_seed=42)
    assert job(first).status == 'done', job(first).events[-1]
    xsq = Path(job(first).output_path).read_bytes()
    assert xsq != baseline
    root = ET.fromstring(xsq)
    effects = root.findall('./ElementEffects/Element[@name="MatrixCenter"]/EffectLayer/Effect')
    assert [(p.get('startTime'), p.get('endTime')) for p in effects] == [('8275', '9725'), ('9725', '10125')]
    second = request_export(client, ready, variation_seed=42)
    assert Path(job(second).output_path).read_bytes() == xsq
    # Package the exact layout used by this enabled export even if configuration disappears later.
    name, expected_layout = job(second).highlight_layout_snapshot
    monkeypatch.setattr(routes, 'get_committed_layout', lambda: None)
    response = client.get(f"/api/v1/songs/{song['song_id']}/export/download-package")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.read(name) == expected_layout
        assert archive.read(Path(job(second).output_path).name) == xsq
    assert load_highlights(song['song_id']) == state
