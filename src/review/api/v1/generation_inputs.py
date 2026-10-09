"""Shared generation arguments for export and validated highlight actions."""
from pathlib import Path

from src.evaluation.generator_runner import GeneratorError


def generation_inputs(song, session, layout, *, genre="pop", occasion="general",
                      include_extra_timing=True, vocal_diarization=True,
                      variation_seed=None):
    """Assemble exactly the saved settings used by the public export path."""
    source_paths = song.get("source_paths") or []
    audio_path = next((p for p in source_paths if Path(p).is_file()), "")
    layout_xml_path = layout.get("xml_path")
    if not layout_xml_path:
        # Do NOT fall through to generator_runner's global-settings fallback —
        # that resolves whatever xLights layout happens to be configured
        # machine-wide, which silently generates against the wrong layout
        # instead of the repo-committed one (see bug-172 follow-up).
        raise GeneratorError(
            "layout/xlights_rgbeffects.xml is missing from the repo checkout."
        )

    # Honor the user's per-section theme picks from the Theme screen
    # instead of letting the generator auto-select every section.
    theme_overrides = {
        a["section_index"]: a["theme_id"]
        for a in session.get("assignments", [])
        if a.get("theme_id") and "section_index" in a
    }

    # Per-section Theme-screen slider values (brightness/hit_strength/
    # dwell_time/color_shift), saved via PUT .../assignments/<idx>.
    section_overrides = {
        a["section_index"]: a["overrides"]
        for a in session.get("assignments", [])
        if a.get("overrides") and "section_index" in a
    }

    # The already-classified section roles/energies (verse/chorus/...)
    # from the Theme screen -- written by analysis.py at analyze/commit
    # time as "<audio_stem>_story.json". Without this, build_plan()
    # silently re-derives unclassified section energies straight from
    # raw detector boundaries, and role labels are just the raw
    # segmentino/QM-segmenter letters (fixed 2026-07-21: this was the
    # actual root cause of "Sections" showing N1/A_1/qm_boundary
    # instead of verse/chorus in the exported .xsq).
    story_path = None
    if audio_path:
        candidate = Path(audio_path).parent / (Path(audio_path).stem + "_story.json")
        if candidate.exists():
            story_path = candidate

    lyrics = session.get("lyrics") or []
    words = session.get("words") or []
    phonemes = session.get("phonemes") or []
    return dict(
        song_id=song["song_id"],
        audio_path=audio_path,
        audio_hash=song["song_id"],
        layout_path=layout_xml_path,
        theme_overrides=theme_overrides,
        section_overrides=section_overrides,
        lyrics=lyrics or None,
        words=words or None,
        phonemes=phonemes or None,
        genre=genre,
        occasion=occasion,
        video_path=song.get("video_path"),
        ignored_image_occurrences=session.get("ignored_image_occurrences") or None,
        image_occurrence_overrides=session.get("image_occurrence_overrides") or None,
        moving_head_keyword_motions=session.get("moving_head_keyword_motions") or None,
        shadow_text_occurrences=session.get("shadow_text_occurrences") or None,
        image_manual_occurrences=session.get("image_manual_occurrences") or None,
        moving_head_manual_triggers=session.get("moving_head_manual_triggers") or None,
        include_extra_timing=include_extra_timing,
        title_override=song.get("title"),
        artist_override=song.get("artist"),
        vocal_diarization=vocal_diarization,
        story_path=story_path,
        variation_seed=variation_seed,
    )
