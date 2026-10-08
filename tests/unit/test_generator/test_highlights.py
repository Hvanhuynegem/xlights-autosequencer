"""Recipe compilation against the real catalog, layout and XSQ writer."""
from copy import deepcopy
from dataclasses import replace
import xml.etree.ElementTree as ET

import pytest

from src.effects.library import load_effect_library
from src.generator.highlights import HighlightCompileError, compile_highlights
from src.generator.models import EffectPlacement, SectionAssignment, SectionEnergy, SequencePlan, SongProfile
from src.generator.xsq_writer import write_xsq
from src.grouper.layout import parse_layout
from src.highlights.models import EventTiming
from src.themes.models import Theme
from tests.fixtures.highlights.synthetic import build_fixture


@pytest.fixture()
def setup(tmp_path):
    fixture = build_fixture(tmp_path / 'audio')
    layout = parse_layout('tests/fixtures/reference/layout.xml')
    library = load_effect_library(custom_dir=tmp_path / 'no-custom-effects')
    theme = Theme(name='Highlight test', mood='structural', occasion='general', genre='any',
                  intent='fixture', layers=[], palette=['#3366CC', '#FFAA00'])
    section = SectionAssignment(SectionEnergy('verse', 0, 16000, 45, 'structural', 0), theme)
    baseline = SequencePlan(SongProfile('Synthetic', 'Fixture', 'pop', 'general', 16000, 120),
                            [section], models=[p.name for p in layout.props])
    return fixture, baseline, layout, library


def compile_case(setup, plan=None, **kwargs):
    fixture, baseline, layout, library = setup
    plan = plan or fixture.plan
    return compile_highlights(baseline, plan, context=kwargs.pop('context', plan.context),
                              events=kwargs.pop('events', plan.events), layout=layout,
                              effect_library=library, **kwargs)


def background(target='MatrixCenter', effect='Color Wash', layer=0):
    return EffectPlacement(effect, 'eff_COLORWASH', target, 8000, 11000,
                           color_palette=['#AA00CC'], layer=layer)


def assert_rejected(setup, code, plan=None, **kwargs):
    before = deepcopy(setup[1])
    with pytest.raises(HighlightCompileError) as exc:
        compile_case(setup, plan, **kwargs)
    assert exc.value.code == code
    assert setup[1] == before


def test_shaped_wash_and_distinct_impact_preserve_source_and_baseline(setup):
    fixture, baseline, _, _ = setup
    before = deepcopy(baseline)
    result = compile_case(setup)
    rise, fall = result['MatrixCenter']
    impact, = result['RadialSpinner']
    assert [(p.start_ms, p.end_ms) for p in (rise, fall, impact)] == [(8275, 9725), (9725, 10125), (10500, 10750)]
    assert [(p.parameters['E_TEXTCTRL_Eff_On_Start'], p.parameters['E_TEXTCTRL_Eff_On_End'])
            for p in (rise, fall, impact)] == [(0, 70), (70, 0), (70, 0)]
    assert all(p.effect_name == 'On' and p.xlights_id == 'eff_ON' for p in (rise, fall, impact))
    assert all(p.color_palette == ['#3366CC'] and p.blend_mode == 'Additive' for p in (rise, fall, impact))
    assert baseline == before
    assert fixture.state.events[0].effective_timing == EventTiming(8273, 10113, 9719)
    assert compile_case(setup) == result


def test_same_target_front_layer_and_effective_palette_without_double_scaling(setup):
    section = setup[1].sections[0]
    section.brightness = .5
    section.group_effects['MatrixCenter'] = [background(layer=-3)]
    result = compile_case(setup)
    assert all(p.layer == -4 and p.color_palette == ['#AA00CC'] for p in result['MatrixCenter'])
    assert result['MatrixCenter'][0].parameters['E_TEXTCTRL_Eff_On_End'] == 70
    assert section.group_effects['MatrixCenter'][0].layer == -3


def test_anchor_pinning_shift_and_section_intensity(setup):
    section = setup[1].sections[0]
    section.anchor_palette = ['#FF0000']
    section.color_shift = 1 / 3
    section.brightness = .5
    section.hit_strength = .25
    result = compile_case(setup)
    assert result['MatrixCenter'][0].color_palette == ['#00FF00']
    assert result['MatrixCenter'][0].parameters['E_TEXTCTRL_Eff_On_End'] == 35
    assert result['RadialSpinner'][0].parameters['E_TEXTCTRL_Eff_On_Start'] == 35
    section.theme_overridden = True
    section.color_shift = 0
    assert compile_case(setup)['MatrixCenter'][0].color_palette == ['#3366CC']


