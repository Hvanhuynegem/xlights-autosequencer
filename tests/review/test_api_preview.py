"""Real accepted-plan generation and freshness at the v1 preview boundary."""
from dataclasses import replace
import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from src.review.api.v1 import preview
from src.review.storage.assignments import load_session, save_full_session
from src.review.storage.highlights import highlight_path, load_highlights, save_highlights
from src.review.storage.library import load_library, save_library
from tests.review.test_highlight_acceptance import workflow, accepted, action, exported  # noqa: F401


@pytest.fixture(autouse=True)
def preview_setup(workflow, monkeypatch):
    monkeypatch.setattr(preview, 'get_committed_layout', lambda: {'xml_path': str(workflow[3])})
    with preview._cache_lock:
        preview._artifacts.clear()
    yield
    with preview._cache_lock:
        preview._artifacts.clear()


def post(client, workflow, **body):
    return client.post(workflow[1] + '/preview', json=body)


def unpack(client, response):
    downloaded = client.get(response.json['result']['artifact_url'])
    assert downloaded.status_code == 200, downloaded.json
    assert downloaded.headers['Cache-Control'] == 'no-store'
    with zipfile.ZipFile(io.BytesIO(downloaded.data)) as package:
        return {name: package.read(name) for name in package.namelist()}


def intervals(xsq, model):
    root = ET.fromstring(xsq)
    return [(int(e.get('startTime')), int(e.get('endTime')))
            for e in root.findall(f'./ElementEffects/Element[@name="{model}"]/EffectLayer/Effect')]


def test_public_preview_matches_enabled_export_and_baseline_choice(client, workflow, accepted):
    response = post(client, workflow, section_index=0)
    assert response.status_code == 200, response.json
    assert response.json['highlights'] is True and response.json['variation_seed'] == 42
    assert response.json['highlight_revision'] == accepted.revision
    package = unpack(client, response)
    assert package['layout.xml'] == workflow[3].read_bytes()
    full, _ = exported(client, workflow)
    assert intervals(package['preview.xsq'], 'MatrixCenter') == intervals(full, 'MatrixCenter')
    assert intervals(package['preview.xsq'], 'RadialSpinner') == [(10500, 10750)]
    baseline = post(client, workflow, highlights=False, variation_seed=42, section_index=0)
    assert baseline.status_code == 200 and baseline.json['highlights'] is False
    assert response.json['result']['placement_count'] == baseline.json['result']['placement_count'] + 3
    assert intervals(unpack(client, baseline)['preview.xsq'], 'MatrixCenter') == []
    assert load_highlights(workflow[0]) == accepted


def test_cache_hit_rebuilds_context_but_skips_serialization(client, workflow, accepted, monkeypatch):
    import src.generator.preview as generator_preview
    import src.analyzer.orchestrator as analyzer
    counts = {'analysis': 0, 'write': 0}
    analyze, write = analyzer.run_orchestrator, generator_preview.write_section_preview
    def counted_analyze(*a, **k):
        counts['analysis'] += 1
        return analyze(*a, **k)
    def counted_write(*a, **k):
        counts['write'] += 1
        return write(*a, **k)
    monkeypatch.setattr(analyzer, 'run_orchestrator', counted_analyze)
    monkeypatch.setattr(generator_preview, 'write_section_preview', counted_write)
    first = post(client, workflow)
    second = post(client, workflow)
    assert first.status_code == second.status_code == 200
    assert not first.json['cached'] and second.json['cached']
    assert first.json['preview_id'] == second.json['preview_id']
    unpack(client, second)
    assert counts == {'analysis': 3, 'write': 1}


