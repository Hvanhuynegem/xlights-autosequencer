"""Scoped plans preserve song content and the source intent used for replay."""
from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from src.generator.models import EffectPlacement
from src.generator.preview import write_section_preview, _SONG_EFFECT_COLLECTIONS
from tests.unit.test_generator.test_xsq_writer import _make_plan, TestScopedPreviewParams as _ScopedPlanFixture


def placement(name, start, end, **kwargs):
    return EffectPlacement(effect_name='On', xlights_id='On', model_or_group=name,
                           start_ms=start, end_ms=end, color_palette=['#FF0000'], **kwargs)


def test_short_section_retains_following_section_and_all_song_collections(tmp_path):
    plan = _make_plan()  # Two five-second sections: preview extends to 10 s.
    for name in _SONG_EFFECT_COLLECTIONS:
        setattr(plan, name, {name: [placement(name, 2500, 3500)]})
    original = deepcopy(plan)
    out = tmp_path / 'preview.xsq'
    result = write_section_preview(plan, 0, out)
    root = ET.parse(out)
    names = {e.get('name') for e in root.findall('./ElementEffects/Element')}
    assert {'Model1', 'Model2', *_SONG_EFFECT_COLLECTIONS} <= names
    assert result.window_ms == 10000 and result.placement_count == 9
    assert plan == original


def test_cropped_highlight_ramps_keep_boundary_brightness_and_source_plan(tmp_path):
    plan = _ScopedPlanFixture()._make_preview_plan()  # 45–60 seconds.
    first, last = 'E_TEXTCTRL_Eff_On_Start', 'E_TEXTCTRL_Eff_On_End'
    plan.highlight_effects = {'Glow': [
        placement('Glow', 44000, 46000, parameters={first: 0, last: 100}, layer=-1),
        placement('Glow', 59000, 61000, parameters={first: 100, last: 0}, layer=-1),
    ]}
    original = deepcopy(plan)
    out = tmp_path / 'preview.xsq'
    write_section_preview(plan, 0, out)
    root = ET.parse(out)
    effects = root.findall('./ElementEffects/Element[@name="Glow"]/EffectLayer/Effect')
    entries = root.findall('./EffectDB/Effect')
    assert [(e.get('startTime'), e.get('endTime')) for e in effects] == [('0', '1000'), ('14000', '15000')]
    ramps = [entries[int(e.get('ref'))].text for e in effects]
    assert first + '=50' in ramps[0] and last + '=100' in ramps[0]
    assert first + '=100' in ramps[1] and last + '=50' in ramps[1]
    assert plan == original


def test_video_path_rewrite_does_not_mutate_full_plan(tmp_path):
    plan = _make_plan()
    video = tmp_path / 'video.mp4'; video.write_bytes(b'fixture')
    effect = placement('VideoTarget', 0, 10000,
                       parameters={'E_FILEPICKERCTRL_Video_Filename': str(video)})
    effect.effect_name = effect.xlights_id = 'Video'
    plan.video_effects = {'VideoTarget': [effect]}
    original = deepcopy(plan)
    out = tmp_path / 'scoped' / 'preview.xsq'; out.parent.mkdir()
    write_section_preview(plan, 0, out)
    assert (out.parent / 'video.mp4').read_bytes() == video.read_bytes()
    assert plan == original


@pytest.mark.parametrize('diarized', [False, True])
def test_scoped_lyric_layers_are_bounded_without_changing_marks(tmp_path, diarized):
    plan = _ScopedPlanFixture()._make_preview_plan()
    words = [{'label': 'one', 'start_ms': 44000, 'end_ms': 46000, 'speaker': 0},
             {'label': 'two', 'start_ms': 59000, 'end_ms': 61000, 'speaker': 1 if diarized else 0},
             {'label': 'outside', 'start_ms': 62000, 'end_ms': 63000, 'speaker': 0}]
    phonemes = [{**w, 'label': 'AI'} for w in words]
    original = deepcopy((words, phonemes))
    out = tmp_path / 'preview.xsq'
    write_section_preview(plan, 0, out, words=words, phonemes=phonemes, vocal_diarization=diarized)
    root = ET.parse(out)
    tracks = root.findall('./ElementEffects/Element[@type="timing"]')
    assert tracks
    if diarized:
        assert any(t.get('name') == 'Lyrics - Backup' for t in tracks)
    for track in tracks:
        for e in track.findall('./EffectLayer/Effect'):
            assert 0 <= int(e.get('startTime')) < int(e.get('endTime')) <= 15000
            assert e.get('label') != 'outside'
    assert (words, phonemes) == original
