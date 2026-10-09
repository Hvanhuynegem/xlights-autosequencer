"""Public reviewed events -> validated draft -> acceptance -> real XSQ export."""
from dataclasses import replace
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from src.analyzer.result import HierarchyResult, TimingMark
from src.review.api.v1 import export, highlights
from src.review.storage.assignments import load_session, save_full_session
from src.review.storage.highlights import highlight_path, load_highlights, save_highlights
from src.review.storage.library import load_library, save_library
from src.themes.library import ThemeLibrary
from src.themes.models import Theme
from tests.fixtures.highlights.synthetic import build_fixture


@pytest.fixture
def workflow(client, tmp_path, monkeypatch):
    fixture = build_fixture(tmp_path / 'audio')
    song_id = fixture.state.source_sha256[:16]
    song = dict(song_id=song_id, title='Synthetic', artist='Fixture', status='themed',
                source_paths=[str(fixture.audio_path)], duration_ms=16000)
    library = load_library()
    library['songs'] = [song]
    save_library(library)
    save_full_session(song_id, {'sections': [{'start_ms': 0, 'end_ms': 16000}], 'assignments': []})
    layout_path = tmp_path / 'layout.xml'
    layout_path.write_bytes(Path('tests/fixtures/reference/layout.xml').read_bytes())
    layout = {'xml_path': str(layout_path)}
    monkeypatch.setattr(export, 'get_committed_layout', lambda: layout)
    monkeypatch.setattr(highlights, 'get_committed_layout', lambda: layout)
    hierarchy = HierarchyResult(
        '2.7.0', str(fixture.audio_path), hashlib.md5(fixture.audio_path.read_bytes()).hexdigest(),
        16000, 120, sections=[TimingMark(time_ms=0, confidence=1, label='verse', duration_ms=16000)],
    )
    monkeypatch.setattr('src.analyzer.orchestrator.run_orchestrator', lambda *a, **k: hierarchy)
    quiet = Theme(name='Quiet', mood='structural', occasion='general', genre='any', intent='fixture',
                  layers=[], palette=['#3366CC', '#FFAA00'])
    monkeypatch.setattr('src.themes.library.load_theme_library', lambda **k: ThemeLibrary('1', {'Quiet': quiet}))

    class ImmediateThread:
        def __init__(self, *, target, args, kwargs=None, daemon=True):
            self.target, self.args, self.kwargs = target, args, kwargs or {}
        def start(self):
            self.target(*self.args, **self.kwargs)
    monkeypatch.setattr(export.threading, 'Thread', ImmediateThread)
    base = f'/api/v1/songs/{song_id}'
    response = client.put(base + '/highlights', json={
        'expected_revision': 0, 'source_sha256': fixture.state.source_sha256,
        'duration_ms': 16000, 'events': [e.to_dict() for e in fixture.state.events],
    })
    assert response.status_code == 200
    return song_id, base, fixture, layout_path


def action(client, workflow, name, **body):
    song_id, base, _, _ = workflow
    body.setdefault('expected_revision', load_highlights(song_id).revision)
    return client.post(base + '/highlights/' + name, json=body)


def draft(client, workflow, **body):
    body.setdefault('treatments', [t.to_dict() for t in workflow[2].plan.treatments])
    return action(client, workflow, 'draft', **body)


def accept(client, workflow):
    state = load_highlights(workflow[0])
    return action(client, workflow, 'accept', plan_id=state.draft_plan.plan_id)


@pytest.fixture
def accepted(client, workflow):
    response = draft(client, workflow, variation_seed=42)
    assert response.status_code == 200, response.json
    response = accept(client, workflow)
    assert response.status_code == 200, response.json
    return load_highlights(workflow[0])


def exported(client, workflow, **body):
    response = client.post(workflow[1] + '/export', json=body)
    assert response.status_code == 202, response.json
    job = export._exports[response.json['export_id']]
    assert job.status == 'done', job.events
    return Path(job.output_path).read_bytes(), response.json


def test_public_workflow_replays_seed_and_expected_placements(client, workflow, accepted):
    baseline, _ = exported(client, workflow, highlights=False, variation_seed=42)
    first, info = exported(client, workflow)
    second, _ = exported(client, workflow)
    assert info['variation_seed'] == 42
    assert first == second and first != baseline
    root = ET.fromstring(first)
    effects = root.findall('./ElementEffects/Element[@name="MatrixCenter"]/EffectLayer/Effect')
    assert [(p.get('startTime'), p.get('endTime')) for p in effects] == [('8275', '9725'), ('9725', '10125')]
    assert accepted.draft_plan is None and accepted.enabled
    assert load_highlights(workflow[0]) == accepted
    # A cheap GET explicitly does not promise that external inputs remain valid.
    assert client.get(workflow[1] + '/highlights').json['plan_validation']['status'] == 'not_checked'