@pytest.mark.parametrize('change', ['events', 'disable', 'session', 'layout', 'audio', 'preferences'])
def test_saved_changes_cannot_return_cached_enhanced_artifacts(client, workflow, accepted, change):
    first = post(client, workflow)
    assert first.status_code == 200
    state = load_highlights(workflow[0])
    if change == 'events':
        save_highlights(workflow[0], replace(state, events=(replace(state.events[0], note='edited'), *state.events[1:])),
                        expected_revision=state.revision)
    elif change == 'disable':
        assert action(client, workflow, 'disable').status_code == 200
    elif change == 'session':
        session = load_session(workflow[0]); session['sections'][0]['role'] = 'chorus'
        save_full_session(workflow[0], session)
    elif change == 'layout':
        workflow[3].write_text(workflow[3].read_text().replace('MatrixCenter', 'RenamedMatrix'))
    elif change == 'audio':
        workflow[2].audio_path.write_bytes(workflow[2].audio_path.read_bytes() + b'changed')
    else:
        library = load_library(); library['preferences']['genre'] = 'rock'; save_library(library)
    download = client.get(first.json['result']['artifact_url'])
    assert download.status_code == 409 and download.json['error']['code'] == 'stale_preview'
    second = post(client, workflow)
    if change == 'disable':
        assert second.status_code == 200 and not second.json['cached'] and not second.json['highlights']
    else:
        assert second.status_code == 409, second.json
        assert second.json['error']['code'] in {'stale_plan', 'analysis_source_mismatch'}


@pytest.mark.parametrize('enhanced', [False, True])
def test_catalog_changes_are_detected_even_when_request_identity_matches(client, workflow, accepted, monkeypatch, enhanced):
    from src.themes.library import load_theme_library
    options = {'highlights': enhanced, 'variation_seed': 42}
    first = post(client, workflow, **options)
    assert first.status_code == 200
    library = load_theme_library()
    library.themes['Quiet'].palette = ['#CC6600']
    monkeypatch.setattr('src.themes.library.load_theme_library', lambda **k: library)
    download = client.get(first.json['result']['artifact_url'])
    assert download.status_code == 409
    assert download.json['error']['code'] == ('stale_plan' if enhanced else 'stale_preview')
    second = post(client, workflow, **options)
    if enhanced:
        assert second.status_code == 409 and second.json['error']['code'] == 'stale_plan'
    else:
        assert second.status_code == 200 and not second.json['cached']
        assert second.json['preview_id'] != first.json['preview_id']


@pytest.mark.parametrize('change', ['session', 'state', 'layout', 'story'])
def test_edits_during_generation_prevent_cache_publication(client, workflow, accepted, monkeypatch, change):
    original = preview.run
    def changed(**kwargs):
        result = original(**kwargs)
        if change == 'session':
            save_full_session(workflow[0], {'sections': []})
        elif change == 'state':
            state = load_highlights(workflow[0])
            save_highlights(workflow[0], replace(state, enabled=False), expected_revision=state.revision)
        elif change == 'layout':
            workflow[3].write_bytes(workflow[3].read_bytes() + b'\n')
        else:
            workflow[2].audio_path.with_name(workflow[2].audio_path.stem + '_story.json').write_text('{}')
        return result
    monkeypatch.setattr(preview, 'run', changed)
    response = post(client, workflow)
    assert response.status_code == 409 and response.json['error']['code'] == 'generation_inputs_changed'
    assert not preview._artifacts


def test_explicit_baseline_bypasses_corrupt_state(client, workflow):
    path = highlight_path(workflow[0]); path.write_text('broken')
    assert post(client, workflow).json['error']['code'] == 'highlight_state_unreadable'
    response = post(client, workflow, highlights=False)
    assert response.status_code == 200, response.json
    unpack(client, response)
    assert path.read_text() == 'broken'


@pytest.mark.parametrize('body', [
    {'highlights': None}, {'highlights': 'yes'}, {'section_index': True}, {'section_index': -1},
    {'section_index': '0'}, {'variation_seed': True}, {'variation_seed': None}, {'variation_seed': 2**32},
    {'vocal_diarization': 1}, {'include_extra_timing': None}, {'context': {}},
])
def test_invalid_preview_options(client, workflow, body):
    response = post(client, workflow, **body)
    assert response.status_code == 400 and response.json['error']['code'] == 'invalid_preview'
    assert not preview._artifacts


def test_unavailable_and_invalid_section(client, workflow):
    assert post(client, workflow, highlights=True).json['error']['code'] == 'highlights_unavailable'
    response = post(client, workflow, section_index=99)
    assert response.status_code == 409 and response.json['error']['code'] == 'invalid_section'
    assert not preview._artifacts


