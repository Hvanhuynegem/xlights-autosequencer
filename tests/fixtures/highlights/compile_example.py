"""Reproducible compiler/XSQ example; does not invoke or enable application export.

Run: python -m tests.fixtures.highlights.compile_example --output <directory>
The intentionally simple authored baseline avoids ambiguous cross-group blends.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from src.effects.library import load_effect_library
from src.generator.highlights import compile_highlights
from src.generator.models import EffectPlacement, SectionAssignment, SectionEnergy, SequencePlan, SongProfile
from src.generator.xsq_writer import write_xsq
from src.grouper.layout import parse_layout
from src.highlights.models import HighlightPlan
from src.themes.models import Theme
from tests.fixtures.highlights.synthetic import build_fixture


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=sorted).encode()).hexdigest()


def compile_example(output: Path) -> dict:
    fixture = build_fixture(output)
    layout_path = Path(__file__).parents[1] / 'reference' / 'layout.xml'
    layout = parse_layout(layout_path)
    with tempfile.TemporaryDirectory() as empty:
        library = load_effect_library(custom_dir=empty)
    theme = Theme(name='Synthetic highlights', mood='structural', occasion='general', genre='any',
                  intent='Compiler example', layers=[], palette=['#3366CC'])
    assignment = SectionAssignment(SectionEnergy('verse', 0, 16000, 45, 'structural', 0), theme)
    for target in ('MatrixCenter', 'RadialSpinner'):
        assignment.group_effects[target] = [EffectPlacement(
            'Color Wash', library.effects['Color Wash'].xlights_id, target, 0, 16000,
            color_palette=['#112244'], parameters={'E_TEXTCTRL_ColorWash_Cycles': 1},
        )]
    baseline = SequencePlan(SongProfile('Synthetic highlights', 'Fixture', 'pop', 'general', 16000, 120),
                            [assignment], models=[p.name for p in layout.props])
    context = replace(fixture.plan.context,
                      sections_sha256=_digest([asdict(assignment.section)]),
                      themes_sha256=_digest(asdict(theme)),
                      catalog_sha256=_digest(asdict(library)),
                      baseline_sha256=_digest(asdict(baseline)))
    saved_plan = replace(fixture.plan, context=context)
    plan_path = output / 'compiled-input-plan.json'
    plan_path.write_text(json.dumps(saved_plan.to_dict(), indent=2) + '\n')
    (output / 'baseline-input.json').write_text(json.dumps(asdict(baseline), indent=2, default=sorted) + '\n')
    write_xsq(deepcopy(baseline), output / 'baseline.xsq', audio_path=fixture.audio_path)
    reloaded = HighlightPlan.from_dict(json.loads(plan_path.read_text()))
    placements = compile_highlights(baseline, reloaded, context=context, events=fixture.state.events,
                                    layout=layout, effect_library=library)
    enhanced = replace(baseline, highlight_effects=placements)
    write_xsq(deepcopy(enhanced), output / 'highlights.xsq', audio_path=fixture.audio_path)
    repeated = compile_highlights(baseline, reloaded, context=context, events=fixture.state.events,
                                  layout=layout, effect_library=library)
    write_xsq(replace(deepcopy(baseline), highlight_effects=repeated), output / 'highlights-repeat.xsq',
              audio_path=fixture.audio_path)
    assert (output / 'highlights.xsq').read_bytes() == (output / 'highlights-repeat.xsq').read_bytes()
    shutil.copyfile(layout_path, output / 'xlights_rgbeffects.xml')
    report = {
        'scope': 'Synthetic authored baseline -> compiler -> XSQ; runtime API/export and rendering not exercised',
        'source_sha256': fixture.state.source_sha256, 'duration_ms': 16000,
        'context': context.to_dict(), 'frame_interval_ms': baseline.frame_interval_ms,
        'placements': {target: [asdict(p) for p in effects] for target, effects in placements.items()},
        'xsq_sha256': {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                       for name in ('baseline.xsq', 'highlights.xsq', 'highlights-repeat.xsq')},
        'repeat_byte_identical': True, 'rendered': False,
    }
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compile_example(args.output)
    print(json.dumps({'output': str(args.output), 'xsq_sha256': result['xsq_sha256']}, indent=2))
