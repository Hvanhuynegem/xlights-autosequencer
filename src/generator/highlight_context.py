"""Build replay identity from actual generator inputs, never a saved proposal."""
from __future__ import annotations

from dataclasses import fields, is_dataclass, dataclass
import hashlib
import json
import math
from numbers import Integral, Real
from pathlib import Path
import xml.etree.ElementTree as ET

from src.generator.highlights import HighlightCompileError, RECIPES, RECIPE_VERSION
from src.highlights.models import PlanContext


def _fail(code, message):
    raise HighlightCompileError(code, message)


def file_digest(path: Path, algorithm="sha256") -> str:
    try:
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, algorithm).hexdigest()
    except OSError as exc:
        raise HighlightCompileError('input_unavailable', 'A generation input file is unavailable') from exc


def _canonical(value, assets):
    if is_dataclass(value):
        return _canonical({f.name: getattr(value, f.name) for f in fields(value)}, assets)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key)
            if name in result:
                _fail('invalid_context', 'Ambiguous context mapping keys')
            if 'FILEPICKER' in name.upper() and isinstance(item, str) and item:
                path = Path(item)
                if path not in assets:
                    assets[path] = file_digest(path)
                result[name] = {'asset_sha256': assets[path]}
            else:
                result[name] = _canonical(item, assets)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical(v, assets) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(v, assets) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real) and math.isfinite(value):
        return float(value)
    _fail('invalid_context', f'Unsupported generation context value: {type(value).__name__}')


def _hash(value, assets) -> str:
    content = json.dumps(_canonical(value, assets), sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True)
class SourceSnapshot:
    source_sha256: str
    source_md5: str
    duration_ms: int
    layout_sha256: str


def capture_source(config, hierarchy) -> SourceSnapshot:
    """Measure the production audio clock and reject a mismatched cached analysis."""
    from src.analyzer.audio import load
    source_hash = file_digest(config.audio_path)
    source_md5 = file_digest(config.audio_path, 'md5')
    try:
        _, _, metadata = load(str(config.audio_path))
    except ValueError as exc:
        raise HighlightCompileError('source_unreadable', 'Audio cannot be decoded for highlight replay') from exc
    if hierarchy.source_hash.removeprefix('md5:') != source_md5:
        _fail('analysis_source_mismatch', 'Analysis belongs to different audio; reanalyze before highlighting')
    if hierarchy.duration_ms != metadata.duration_ms:
        _fail('analysis_duration_mismatch', 'Analysis duration differs from decoded audio; reanalyze')
    snapshot = SourceSnapshot(source_hash, source_md5, metadata.duration_ms, file_digest(config.layout_path))
    verify_source(config, snapshot)
    return snapshot


def verify_source(config, snapshot):
    if file_digest(config.audio_path) != snapshot.source_sha256:
        _fail('source_changed', 'Audio changed during highlight generation; reload and retry')
    if file_digest(config.layout_path) != snapshot.layout_sha256:
        _fail('layout_changed', 'Layout changed during highlight generation; reload and retry')


def build_context(config, hierarchy, baseline, layout, effect_library, theme_library, *, source, story=None):
    """Fingerprint loaded objects and actual placements after baseline assembly.

    Location-only paths, display metadata and diagnostics are excluded. Actual
    referenced asset bytes and all generated placements remain part of identity.
    """
    if layout is None:
        _fail('layout_unavailable', 'A parsed layout is required for highlight validation')
    assets = {}
    analysis = {f.name: getattr(hierarchy, f.name) for f in fields(hierarchy)
                if f.name not in {'source_file', 'relative_source_file', 'warnings', 'validation'}}
    config_data = {f.name: getattr(config, f.name) for f in fields(config)
                   if f.name not in {'audio_path', 'layout_path', 'output_dir', 'story_path', 'video_path',
                                     'title_override', 'artist_override', 'highlight_state',
                                     'capture_highlight_context', 'highlight_reviewed_sections'}}
    if config.video_path:
        config_data['video_sha256'] = file_digest(config.video_path)
    profile = {f.name: getattr(baseline.song_profile, f.name) for f in fields(baseline.song_profile)
               if f.name not in {'title', 'artist'}}
    baseline_data = {f.name: getattr(baseline, f.name) for f in fields(baseline)
                     if f.name not in {'song_profile', 'warnings', 'highlight_effects', 'highlight_context'}}
    baseline_data['song_profile'] = profile
    # The XML tree pins actual group membership and model settings. The parsed
    # props/groups additionally capture computed suitability/normalization.
    layout_data = {'xml': ET.canonicalize(ET.tostring(layout.raw_tree.getroot(), encoding='unicode'), strip_text=True),
                   'props': layout.props, 'generated_groups': baseline.layout_groups}
    context = PlanContext(
        source_sha256=source.source_sha256, duration_ms=source.duration_ms,
        analysis_revision=_hash(analysis, assets),
        sections_sha256=_hash({'effective': [a.section for a in baseline.sections],
                              'reviewed': config.highlight_reviewed_sections, 'story': story}, assets),
        layout_sha256=_hash(layout_data, assets),
        themes_sha256=_hash({'library': theme_library, 'overrides': config.theme_overrides,
                            'sliders': config.section_overrides}, assets),
        catalog_sha256=_hash({'effects': effect_library, 'recipes': RECIPES}, assets),
        baseline_sha256=_hash({'config': config_data, 'plan': baseline_data}, assets),
        variation_seed=config.variation_seed, recipe_version=RECIPE_VERSION,
    )
    verify_source(config, source)
    # Referenced assets must not change while the context was being assembled.
    if any(file_digest(path) != digest for path, digest in assets.items()):
        _fail('asset_changed', 'A referenced asset changed during highlight generation')
    return context