def test_draft_reject_disable_enable_and_undo_preserve_intent(client, workflow, accepted):
    assert draft(client, workflow).status_code == 200
    state = load_highlights(workflow[0])
    assert state.accepted_plan == accepted.accepted_plan and state.enabled
    assert action(client, workflow, 'reject', plan_id=state.draft_plan.plan_id).status_code == 200
    assert load_highlights(workflow[0]).accepted_plan == accepted.accepted_plan
    assert action(client, workflow, 'disable').status_code == 200
    baseline, _ = exported(client, workflow, variation_seed=42)
    assert action(client, workflow, 'enable').status_code == 200
    assert exported(client, workflow)[0] != baseline
    treatments = [t.to_dict() for t in workflow[2].plan.treatments]
    treatments[0]['intensity'] = .3
    assert draft(client, workflow, treatments=treatments).status_code == 200
    assert accept(client, workflow).status_code == 200
    second = load_highlights(workflow[0])
    assert second.previous_accepted_plan == accepted.accepted_plan
    assert second.accepted_plan != accepted.accepted_plan
    assert action(client, workflow, 'undo').status_code == 200
    restored = load_highlights(workflow[0])
    assert restored.accepted_plan == accepted.accepted_plan
    assert restored.previous_accepted_plan == second.accepted_plan


@pytest.mark.parametrize('change', ['session', 'layout', 'audio', 'events'])
def test_acceptance_revalidates_and_preserves_saved_plans(client, workflow, accepted, change):
    assert draft(client, workflow).status_code == 200
    song_id = workflow[0]
    if change == 'session':
        session = load_session(song_id)
        session['sections'][0]['role'] = 'chorus'
        save_full_session(song_id, session)
    elif change == 'layout':
        workflow[3].write_text(workflow[3].read_text().replace('MatrixCenter', 'RenamedMatrix'))
    elif change == 'audio':
        workflow[2].audio_path.write_bytes(workflow[2].audio_path.read_bytes() + b'changed')
    else:
        state = load_highlights(song_id)
        events = (replace(state.events[0], note='new review'), *state.events[1:])
        save_highlights(song_id, replace(state, events=events), expected_revision=state.revision)
    before = highlight_path(song_id).read_bytes()
    response = accept(client, workflow)
    assert response.status_code == 409, response.json
    assert response.json['error']['code'] in {'stale_plan', 'analysis_source_mismatch'}
    assert highlight_path(song_id).read_bytes() == before


@pytest.mark.parametrize('action_name', ['enable', 'undo'])
def test_restore_actions_revalidate_current_inputs(client, workflow, accepted, action_name):
    if action_name == 'undo':
        assert draft(client, workflow).status_code == 200
        assert accept(client, workflow).status_code == 200
    else:
        assert action(client, workflow, 'disable').status_code == 200
    session = load_session(workflow[0]); session['sections'] = []
    save_full_session(workflow[0], session)
    before = highlight_path(workflow[0]).read_bytes()
    response = action(client, workflow, action_name)
    assert response.status_code == 409 and response.json['error']['code'] == 'stale_plan'
    assert highlight_path(workflow[0]).read_bytes() == before


@pytest.mark.parametrize('change', ['state', 'session', 'layout', 'story', 'preferences'])
def test_changes_during_generation_prevent_draft_commit(client, workflow, monkeypatch, change):
    from src.evaluation import generator_runner
    actual = generator_runner.run
    def changed(**kwargs):
        result = actual(**kwargs)
        if change == 'state':
            state = load_highlights(workflow[0])
            save_highlights(workflow[0], state, expected_revision=state.revision)
        elif change == 'session':
            save_full_session(workflow[0], {'sections': []})
        elif change == 'layout':
            workflow[3].write_bytes(workflow[3].read_bytes() + b'\n')
        elif change == 'story':
            workflow[2].audio_path.with_name(workflow[2].audio_path.stem + '_story.json').write_text('{}')
        else:
            library = load_library(); library['preferences']['genre'] = 'rock'; save_library(library)
        return result
    monkeypatch.setattr(generator_runner, 'run', changed)
    response = draft(client, workflow)
    assert response.status_code == 409, response.json
    assert response.json['error']['code'] == ('revision_conflict' if change == 'state' else 'generation_inputs_changed')
    state = load_highlights(workflow[0])
    assert state.draft_plan is None and state.accepted_plan is None


def test_invalid_treatment_does_not_destroy_accepted_plan(client, workflow, accepted):
    treatments = [t.to_dict() for t in workflow[2].plan.treatments]
    treatments[0]['targets'] = ['ImaginaryModel']
    response = draft(client, workflow, treatments=treatments)
    assert response.status_code == 409
    assert response.json['error']['code'] == 'unknown_target'
    assert load_highlights(workflow[0]) == accepted


def test_disable_and_reject_work_without_source_or_layout(client, workflow, accepted, monkeypatch):
    assert draft(client, workflow).status_code == 200
    plan_id = load_highlights(workflow[0]).draft_plan.plan_id
    workflow[2].audio_path.unlink()
    monkeypatch.setattr(highlights, 'get_committed_layout', lambda: None)
    assert action(client, workflow, 'disable').status_code == 200
    assert action(client, workflow, 'reject', plan_id=plan_id).status_code == 200
    state = load_highlights(workflow[0])
    assert not state.enabled and state.draft_plan is None
    assert state.accepted_plan == accepted.accepted_plan