def test_seed_and_writer_options_do_not_share_cached_output(client, workflow):
    first = post(client, workflow, variation_seed=42)
    second = post(client, workflow, variation_seed=43)
    third = post(client, workflow, variation_seed=43, include_extra_timing=False)
    assert all(r.status_code == 200 and not r.json['cached'] for r in (first, second, third))
    assert len({r.json['preview_id'] for r in (first, second, third)}) == 3


def test_explicit_seed_change_rejects_accepted_plan(client, workflow, accepted):
    response = post(client, workflow, variation_seed=43)
    assert response.status_code == 409 and response.json['error']['code'] == 'stale_plan'
    assert not preview._artifacts


def test_cache_eviction_and_wrong_song_download(client, workflow, monkeypatch):
    monkeypatch.setattr(preview, '_MAX_ENTRIES', 1)
    first = post(client, workflow, variation_seed=42)
    second = post(client, workflow, variation_seed=43)
    assert len(preview._artifacts) == 1
    assert client.get(first.json['result']['artifact_url']).status_code == 404
    wrong = f"/api/v1/songs/wrong/preview/{second.json['preview_id']}/download"
    assert client.get(wrong).status_code == 404
    unpack(client, second)


def test_oversized_preview_is_not_cached(client, workflow, monkeypatch):
    monkeypatch.setattr(preview, '_MAX_BYTES', 10)
    response = post(client, workflow)
    assert response.status_code == 413 and response.json['error']['code'] == 'preview_too_large'
    assert not preview._artifacts


def test_video_media_survives_runner_temporary_directory(client, workflow, tmp_path):
    workflow[3].write_text(workflow[3].read_text().replace('MatrixCenter', 'Matrix Video'))
    video = tmp_path / 'fixture.mp4'; video.write_bytes(b'fixture video bytes')
    library = load_library(); library['songs'][0]['video_path'] = str(video); save_library(library)
    response = post(client, workflow, highlights=False)
    assert response.status_code == 200, response.json
    package = unpack(client, response)
    assert package['fixture.mp4'] == video.read_bytes()
    assert intervals(package['preview.xsq'], 'Matrix Video')
    # Asset content identity matters even if its path and session do not change.
    video.write_bytes(b'changed video bytes')
    stale = client.get(response.json['result']['artifact_url'])
    assert stale.status_code == 409 and stale.json['error']['code'] == 'stale_preview'
    refreshed = post(client, workflow, highlights=False)
    assert refreshed.status_code == 200 and not refreshed.json['cached']
    assert unpack(client, refreshed)['fixture.mp4'] == video.read_bytes()


@pytest.mark.parametrize('change', ['baseline', 'lyrics', 'options'])
def test_runner_itself_rejects_cached_output_with_different_intent_or_writer_inputs(client, workflow, accepted, change):
    from src.evaluation.generator_runner import run, SectionPreviewRequest
    _, inputs, state, sections, _ = preview._snapshot(workflow[0], {})
    cached = run(**inputs, highlight_state=state, highlight_reviewed_sections=sections,
                 section_preview=SectionPreviewRequest(0))
    if change == 'baseline':
        state = None
    elif change == 'lyrics':
        inputs['lyrics'] = [{'t_ms': 0, 'duration_ms': 500, 'text': 'new words'}]
    else:
        inputs['include_extra_timing'] = False
    result = run(**inputs, highlight_state=state, highlight_reviewed_sections=sections,
                 section_preview=SectionPreviewRequest(0, cached))
    assert not result.reused
    if change == 'baseline':
        assert intervals(result.xsq, 'MatrixCenter') == []


def test_video_change_during_serialization_is_not_published(client, workflow, tmp_path, monkeypatch):
    import src.generator.preview as renderer
    video = tmp_path / 'fixture.mp4'; video.write_bytes(b'old')
    library = load_library(); library['songs'][0]['video_path'] = str(video); save_library(library)
    original = renderer.write_section_preview
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        video.write_bytes(b'new')
        return result
    monkeypatch.setattr(renderer, 'write_section_preview', changed)
    response = post(client, workflow, highlights=False)
    assert response.status_code == 409 and response.json['error']['code'] == 'generation_inputs_changed'
    assert not preview._artifacts