@pytest.mark.parametrize('frame', [20, 25, 50])
def test_configured_frame_interval_reaches_xsq(setup, tmp_path, frame):
    baseline = setup[1]
    baseline.frame_interval_ms = frame
    baseline.highlight_effects = compile_case(setup)
    path = tmp_path / 'aligned.xsq'
    write_xsq(baseline, path)
    root = ET.parse(path).getroot()
    assert root.get('FixedPointTiming') == str(frame)
    assert root.findtext('head/sequenceTiming') == f'{frame} ms'
    for effect in root.findall('./ElementEffects/Element/EffectLayer/Effect'):
        assert int(effect.get('startTime')) % frame == 0
        assert int(effect.get('endTime')) % frame == 0


def test_half_frame_rounds_up_and_last_frame_stays_inside_audio(setup, tmp_path):
    fixture = build_fixture(tmp_path / 'end', 'near_end')
    setup[1].frame_interval_ms = 50
    result = compile_case(setup, fixture.plan)
    assert result['RadialSpinner'][0].end_ms == 16000
    event = replace(fixture.plan.events[0], timing_override=EventTiming(15725, 15725))
    plan = replace(fixture.plan, events=(event,))
    assert compile_case(setup, plan)['RadialSpinner'][0].start_ms == 15750
    duration = 15991
    setup[1].song_profile.duration_ms = duration
    event = replace(event, timing_override=EventTiming(15751, 15751))
    treatment = replace(plan.treatments[0], end_offset_ms=240)
    plan = replace(plan, context=replace(plan.context, duration_ms=duration), events=(event,), treatments=(treatment,))
    assert compile_case(setup, plan)['RadialSpinner'][0].end_ms == 15950


def test_empty_plan_is_byte_identical_baseline(setup, tmp_path):
    baseline = setup[1]
    baseline.sections[0].group_effects['MatrixCenter'] = [background()]
    before, after = tmp_path / 'before.xsq', tmp_path / 'after.xsq'
    write_xsq(baseline, before)
    empty = replace(setup[0].plan, events=(), treatments=())
    baseline.highlight_effects = compile_case(setup, empty)
    write_xsq(baseline, after)
    assert before.read_bytes() == after.read_bytes()


def test_real_writer_preserves_envelope_palette_and_frontmost_layer(setup, tmp_path):
    baseline = setup[1]
    baseline.sections[0].group_effects['MatrixCenter'] = [background()]
    baseline.highlight_effects = compile_case(setup)
    first, second = tmp_path / 'one.xsq', tmp_path / 'two.xsq'
    write_xsq(baseline, first)
    write_xsq(baseline, second)
    assert first.read_bytes() == second.read_bytes()
    root = ET.parse(first).getroot()
    layers = root.find('./ElementEffects/Element[@name="MatrixCenter"]').findall('EffectLayer')
    assert [p.get('name') for p in layers[0]] == ['On', 'On']
    assert layers[1][0].get('name') == 'Color Wash'
    db = [node.text for node in root.findall('./EffectDB/Effect')]
    rise, fall = (db[int(node.get('ref'))] for node in layers[0])
    assert 'E_TEXTCTRL_Eff_On_Start=0' in rise and 'E_TEXTCTRL_Eff_On_End=70' in rise
    assert 'E_TEXTCTRL_Eff_On_Start=70' in fall and 'E_TEXTCTRL_Eff_On_End=0' in fall
    assert 'T_CHOICE_LayerMethod=Additive' in rise
    assert 'T_TEXTCTRL_Fadein=' not in rise


@pytest.mark.parametrize('change,code', [
    ({'layout_sha256': '9' * 64}, 'stale_plan'),
    ({'variation_seed': 123}, 'stale_plan'),
])
def test_changed_inputs_reject_snapshot(setup, change, code):
    assert_rejected(setup, code, context=replace(setup[0].plan.context, **change))


def test_current_event_edits_require_new_snapshot(setup):
    events = (replace(setup[0].plan.events[0], note='changed'), setup[0].plan.events[1])
    assert_rejected(setup, 'stale_plan', events=events)


def test_missing_peak_and_collapsed_peak_are_rejected(setup):
    plan = setup[0].plan
    for timing, code in [(EventTiming(8273, 10113), 'missing_peak'),
                         (EventTiming(8273, 10113, 8274), 'invalid_peak')]:
        reviews = (replace(plan.events[0], timing_override=timing), plan.events[1])
        assert_rejected(setup, code, replace(plan, events=reviews))


def test_wrong_event_kind_or_candidate_is_rejected(setup):
    plan = setup[0].plan
    for review in (replace(plan.events[0], status='candidate'),
                   replace(plan.events[0], event=replace(plan.events[0].event, kind='fill'))):
        assert_rejected(setup, 'event_ineligible', replace(plan, events=(review, plan.events[1])))


