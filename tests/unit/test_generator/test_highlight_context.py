"""Live context identity and actual build_plan replay, without audio detection."""
from dataclasses import replace
import hashlib
import shutil

import pytest

from src.analyzer.result import HierarchyResult, TimingMark
from src.effects.library import load_effect_library
from src.generator.highlight_context import build_context, capture_source
from src.generator.highlights import HighlightCompileError
from src.generator.models import GenerationConfig, EffectPlacement
from src.generator.plan import build_plan
from src.grouper.layout import parse_layout
from src.themes.library import ThemeLibrary
from src.themes.models import Theme, EffectLayer
from tests.fixtures.highlights.synthetic import build_fixture


@pytest.fixture()
def inputs(tmp_path):
    fixture = build_fixture(tmp_path / 'audio')
    path = tmp_path / 'layout.xml'
    shutil.copyfile('tests/fixtures/reference/layout.xml', path)
    layout = parse_layout(path)
    hierarchy = HierarchyResult('2.7.0', str(fixture.audio_path),
                                hashlib.md5(fixture.audio_path.read_bytes()).hexdigest(), 16000, 120,
                                sections=[TimingMark(time_ms=0, confidence=1, label='verse', duration_ms=16000)])
    effects = load_effect_library(custom_dir=tmp_path / 'empty')
    theme = Theme(name='Test', mood='structural', occasion='general', genre='any', intent='test',
                  layers=[EffectLayer(variant='On')], palette=['#3366CC', '#FFAA00'])
    themes = ThemeLibrary('1', {'Test': theme})
    config = GenerationConfig(fixture.audio_path, path, output_dir=tmp_path / 'output',
                              theme_overrides={0: 'Test'}, variation_seed=42,
                              picture_effects=False, moving_head_effects=False,
                              capture_highlight_context=True)
    return fixture, config, hierarchy, layout, effects, themes


def generate(inputs):
    fixture, config, hierarchy, layout, effects, themes = inputs
    # Intentionally no generated power groups: a sparse direct-generator caller.
    # Source decoding, plan assembly, fingerprints and recipe compilation are real.
    return build_plan(config, hierarchy, layout.props, [], effects, themes, layout=layout)


def accepted(inputs):
    baseline = generate(inputs)
    fixture, config, *_ = inputs
    plan = replace(fixture.plan, context=baseline.highlight_context)
    config.highlight_state = replace(fixture.state, accepted_plan=plan, enabled=True, draft_plan=None)
    config.capture_highlight_context = False
    return baseline, plan


def test_actual_build_plan_compiles_using_fresh_context(inputs):
    baseline, plan = accepted(inputs)
    replay = generate(inputs)
    assert replay.highlight_context == plan.context
    assert replay.highlight_effects['MatrixCenter'][0].start_ms == 8275
    assert replay.highlight_effects['RadialSpinner'][0].end_ms == 10750
    assert replay.sections == baseline.sections
    assert baseline.highlight_effects == {}
    assert generate(inputs) == replay


def test_disabled_path_does_not_hash_or_decode(inputs, monkeypatch):
    inputs[1].capture_highlight_context = False
    inputs[1].highlight_state = inputs[0].state  # disabled draft
    def forbidden(*a, **k):
        pytest.fail('Disabled generation must not compute highlight context')
    monkeypatch.setattr('src.generator.highlight_context.capture_source', forbidden)
    result = generate(inputs)
    assert result.highlight_context is None and result.highlight_effects == {}


@pytest.mark.parametrize('change', ['seed', 'theme', 'sliders', 'reviewed_sections', 'layout', 'analysis', 'catalog'])
def test_relevant_inputs_make_saved_plan_stale(inputs, change):
    accepted(inputs)
    fixture, config, hierarchy, layout, effects, themes = inputs
    if change == 'seed': config.variation_seed += 1
    elif change == 'theme': themes.themes['Test'].palette = ['#00FF00', '#FFFFFF']
    elif change == 'sliders': config.section_overrides = {0: {'brightness': .5}}
    elif change == 'reviewed_sections': config.highlight_reviewed_sections = [{'start_ms': 0, 'end_ms': 8000}]
    elif change == 'layout': layout.props[0].world_x += 1
    elif change == 'analysis': hierarchy.estimated_bpm += 1
    elif change == 'catalog': effects.effects['On'].description += ' revised'
    with pytest.raises(HighlightCompileError) as exc:
        generate(inputs)
    assert exc.value.code == 'stale_plan'
    assert config.highlight_state.accepted_plan is not None


def test_audio_rename_and_output_location_do_not_change_context(inputs, tmp_path):
    before = generate(inputs).highlight_context
    fixture, config, hierarchy, *_ = inputs
    renamed = fixture.audio_path.with_name('renamed.wav')
    fixture.audio_path.rename(renamed)
    config.audio_path = renamed
    config.output_dir = tmp_path / 'elsewhere'
    config.title_override = 'Changed display title'
    hierarchy.source_file = str(renamed)
    hierarchy.relative_source_file = 'renamed.wav'
    assert generate(inputs).highlight_context == before


def test_wrong_analysis_source_and_clock_are_rejected(inputs):
    inputs[2].source_hash = 'a' * 32
    with pytest.raises(HighlightCompileError) as exc:
        generate(inputs)
    assert exc.value.code == 'analysis_source_mismatch'
    inputs[2].source_hash = hashlib.md5(inputs[0].audio_path.read_bytes()).hexdigest()
    inputs[2].duration_ms += 1
    with pytest.raises(HighlightCompileError) as exc:
        generate(inputs)
    assert exc.value.code == 'analysis_duration_mismatch'


def test_source_or_layout_replaced_during_baseline_is_rejected(inputs):
    _, config, hierarchy, layout, effects, themes = inputs
    baseline = generate(inputs)
    source = capture_source(config, hierarchy)
    config.layout_path.write_text('<replacement/>')
    with pytest.raises(HighlightCompileError) as exc:
        build_context(config, hierarchy, baseline, layout, effects, themes, source=source)
    assert exc.value.code == 'layout_changed'


def test_referenced_asset_content_changes_baseline_fingerprint(inputs, tmp_path):
    _, config, hierarchy, layout, effects, themes = inputs
    baseline = generate(inputs)
    source = capture_source(config, hierarchy)
    asset = tmp_path / 'image.png'
    asset.write_bytes(b'image version 1')
    baseline.picture_effects = {'MatrixCenter': [EffectPlacement('Pictures', 'Pictures', 'MatrixCenter', 0, 1000,
        parameters={'E_FILEPICKER_Pictures_Filename': str(asset)})]}
    def context():
        return build_context(config, hierarchy, baseline, layout, effects, themes, source=source)
    first = context()
    asset.write_bytes(b'image version 2')
    assert context().baseline_sha256 != first.baseline_sha256
    asset.unlink()
    with pytest.raises(HighlightCompileError) as exc:
        context()
    assert exc.value.code == 'input_unavailable'