@pytest.mark.parametrize('body', [
    {'expected_revision': True}, {'expected_revision': -1}, {'expected_revision': 1, 'context': {}},
    {'expected_revision': 1, 'variation_seed': True}, {'expected_revision': 1, 'variation_seed': -1},
    {'expected_revision': 1, 'variation_seed': 2**32}, {'expected_revision': 1, 'variation_seed': None},
    {'expected_revision': 1, 'treatments': []}, {'expected_revision': 1, 'treatments': {}},
])
def test_draft_rejects_invalid_contract_before_writing(client, workflow, body):
    body.setdefault('treatments', [t.to_dict() for t in workflow[2].plan.treatments])
    before = highlight_path(workflow[0]).read_bytes()
    response = client.post(workflow[1] + '/highlights/draft', json=body)
    assert response.status_code == 400
    assert highlight_path(workflow[0]).read_bytes() == before


@pytest.mark.parametrize('raw', ['null', '[]', '{', '{"expected_revision":1,"expected_revision":1}',
                                '{"expected_revision":NaN}'])
def test_action_json_is_strict(client, workflow, raw):
    response = client.post(workflow[1] + '/highlights/disable', data=raw, content_type='application/json')
    assert response.status_code == 400


def test_stale_revision_and_wrong_draft_id_cannot_accept(client, workflow):
    assert draft(client, workflow).status_code == 200
    state = load_highlights(workflow[0])
    response = action(client, workflow, 'accept', expected_revision=state.revision - 1, plan_id=state.draft_plan.plan_id)
    assert response.status_code == 409 and response.json['error']['code'] == 'revision_conflict'
    response = action(client, workflow, 'accept', plan_id='wrong')
    assert response.status_code == 409 and response.json['error']['code'] == 'draft_unavailable'
    assert load_highlights(workflow[0]) == state


def test_unreadable_state_is_never_overwritten(client, workflow):
    path = highlight_path(workflow[0]); path.write_text('broken')
    for name in ('draft', 'accept', 'reject', 'disable', 'enable', 'undo'):
        body = {'expected_revision': 1}
        if name == 'draft': body['treatments'] = [t.to_dict() for t in workflow[2].plan.treatments]
        if name in ('accept', 'reject'): body['plan_id'] = 'plan'
        response = client.post(workflow[1] + '/highlights/' + name, json=body)
        assert response.status_code == 409 and response.json['error']['code'] == 'highlight_state_unreadable'
    assert path.read_text() == 'broken'


def test_draft_and_export_forward_the_same_saved_options(client, workflow, monkeypatch):
    """A rich saved session must reach both flows, including story and extras."""
    session = load_session(workflow[0])
    session.update(
        assignments=[{'section_index': 0, 'theme_id': 'Chosen', 'overrides': {'brightness': .6}}],
        lyrics=[{'t_ms': 10, 'duration_ms': 100, 'text': 'Hi'}],
        words=[{'label': 'Hi', 'start_ms': 10, 'end_ms': 110}],
        phonemes=[{'label': 'AI', 'start_ms': 10, 'end_ms': 110}],
        ignored_image_occurrences=[{'word': 'Hi', 'start_ms': 10}],
        image_occurrence_overrides=[{'word': 'Hi', 'start_ms': 20, 'image_id': 'image'}],
        moving_head_keyword_motions={'Hi': 'spin'},
        shadow_text_occurrences=[{'word': 'Hi', 'start_ms': 30}],
        image_manual_occurrences=[{'start_ms': 40, 'image_id': 'image'}],
        moving_head_manual_triggers=[{'start_ms': 50, 'motion': 'spin'}],
    )
    save_full_session(workflow[0], session)
    library = load_library(); library['preferences'].update(genre='rock', occasion='halloween')
    library['songs'][0]['video_path'] = 'video.mp4'
    save_library(library)
    story = workflow[2].audio_path.with_name(workflow[2].audio_path.stem + '_story.json')
    story.write_text('{}')
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return workflow[2].plan if 'highlight_draft' in kwargs else b'<xsequence/>'
    monkeypatch.setattr('src.evaluation.generator_runner.run', run)
    assert draft(client, workflow, variation_seed=42).status_code == 200
    exported(client, workflow, variation_seed=42, highlights=False)
    draft_args = {k: v for k, v in calls[0].items() if not k.startswith('highlight_')}
    export_args = {k: v for k, v in calls[1].items() if k != 'progress_cb'}
    assert draft_args == export_args
    assert draft_args['story_path'] == story
    assert draft_args['theme_overrides'] == {0: 'Chosen'}
    assert draft_args['section_overrides'] == {0: {'brightness': .6}}
    assert draft_args['vocal_diarization'] is True
    assert draft_args['genre'] == 'rock' and draft_args['occasion'] == 'halloween'
    for name in ('lyrics', 'words', 'phonemes', 'ignored_image_occurrences', 'image_occurrence_overrides',
                 'moving_head_keyword_motions', 'shadow_text_occurrences', 'image_manual_occurrences',
                 'moving_head_manual_triggers'):
        assert draft_args[name] == session[name]
