"""Deterministic wrapper around the xLights sequence generator."""
from __future__ import annotations

import io
import hashlib
import json
from dataclasses import dataclass, replace
from threading import RLock
from uuid import uuid4
import random
import tempfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from src.highlights.models import HighlightPlan, HighlightState, HighlightTreatment, PlanContext
from src.generator.preview import PreviewResult


# Pipelines seed process-global random sources. Keep runner calls deterministic
# when draft preparation and background exports overlap in this backend.
_GENERATION_LOCK = RLock()


@dataclass(frozen=True)
class HighlightDraftRequest:
    state: HighlightState
    treatments: tuple[HighlightTreatment, ...]


@dataclass(frozen=True)
class GeneratedSectionPreview:
    context: PlanContext
    section_index: int
    result: PreviewResult
    xsq: bytes
    assets: tuple[tuple[str, bytes], ...] = ()
    reused: bool = False
    content_identity: str = ""


@dataclass(frozen=True)
class SectionPreviewRequest:
    section_index: int | None = None
    cached: GeneratedSectionPreview | None = None


class GeneratorError(Exception):
    """Raised when the generator pipeline fails."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def _derive_seed(audio_hash: str) -> int:
    """Derive a deterministic integer seed from an audio hash string.

    audio_hash format: "md5:3f4b..." — take first 8 hex chars after the prefix.
    """
    hex_part = audio_hash.removeprefix("md5:")[:8]
    return int(hex_part, 16)


def run(
    song_id: str,
    audio_path: Path | str,
    audio_hash: str,
    layout_path: Optional[Path] = None,
    theme_overrides: Optional[dict[int, str]] = None,
    section_overrides: Optional[dict[int, dict]] = None,
    lyrics: Optional[list[dict]] = None,
    words: Optional[list[dict]] = None,
    phonemes: Optional[list[dict]] = None,
    genre: str = "pop",
    occasion: str = "general",
    video_path: Optional[Path | str] = None,
    ignored_image_occurrences: Optional[list[dict]] = None,
    image_occurrence_overrides: Optional[list[dict]] = None,
    moving_head_keyword_motions: Optional[dict[str, str]] = None,
    shadow_text_occurrences: Optional[list[dict]] = None,
    image_manual_occurrences: Optional[list[dict]] = None,
    moving_head_manual_triggers: Optional[list[dict]] = None,
    include_extra_timing: bool = True,
    title_override: Optional[str] = None,
    artist_override: Optional[str] = None,
    vocal_diarization: bool = False,
    story_path: Optional[Path | str] = None,
    progress_cb: Optional[Callable[[str, float], None]] = None,
    variation_seed: Optional[int] = None,
    highlight_state: HighlightState | None = None,
    highlight_reviewed_sections: list[dict] | None = None,
    highlight_draft: HighlightDraftRequest | None = None,
    section_preview: SectionPreviewRequest | None = None,
) -> bytes | HighlightPlan | GeneratedSectionPreview:
    """Run the generator deterministically and return .xsq bytes.

    Args:
        song_id: The song identifier (used for logging / diagnostics).
        audio_path: Path to the source MP3 or WAV.
        audio_hash: "md5:..." hash string used to derive the seed.
        layout_path: Optional path to xlights_rgbeffects.xml layout.
                     If None, reads from settings.
        theme_overrides: Optional {section_index: theme_name} map — forces
                         specific sections to a caller-chosen theme instead
                         of the auto-selected one (see GenerationConfig).
        section_overrides: Optional {section_index: {"brightness", "hit_strength",
                         "dwell_time", "color_shift"}} map from the Theme screen's
                         per-section parameter sliders (GenerationConfig.section_overrides).
        lyrics: Optional synced-lyrics lines (``{t_ms, duration_ms, text}``)
                embedded as a "Lyrics" timing track in the output .xsq.
        words: Optional WhisperX word marks (``{label, start_ms, end_ms}``)
               embedded as a "Words" timing track; also drives Faces/Text
               placements on face-capable props and matrices.
        phonemes: Optional Papagayo phoneme marks (same shape) embedded as a
                  "Phonemes" timing track for the Faces effect.
        genre: Theme-selection genre hint (GenerationConfig.genre).
        occasion: Theme-selection occasion hint (GenerationConfig.occasion).
        video_path: Optional path to an imported video file — placed as a
                    Video effect on the largest matrix prop (GenerationConfig.video_path).
        ignored_image_occurrences: Optional lyric occurrences
                    ({"word", "start_ms"}) whose image-library match the
                    user unmapped on the Pictures screen — suppresses the
                    lyric-matched Pictures burst for that one occurrence
                    (GenerationConfig.ignored_image_occurrences).
        image_occurrence_overrides: Optional lyric occurrences
                    ({"word", "start_ms", "image_id"}) the user pinned to a
                    specific library image on the Pictures screen, distinct
                    from whatever that word's normal fuzzy-tag match
                    resolves to for its other occurrences
                    (GenerationConfig.image_occurrence_overrides).
        moving_head_keyword_motions: Optional {word: motion} map overriding
                    the default shake/spin/bounce Moving Head keyword
                    triggers with the user's own per-song additions/removals
                    from the review UI's Extras screen
                    (GenerationConfig.moving_head_keyword_motions).
        shadow_text_occurrences: Optional lyric occurrences
                    ({"word", "start_ms"}) the user tagged "Shadow" on the
                    Pictures screen — fires a two-layer Shadow Text effect
                    for that one occurrence
                    (GenerationConfig.shadow_text_occurrences).
        image_manual_occurrences: Optional manual Pictures bursts
                    ({"start_ms", "image_id"}) pinned to an explicit
                    timestamp from the Extras screen, independent of any
                    transcribed lyric word
                    (GenerationConfig.image_manual_occurrences).
        moving_head_manual_triggers: Optional manual Moving Head accents
                    ({"start_ms", "motion"}) pinned to an explicit timestamp
                    from the Extras screen, independent of any lyric keyword
                    (GenerationConfig.moving_head_manual_triggers).
        include_extra_timing: When False, the Chords and per-stem Onsets (...)
                    timing tracks are omitted from the .xsq (display-only
                    tracks; effect placement is unaffected).
        vocal_diarization: When True and ``words`` carries a confidently-
                    detected second voice (``speaker`` key from
                    ``src.analyzer.vocal_diarization``), routes it to a
                    second face prop and a "Lyrics - Backup" timing track
                    (GenerationConfig.vocal_diarization). Default False
                    pending broader real-song validation.
        story_path: Optional path to a ``<audio_stem>_story.json`` written
                    by the review/analyze flow (or the older CLI pipeline).
                    When present, section energies/roles/moods come from
                    this already-classified story instead of being
                    re-derived from raw, unclassified detector boundaries
                    (GenerationConfig.story_path) — keeps generation
                    consistent with what was reviewed on the Theme screen.
        variation_seed: Optional override for the per-song deterministic
                    seed (normally ``_derive_seed(audio_hash)``) that drives
                    every rotation-pool/jitter choice the generator makes.
                    Pass a different integer to get a different-looking
                    generation of the same song ("reroll"); omit to keep
                    today's default of always reproducing the same output
                    for the same song.

    Returns:
        Raw .xsq XML bytes. With highlight_draft, a server-created plan compiled
        and serialized against the real baseline instead. Draft preparation
        does not replay the state's previously accepted plan or persist changes.
        section_preview instead returns a GeneratedSectionPreview. Cached preview
        serialization is reused only after rebuilding and validating live context;
        accepted intent and writer-only inputs also participate in cache identity.

    Raises:
        GeneratorError: If the generator pipeline fails.
    """
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise GeneratorError(f"audio_path does not exist: {audio_path}")

    # Resolve layout path
    if layout_path is None:
        try:
            from src.settings import get_layout_path
            layout_path = get_layout_path()
        except Exception as exc:
            raise GeneratorError("No layout path available") from exc

    if layout_path is None:
        raise GeneratorError("No layout path available")

    layout_path = Path(layout_path)
    if not layout_path.exists():
        raise GeneratorError(f"layout_path does not exist: {layout_path}")

    if highlight_draft is not None and (highlight_state is not None or section_preview is not None):
        raise GeneratorError("Draft preparation cannot be combined with replay or preview")

    with _GENERATION_LOCK:
        # Seed all RNG sources deterministically from the audio hash, unless the
        # caller supplied an explicit reroll seed.
        seed = variation_seed if variation_seed is not None else _derive_seed(audio_hash)
        random.seed(seed)
        np.random.seed(seed % (2**32))

        try:
            highlight_kwargs = {}
            if highlight_state is not None and highlight_state.enabled:
                highlight_kwargs = {"highlight_state": highlight_state,
                                    "highlight_reviewed_sections": highlight_reviewed_sections}
            if highlight_draft is not None:
                highlight_kwargs = {"highlight_draft": highlight_draft,
                                    "highlight_reviewed_sections": highlight_reviewed_sections}
            if section_preview is not None:
                highlight_kwargs["section_preview"] = section_preview
                highlight_kwargs["highlight_reviewed_sections"] = highlight_reviewed_sections
            return _run_pipeline(audio_path, layout_path, seed, theme_overrides=theme_overrides,
                                  section_overrides=section_overrides,
                                  lyrics=lyrics, words=words, phonemes=phonemes,
                                  genre=genre, occasion=occasion, video_path=video_path,
                                  ignored_image_occurrences=ignored_image_occurrences,
                                  image_occurrence_overrides=image_occurrence_overrides,
                                  moving_head_keyword_motions=moving_head_keyword_motions,
                                  shadow_text_occurrences=shadow_text_occurrences,
                                  image_manual_occurrences=image_manual_occurrences,
                                  moving_head_manual_triggers=moving_head_manual_triggers,
                                  include_extra_timing=include_extra_timing,
                                  title_override=title_override, artist_override=artist_override,
                                  vocal_diarization=vocal_diarization,
                                  story_path=Path(story_path) if story_path else None,
                                  progress_cb=progress_cb, **highlight_kwargs)
        except GeneratorError:
            raise
        except Exception as exc:
            from src.generator.highlights import HighlightCompileError
            code = exc.code if isinstance(exc, HighlightCompileError) else None
            raise GeneratorError(f"Generator pipeline failed: {exc}", code=code) from exc


def _run_pipeline(
    audio_path: Path,
    layout_path: Path,
    seed: int,
    theme_overrides: Optional[dict[int, str]] = None,
    section_overrides: Optional[dict[int, dict]] = None,
    lyrics: Optional[list[dict]] = None,
    words: Optional[list[dict]] = None,
    phonemes: Optional[list[dict]] = None,
    genre: str = "pop",
    occasion: str = "general",
    video_path: Optional[Path | str] = None,
    ignored_image_occurrences: Optional[list[dict]] = None,
    image_occurrence_overrides: Optional[list[dict]] = None,
    moving_head_keyword_motions: Optional[dict[str, str]] = None,
    shadow_text_occurrences: Optional[list[dict]] = None,
    image_manual_occurrences: Optional[list[dict]] = None,
    moving_head_manual_triggers: Optional[list[dict]] = None,
    include_extra_timing: bool = True,
    title_override: Optional[str] = None,
    artist_override: Optional[str] = None,
    vocal_diarization: bool = False,
    story_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[str, float], None]] = None,
    highlight_state: HighlightState | None = None,
    highlight_reviewed_sections: list[dict] | None = None,
    highlight_draft: HighlightDraftRequest | None = None,
    section_preview: SectionPreviewRequest | None = None,
) -> bytes | HighlightPlan | GeneratedSectionPreview:
    """Execute the full generation pipeline and return .xsq bytes."""
    from src.analyzer.orchestrator import run_orchestrator
    from src.effects.library import load_effect_library
    from src.generator.models import GenerationConfig
    from src.generator.plan import build_plan
    from src.generator.xsq_writer import write_xsq
    from src.grouper.classifier import classify_props, normalize_coords
    from src.grouper.grouper import generate_groups
    from src.grouper.layout import parse_layout
    from src.themes.library import load_theme_library
    from src.variants.library import load_variant_library

    replay_files = {}
    if section_preview is not None or highlight_draft is not None or (highlight_state is not None and highlight_state.enabled):
        from src.generator.highlight_context import file_digest
        replay_paths = [audio_path, layout_path]
        if story_path is not None:
            replay_paths.append(Path(story_path))
        if video_path is not None:
            replay_paths.append(Path(video_path))
        replay_files = {path: file_digest(path) for path in replay_paths}

    # Run analysis (uses cache when available)
    hierarchy = run_orchestrator(str(audio_path), fresh=False)

    # Parse layout
    layout = parse_layout(layout_path)
    props = layout.props
    normalize_coords(props)
    classify_props(props)
    groups = generate_groups(props)

    # Load libraries
    effect_library = load_effect_library()
    variant_library = load_variant_library(effect_library=effect_library)
    theme_library = load_theme_library(
        effect_library=effect_library,
        variant_library=variant_library,
    )

    # Build GenerationConfig — use a temp dir as output_dir so no files leak
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = GenerationConfig(
            audio_path=audio_path,
            layout_path=layout_path,
            output_dir=Path(tmp_dir),
            genre=genre,
            occasion=occasion,
            theme_overrides=theme_overrides,
            section_overrides=section_overrides,
            # Per-song seed so theme lineups and effect alternation choices
            # differ between songs instead of repeating the section-index
            # pattern (identical output across songs otherwise).
            variation_seed=seed,
            # Faces placements reference the "Phonemes" timing track, so
            # only enable vocal placements when both mark sets exist.
            vocal_words=words if (words and phonemes) else None,
            vocal_diarization=vocal_diarization,
            story_path=story_path,
            video_path=video_path,
            ignored_image_occurrences=ignored_image_occurrences,
            image_occurrence_overrides=image_occurrence_overrides,
            moving_head_keyword_motions=(
                moving_head_keyword_motions
                if moving_head_keyword_motions is not None
                else {"shake": "shake", "spin": "spin", "bounce": "bounce"}
            ),
            shadow_text_occurrences=shadow_text_occurrences,
            image_manual_occurrences=image_manual_occurrences,
            moving_head_manual_triggers=moving_head_manual_triggers,
            title_override=title_override,
            artist_override=artist_override,
            highlight_state=highlight_state,
            capture_highlight_context=highlight_draft is not None or section_preview is not None,
            highlight_reviewed_sections=highlight_reviewed_sections,
        )

        # Re-seed after config construction (which may trigger path resolution calls)
        random.seed(seed)
        np.random.seed(seed % (2**32))

        # Build plan
        plan = build_plan(config, hierarchy, props, groups, effect_library, theme_library,
                          progress_cb=progress_cb, layout=layout)

        prepared = None
        if highlight_draft is not None:
            from src.generator.highlights import compile_highlights
            context = plan.highlight_context
            state = highlight_draft.state
            if (context.source_sha256 != state.source_sha256 or
                    context.duration_ms != state.duration_ms):
                raise GeneratorError("Saved events belong to different audio", code="source_changed")
            prepared = HighlightPlan(
                plan_id="plan_" + uuid4().hex, revision=1, context=context,
                events=state.events, treatments=highlight_draft.treatments,
            )
            plan.highlight_effects = compile_highlights(
                plan, prepared, context=context, events=state.events,
                layout=layout, effect_library=effect_library,
            )

        if section_preview is not None:
            from src.generator.preview import pick_representative_section, write_section_preview
            index = section_preview.section_index
            if index is None:
                index = pick_representative_section([a.section for a in plan.sections])
            if type(index) is not int or not 0 <= index < len(plan.sections):
                raise GeneratorError("Preview section does not exist", code="invalid_section")
            # Context describes the baseline. Accepted treatments and writer-only
            # inputs must also match, even for callers outside the HTTP cache.
            identity_data = dict(
                context=plan.highlight_context.to_dict(), index=index,
                highlights=highlight_state.to_dict() if highlight_state is not None and highlight_state.enabled else None,
                lyrics=lyrics, words=words, phonemes=phonemes,
                include_extra_timing=include_extra_timing, vocal_diarization=vocal_diarization,
                title=plan.song_profile.title, artist=plan.song_profile.artist,
                audio_name=audio_path.name, layout_name=layout_path.name,
            )
            identity = hashlib.sha256(json.dumps(identity_data, sort_keys=True, separators=(',', ':'),
                                                  allow_nan=False).encode()).hexdigest()
            cached = section_preview.cached
            if cached is not None and cached.content_identity == identity:
                if any(file_digest(path) != digest for path, digest in replay_files.items()):
                    raise GeneratorError("Inputs changed during preview validation", code="generation_inputs_changed")
                return replace(cached, reused=True)
            preview_path = Path(tmp_dir) / "preview.xsq"
            result = write_section_preview(
                plan, index, preview_path, hierarchy=hierarchy, audio_path=audio_path,
                lyrics=lyrics, words=words, phonemes=phonemes,
                include_extra_timing=include_extra_timing, vocal_diarization=vocal_diarization,
            )
            assets = tuple((p.name, p.read_bytes()) for p in sorted(Path(tmp_dir).iterdir())
                           if p.is_file() and p != preview_path)
            assets += ((layout_path.name, layout_path.read_bytes()),)
            if any(file_digest(path) != digest for path, digest in replay_files.items()):
                raise GeneratorError("Inputs changed during preview generation", code="generation_inputs_changed")
            return GeneratedSectionPreview(plan.highlight_context, index, result,
                                           preview_path.read_bytes(), assets, content_identity=identity)

        # Write .xsq to a temp file, then read back as bytes
        output_path = Path(tmp_dir) / "output.xsq"
        write_xsq(plan, output_path, hierarchy=hierarchy, audio_path=audio_path,
                  lyrics=lyrics, words=words, phonemes=phonemes,
                  include_extra_timing=include_extra_timing,
                  vocal_diarization=vocal_diarization)

        if replay_files and any(file_digest(path) != digest for path, digest in replay_files.items()):
            raise GeneratorError("Source or layout changed during highlight export; retry", code="generation_inputs_changed")

        return prepared if prepared is not None else output_path.read_bytes()