@pytest.mark.parametrize('target,code', [('Missing', 'unknown_target'), ('All Props', 'highlight_collision')])
def test_unknown_target_and_overlapping_physical_targets(setup, target, code):
    plan = setup[0].plan
    targets = (target,) if target == 'Missing' else ('MatrixCenter', 'All Props')
    treatment = replace(plan.treatments[0], targets=targets)
    assert_rejected(setup, code, replace(plan, treatments=(treatment,)))


def test_nested_groups_detect_protected_shared_membership(setup):
    ET.SubElement(setup[2].raw_tree.getroot().find('modelGroups'), 'modelGroup',
                  name='Nested', models='All Props')
    setup[1].vocal_effects['Nested'] = [background('Nested', 'Faces')]
    assert_rejected(setup, 'protected_content')


@pytest.mark.parametrize('collection', ['vocal_effects', 'video_effects', 'crash_effects', 'picture_effects',
                                       'shadow_text_effects', 'moving_head_effects', 'highlight_effects'])
def test_song_level_protected_content(setup, collection):
    getattr(setup[1], collection)['MatrixCenter'] = [background()]
    assert_rejected(setup, 'protected_content')


def test_fade_mask_and_ordinary_cross_group_compositing_are_rejected(setup):
    p = background('All Props', 'On')
    setup[1].sections[0].group_effects['All Props'] = [p]
    assert_rejected(setup, 'ambiguous_composition')
    p.parameters['T_CHOICE_LayerMethod'] = 'Min'
    assert_rejected(setup, 'protected_content')


def test_cyclic_group_is_actionable(setup):
    group = setup[2].raw_tree.getroot().find('.//modelGroup')
    group.set('models', 'All Props')
    plan = setup[0].plan
    treatment = replace(plan.treatments[0], targets=('All Props',))
    assert_rejected(setup, 'cyclic_group', replace(plan, treatments=(treatment,)))


@pytest.mark.parametrize('display_as', ['DmxMovingHeadAdv', 'Unknown Device'])
def test_unsupported_models_never_receive_rgb_effects(setup, display_as):
    next(p for p in setup[2].props if p.name == 'MatrixCenter').display_as = display_as
    assert_rejected(setup, 'target_ineligible')


def test_dedicated_singing_model_is_protected_even_without_active_faces(setup):
    next(p for p in setup[2].props if p.name == 'MatrixCenter').face_definitions = ['mouth']
    assert_rejected(setup, 'target_ineligible')


def test_section_boundaries_and_zero_brightness(setup):
    setup[1].sections[0].section.end_ms = 9000
    assert_rejected(setup, 'section_boundary')
    setup[1].sections[0].section.end_ms = 16000
    setup[1].sections[0].brightness = 0
    assert_rejected(setup, 'invisible_treatment')


def test_missing_or_changed_catalog_fails_whole_proposal(setup):
    library = setup[3]
    effect = library.effects.pop('On')
    assert_rejected(setup, 'recipe_unavailable')
    library.effects['On'] = effect
    next(p for p in effect.parameters if p.name == 'Eff_On_End').max = 10
    assert_rejected(setup, 'recipe_unavailable')


def test_rejected_later_treatment_leaves_baseline_and_intent_untouched(setup):
    plan = setup[0].plan
    before = plan.to_dict()
    bad = replace(plan, treatments=(plan.treatments[0], replace(plan.treatments[1], targets=('Missing',))))
    assert_rejected(setup, 'unknown_target', bad)
    assert plan.to_dict() == before
    assert setup[1].highlight_effects == {}


@pytest.mark.parametrize('frame', [0, -1, True, 25.5])
def test_invalid_frame_interval(setup, tmp_path, frame):
    setup[1].frame_interval_ms = frame
    assert_rejected(setup, 'invalid_frame_interval')
    with pytest.raises(ValueError, match='frame_interval_ms'):
        write_xsq(setup[1], tmp_path / 'invalid.xsq')


def test_off_grid_baseline_is_not_silently_retimed(setup):
    setup[1].frame_interval_ms = 20
    placement = background()
    placement.start_ms = 8025
    setup[1].sections[0].group_effects['MatrixCenter'] = [placement]
    assert_rejected(setup, 'baseline_timing')


def test_example_reloads_saved_plan_and_replays_identical_xsq(tmp_path):
    from tests.fixtures.highlights.compile_example import compile_example
    report = compile_example(tmp_path)
    assert report['repeat_byte_identical'] is True
    assert report['rendered'] is False
    assert report['xsq_sha256']['baseline.xsq'] != report['xsq_sha256']['highlights.xsq']
    assert len(report['placements']['MatrixCenter']) == 2
