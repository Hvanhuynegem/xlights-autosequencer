"""Real import → manual review → persistence, with no detector or provider."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import io
from pathlib import Path
from threading import Barrier

import pytest

from src.review.api.v1 import highlights as routes
from src.review.storage.assignments import save_full_session
from src.review.storage.highlights import highlight_path, load_highlights, save_highlights
from src.review.storage.library import load_library, save_library
from tests.fixtures.highlights.synthetic import build_fixture


@pytest.fixture()
def imported(client, tmp_path):
    fixture = build_fixture(tmp_path / "synthetic")
    response = client.post('/api/v1/import', data={
        'audio': (io.BytesIO(fixture.audio_path.read_bytes()), 'manual-highlight.wav'),
    }, content_type='multipart/form-data')
    assert response.status_code == 201
    song = response.get_json()['song']
    return song, fixture, f"/api/v1/songs/{song['song_id']}/highlights"


def payload(fixture, *, revision=0):
    return {'expected_revision': revision, 'source_sha256': fixture.state.source_sha256,
            'duration_ms': fixture.state.duration_ms,
            'events': [r.to_dict() for r in fixture.state.events]}


def test_draft_song_returns_measured_empty_state_without_creating_sidecar(client, imported):
    song, fixture, url = imported
    lib = load_library()
    lib['songs'][0]['duration_ms'] = 99999  # container metadata is not the timing clock
    save_library(lib)
    result = client.get(url)
    assert result.status_code == 200
    data = result.get_json()
    assert data['source'] == {'source_sha256': fixture.state.source_sha256, 'duration_ms': 16000}
    assert data['state']['revision'] == 0
    assert data['state']['events'] == [] and data['state']['enabled'] is False
    assert data['issues'] == [] and data['plan_validation']['status'] == 'no_plan'
    assert not highlight_path(song['song_id']).exists()


def test_review_lifecycle_survives_new_client_and_session_replacement(app, client, imported):
    song, fixture, url = imported
    body = payload(fixture)
    first = client.put(url, json=body)
    assert first.status_code == 200
    assert first.get_json()['state']['revision'] == 1
    body['expected_revision'] = 1
    body['events'][0].update(timing_override={'start_ms': 8291, 'peak_ms': 9751, 'end_ms': 10119}, locked=True)
    assert client.put(url, json=body).status_code == 200
    save_full_session(song['song_id'], {'sections': [], 'assignments': []})
    loaded = app.test_client().get(url).get_json()['state']
    assert loaded['revision'] == 2
    assert loaded['events'][0]['event']['timing']['start_ms'] == 8273
    assert loaded['events'][0]['timing_override']['start_ms'] == 8291
    assert loaded['events'][0]['locked'] is True
    for revision, status in ((2, 'dismissed'), (3, 'accepted')):
        body['expected_revision'] = revision
        body['events'][0]['status'] = status
        assert client.put(url, json=body).status_code == 200
    body.update(expected_revision=4, events=[])
    assert client.put(url, json=body).get_json()['state']['events'] == []
    assert load_highlights(song['song_id']).revision == 5


def test_old_revision_cannot_overwrite_newer_edits(client, imported):
    song, fixture, url = imported
    body = payload(fixture)
    assert client.put(url, json=body).status_code == 200
    before = highlight_path(song['song_id']).read_bytes()
    response = client.put(url, json=body)
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'revision_conflict'
    assert highlight_path(song['song_id']).read_bytes() == before


def test_two_concurrent_requests_have_exactly_one_winner(app, client, imported, monkeypatch):
    song, fixture, url = imported
    barrier = Barrier(2)
    original = routes.save_highlights
    def synchronized_save(*args, **kwargs):
        barrier.wait(timeout=10)
        return original(*args, **kwargs)
    monkeypatch.setattr(routes, 'save_highlights', synchronized_save)
    def put(note):
        body = payload(fixture)
        body['events'][0]['note'] = note
        with app.test_client() as tab:
            return tab.put(url, json=body).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(put, ['first', 'second']))
    assert sorted(codes) == [200, 409]
    assert load_highlights(song['song_id']).revision == 1


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(accepted_plan={}),
    lambda p: p.update(enabled=True),
    lambda p: p.update(expected_revision=True),
    lambda p: p.update(events='not-an-array'),
    lambda p: p.update(duration_ms=True),
    lambda p: p['events'].append(p['events'][0]),
    lambda p: p['events'][0]['event']['timing'].update(end_ms=20000),
    lambda p: p['events'][0]['event']['timing'].update(peak_ms=0),
    lambda p: p['events'][0]['event'].update(provenance='detector'),
    lambda p: p['events'][0].update(timing_override={'start_ms': -1, 'end_ms': 9999}),
])
def test_invalid_edits_and_plan_injection_do_not_create_state(client, imported, mutation):
    song, fixture, url = imported
    body = payload(fixture)
    mutation(body)
    response = client.put(url, json=body)
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'invalid_highlights'
    assert not highlight_path(song['song_id']).exists()


def test_original_event_evidence_is_immutable(client, imported):
    song, fixture, url = imported
    body = payload(fixture)
    assert client.put(url, json=body).status_code == 200
    body['expected_revision'] = 1
    body['events'][0]['event']['timing']['start_ms'] += 1
    assert client.put(url, json=body).status_code == 400
    assert load_highlights(song['song_id']).revision == 1


@pytest.mark.parametrize('field,value,code', [('source_sha256', 'b' * 64, 'source_changed'),
                                           ('duration_ms', 16001, 'duration_changed')])
def test_stale_client_source_is_rejected(client, imported, field, value, code):
    song, fixture, url = imported
    body = payload(fixture)
    body[field] = value
    if field == 'source_sha256':
        for review in body['events']:
            review['event'][field] = value
    response = client.put(url, json=body)
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == code
    assert not highlight_path(song['song_id']).exists()


def test_changed_audio_reports_saved_state_and_rejects_overwrite(client, imported, tmp_path):
    song, fixture, url = imported
    assert client.put(url, json=payload(fixture)).status_code == 200
    before = highlight_path(song['song_id']).read_bytes()
    replacement = build_fixture(tmp_path / 'replacement', 'rhythm_only')
    Path(song['source_paths'][0]).write_bytes(replacement.audio_path.read_bytes())
    data = client.get(url).get_json()
    assert data['state']['source_sha256'] == fixture.state.source_sha256
    assert data['source']['source_sha256'] == replacement.state.source_sha256
    assert data['issues'][0]['code'] == 'source_changed'
    assert client.put(url, json=payload(replacement, revision=1)).status_code == 409
    assert highlight_path(song['song_id']).read_bytes() == before


def test_source_change_between_validation_and_commit_does_not_save(client, imported, monkeypatch):
    song, fixture, url = imported
    original = routes._check_source
    calls = 0
    def changed_at_commit(song_id, source):
        nonlocal calls
        calls += 1
        if calls == 2:
            source.path.write_bytes(b'changed during edit')
        return original(song_id, source)
    monkeypatch.setattr(routes, '_check_source', changed_at_commit)
    response = client.put(url, json=payload(fixture))
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'source_changed'
    assert not highlight_path(song['song_id']).exists()


def test_rename_does_not_change_audio_identity(client, imported):
    song, fixture, url = imported
    assert client.put(url, json=payload(fixture)).status_code == 200
    source = Path(song['source_paths'][0])
    renamed = source.with_name('renamed.wav')
    source.rename(renamed)
    lib = load_library()
    lib['songs'][0]['source_paths'].append(str(renamed))
    save_library(lib)
    result = client.get(url).get_json()
    assert result['issues'] == []
    assert result['source']['source_sha256'] == fixture.state.source_sha256


def test_api_preserves_accepted_and_draft_plans_but_never_claims_validity(client, imported):
    song, fixture, url = imported
    state = replace(fixture.state, accepted_plan=fixture.plan, previous_accepted_plan=fixture.plan)
    saved = save_highlights(song['song_id'], state, expected_revision=0)
    body = payload(fixture, revision=1)
    body['events'][0]['note'] = 'Updated manual review'
    result = client.put(url, json=body)
    assert result.status_code == 200
    data = result.get_json()
    assert data['state']['accepted_plan'] == saved.accepted_plan.to_dict()
    assert data['state']['draft_plan'] == saved.draft_plan.to_dict()
    assert data['state']['previous_accepted_plan'] == saved.previous_accepted_plan.to_dict()
    assert data['state']['enabled'] is False
    assert data['plan_validation']['status'] == 'not_checked'
    assert {issue['plan'] for issue in data['issues']} == {'draft_plan', 'accepted_plan'}

    before = highlight_path(song['song_id']).read_bytes()
    body.update(expected_revision=2, accepted_plan=None)
    assert client.put(url, json=body).status_code == 400
    assert highlight_path(song['song_id']).read_bytes() == before


@pytest.mark.parametrize('case', ['near_end', 'rhythm_only'])
def test_boundary_and_empty_fixture_events_can_be_saved_without_analysis(client, tmp_path, case):
    fixture = build_fixture(tmp_path / case, case)
    song = client.post('/api/v1/import', data={
        'audio': (io.BytesIO(fixture.audio_path.read_bytes()), f'{case}.wav'),
    }, content_type='multipart/form-data').get_json()['song']
    url = f"/api/v1/songs/{song['song_id']}/highlights"
    response = client.put(url, json=payload(fixture))
    assert response.status_code == 200
    assert load_highlights(song['song_id']).events == fixture.state.events
    assert client.get(url).get_json()['issues'] == []


def test_corrupt_sidecar_is_reported_and_not_overwritten(client, imported):
    song, fixture, url = imported
    path = highlight_path(song['song_id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'broken')
    for response in (client.get(url), client.put(url, json=payload(fixture))):
        assert response.status_code == 409
        assert response.get_json()['error']['code'] == 'highlight_state_unreadable'
    assert path.read_bytes() == b'broken'


def test_missing_or_unreadable_audio_produces_actionable_error(client, imported):
    song, fixture, url = imported
    path = Path(song['source_paths'][0])
    path.unlink()
    response = client.get(url)
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'source_unavailable'
    path.write_bytes(b'not audio')
    response = client.get(url)
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'source_unreadable'


@pytest.mark.parametrize('raw', ['null', '[]', '{', '{"events":[],"events":[]}', '{"events":NaN}', ''])
def test_malformed_body_is_structured_error(client, imported, raw):
    song, fixture, url = imported
    response = client.put(url, data=raw, content_type='application/json')
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'invalid_highlights'
    assert not highlight_path(song['song_id']).exists()


def test_body_limit_and_media_type(client, imported):
    song, fixture, url = imported
    assert client.put(url, data='{}', content_type='text/plain').status_code == 400
    response = client.put(url, data=b' ' * (2 * 1024 * 1024 + 1), content_type='application/json')
    assert response.status_code == 413
    assert response.get_json()['error']['code'] == 'request_too_large'


def test_unknown_song_is_404(client):
    assert client.get('/api/v1/songs/missing/highlights').status_code == 404
    response = client.put('/api/v1/songs/missing/highlights', json={
        'expected_revision': 0, 'source_sha256': 'a' * 64, 'duration_ms': 1000, 'events': [],
    })
    assert response.status_code == 404
