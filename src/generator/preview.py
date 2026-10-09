"""Preview render — short-section .xsq generation for the Preview tab.

Implements:
  - CancelToken / PreviewCancelled — cooperative cancellation primitive
  - PreviewJob / PreviewResult — data types for the async job surface
  - _canonical_brief_hash — deterministic hash for Brief objects
  - _PreviewCache — LRU cache keyed by (song_hash, section_index, brief_hash)
  - _clamp_window_ms — clamp section window to 10-20s
  - pick_representative_section — auto-select the best section to preview
  - run_section_preview — scoped generator run for a single section
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Cancellation primitive ─────────────────────────────────────────────────


class PreviewCancelled(Exception):
    """Raised inside a preview thread when its CancelToken has been fired."""


class CancelToken:
    """Thread-safe cooperative cancellation flag.

    The dispatcher calls cancel() on supersede; the preview thread calls
    raise_if_cancelled() at pipeline stage boundaries.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Signal cancellation to the preview thread."""
        self._event.set()

    def is_cancelled(self) -> bool:
        """Return True if cancel() has been called."""
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise PreviewCancelled if the token has been cancelled."""
        if self._event.is_set():
            raise PreviewCancelled()


# ── Data types ─────────────────────────────────────────────────────────────


@dataclass
class PreviewResult:
    """Payload returned by the status GET when status == 'done'."""

    section: dict          # {label, start_ms, end_ms, energy_score, role}
    window_ms: int         # Previewed window length (10000-20000)
    theme_name: str        # Theme selected for this section
    placement_count: int   # Total EffectPlacement objects in the artifact
    artifact_url: str      # "/api/song/<hash>/preview/<job_id>/download"
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "section": self.section,
            "window_ms": self.window_ms,
            "theme_name": self.theme_name,
            "placement_count": self.placement_count,
            "artifact_url": self.artifact_url,
            "warnings": self.warnings,
        }


@dataclass
class PreviewJob:
    """State for a single preview render job."""

    job_id: str
    song_hash: str
    section_index: int
    brief_snapshot: dict[str, Any]
    brief_hash: str
    status: str                      # pending / running / done / failed / cancelled
    started_at: float
    completed_at: Optional[float] = None
    artifact_path: Optional[Path] = None
    error_message: Optional[str] = None
    cancel_token: CancelToken = field(default_factory=CancelToken)
    result: Optional[PreviewResult] = None
    warnings: list[str] = field(default_factory=list)


# ── Brief hashing ──────────────────────────────────────────────────────────


def _canonical_brief_hash(brief: dict) -> str:
    """Return the first 16 hex chars of sha256(canonical-JSON(brief)).

    Canonical serialization sorts keys so logically equal briefs with
    different key ordering produce the same hash.
    """
    canonical = json.dumps(brief, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ── LRU cache ──────────────────────────────────────────────────────────────

CacheKey = tuple[str, int, str]  # (song_hash, section_index, brief_hash)


class _PreviewCache:
    """Bounded in-memory LRU cache for preview results.

    Eviction deletes the artifact .xsq file from disk.
    Only 'done' results are admitted (failed/cancelled never stored).
    """

    def __init__(self, max_entries: int = 16) -> None:
        self._max = max_entries
        # Ordered dict: most-recently-used at the end
        from collections import OrderedDict
        self._store: "OrderedDict[CacheKey, tuple[PreviewResult, Path]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> Optional[tuple[PreviewResult, Path]]:
        """Return (result, artifact_path) if cached, else None. Updates LRU order."""
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def put(self, key: CacheKey, result: PreviewResult, artifact_path: Path) -> None:
        """Insert a result. Only call when status == 'done'. Evicts LRU if needed."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = (result, artifact_path)
                return
            self._store[key] = (result, artifact_path)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                _, (_, evicted_path) = self._store.popitem(last=False)
                try:
                    evicted_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ── Window clamping ────────────────────────────────────────────────────────

_MIN_WINDOW_MS = 10_000   # 10 seconds
_MAX_WINDOW_MS = 20_000   # 20 seconds


def _clamp_window_ms(
    section_start: int,
    section_end: int,
    song_duration_ms: int = 0,
) -> tuple[int, int, bool]:
    """Clamp the preview window to the 10-20s range.

    Returns (window_end_ms, window_duration_ms, crosses_boundary).
    - window_end_ms: absolute end time in the song
    - window_duration_ms: length of the preview (10000-20000)
    - crosses_boundary: True when the window extends beyond section_end
    """
    section_dur = section_end - section_start

    if section_dur >= _MAX_WINDOW_MS:
        # Section is longer than max: use first 20s
        window_dur = _MAX_WINDOW_MS
        window_end = section_start + _MAX_WINDOW_MS
        crosses = False
    elif section_dur >= _MIN_WINDOW_MS:
        # Section fits within range: use full section
        window_dur = section_dur
        window_end = section_end
        crosses = False
    else:
        # Section is shorter than minimum: extend into next section
        window_dur = _MIN_WINDOW_MS
        window_end = section_start + _MIN_WINDOW_MS
        if song_duration_ms > 0:
            window_end = min(window_end, song_duration_ms)
            window_dur = window_end - section_start
            # If we still can't get 10s (end of song), use what's available
            if window_dur < _MIN_WINDOW_MS:
                window_dur = max(window_dur, section_dur)
        crosses = window_end > section_end

    return window_end, window_dur, crosses


# ── Representative section picker ─────────────────────────────────────────

_HIGH_ENERGY_THRESHOLD = 50
_MIN_SECTION_DURATION_MS = 4000
_PREFERRED_ROLES = frozenset({"chorus", "drop", "climax"})
_SKIP_ROLES = frozenset({"intro", "outro"})


def pick_representative_section(sections: list) -> int:
    """Return the index of the representative section per User Story 3 rules.

    Ranking:
    1. Filter: duration >= 4000ms AND role not in {intro, outro}
    2. Among filtered with energy >= 50: pick highest energy;
       tiebreak by preferred role (chorus/drop/climax), then earliest start
    3. Fallback A: no energy >= 50 → return longest filtered section
    4. Fallback B: no filtered sections → first section with duration >= 4000ms
    5. Fallback C: return 0

    Accepts list[SectionEnergy] where SectionEnergy has:
      label (str), start_ms (int), end_ms (int), energy_score (int)
    """
    if not sections:
        return 0

    def _dur(s) -> int:
        return s.end_ms - s.start_ms

    def _role(s) -> str:
        return (s.label or "").lower().strip()

    # Step 1: filter to non-intro/outro sections >= 4s
    candidates = [
        (i, s) for i, s in enumerate(sections)
        if _dur(s) >= _MIN_SECTION_DURATION_MS and _role(s) not in _SKIP_ROLES
    ]

    if not candidates:
        # Fallback B: any section >= 4s regardless of role
        fallback_b = [(i, s) for i, s in enumerate(sections) if _dur(s) >= _MIN_SECTION_DURATION_MS]
        if fallback_b:
            return fallback_b[0][0]
        # Fallback C
        return 0

    # Step 2: high-energy candidates (energy >= 50)
    high_energy = [(i, s) for i, s in candidates if s.energy_score >= _HIGH_ENERGY_THRESHOLD]

    if high_energy:
        # Sort by: highest energy desc, preferred role (1=preferred 0=other), earliest start asc
        def _key(pair):
            i, s = pair
            role_pref = 0 if _role(s) in _PREFERRED_ROLES else 1
            return (-s.energy_score, role_pref, s.start_ms)

        high_energy.sort(key=_key)
        return high_energy[0][0]

    # Fallback A: no high-energy sections → return longest candidate
    candidates.sort(key=lambda pair: -_dur(pair[1]))
    return candidates[0][0]


# ── Preview runner ─────────────────────────────────────────────────────────


def run_section_preview(
    config: Any,
    section_index: int,
    output_path: Path,
    cancel_token: CancelToken,
) -> PreviewResult:
    """Run a scoped section preview through the real generator pipeline.

    Pipeline:
    1. build_plan(config, ...) — full plan
    2. [poll] cancel after build_plan
    3. Clone all sections and song-level effects intersecting the target window
    4. Adjust clipped highlight ramps without changing the source plan
    5. [poll] cancel before write_xsq
    6. write_xsq with scoped_duration_ms + audio_offset_ms

    Returns a PreviewResult on success; raises PreviewCancelled on supersede;
    raises other exceptions for pipeline failures.
    """
    from src.analyzer.orchestrator import run_orchestrator
    from src.effects.library import load_effect_library
    from src.generator.plan import build_plan
    from src.grouper.classifier import classify_props, normalize_coords
    from src.grouper.grouper import generate_groups
    from src.grouper.layout import parse_layout
    from src.themes.library import load_theme_library
    from src.variants.library import load_variant_library

    warnings: list[str] = []

    # Stage 1: Analysis
    hierarchy = run_orchestrator(str(config.audio_path), fresh=False)

    # Stage 2: Layout + groups
    layout = parse_layout(config.layout_path)
    props = layout.props
    normalize_coords(props)
    classify_props(props)
    groups = generate_groups(props)

    # Stage 3: Libraries
    effect_library = load_effect_library()
    variant_library = load_variant_library(effect_library=effect_library)
    theme_library = load_theme_library(
        effect_library=effect_library, variant_library=variant_library
    )

    # Stage 4: Full build_plan (all sections)
    plan = build_plan(config, hierarchy, props, groups, effect_library, theme_library,
                      layout=layout)

    # Poll point A: after build_plan, before filtering
    cancel_token.raise_if_cancelled()

    if config.beat_accent_effects and not hierarchy.events.get("drums"):
        warnings.append("drums stem missing — beat accents skipped")
    result = write_section_preview(
        plan, section_index, output_path, hierarchy=hierarchy,
        audio_path=config.audio_path, cancel_token=cancel_token,
    )
    result.warnings[:0] = warnings
    return result


_SONG_EFFECT_COLLECTIONS = (
    "vocal_effects", "video_effects", "crash_effects", "picture_effects",
    "shadow_text_effects", "moving_head_effects", "highlight_effects",
)


def write_section_preview(plan, section_index, output_path, *, hierarchy=None,
                          audio_path=None, cancel_token=None, lyrics=None, words=None,
                          phonemes=None, include_extra_timing=True, vocal_diarization=False):
    """Serialize a completed plan's window without changing its full-song intent.

    Baseline assembly and highlight validation belong to the caller. Retain all
    intersecting sections/extras; writer timestamps use the local preview clock.
    """
    from src.generator.xsq_writer import write_xsq

    if section_index is None:
        section_index = pick_representative_section([a.section for a in plan.sections])
    if type(section_index) is not int or not 0 <= section_index < len(plan.sections):
        raise ValueError(f"section_index {section_index} out of range (plan has {len(plan.sections)} sections)")
    if cancel_token:
        cancel_token.raise_if_cancelled()
    target = plan.sections[section_index]
    section = target.section
    start = section.start_ms
    end, duration, crosses_boundary = _clamp_window_ms(start, section.end_ms, plan.song_profile.duration_ms)
    warnings = []
    if crosses_boundary:
        warnings.append(f"Section shorter than 10s — preview window extended to {duration // 1000}s")

    # The writer rewrites media paths and some layer settings. Never expose the
    # original full plan to those changes when producing a scoped artifact.
    scoped = deepcopy(plan)
    scoped.sections = [a for a in scoped.sections
                       if a.section.start_ms < end and a.section.end_ms > start]
    partial_animation = False
    def visible(collection, *, highlights=False):
        nonlocal partial_animation
        result = {}
        for name, placements in collection.items():
            kept = []
            for p in placements:
                if p.start_ms >= end or p.end_ms <= start:
                    continue
                clipped_start, clipped_end = max(start, p.start_ms), min(end, p.end_ms)
                if (clipped_start, clipped_end) != (p.start_ms, p.end_ms):
                    first, last = "E_TEXTCTRL_Eff_On_Start", "E_TEXTCTRL_Eff_On_End"
                    if highlights and p.effect_name == "On" and all(
                            type(p.parameters.get(k)) in (int, float) for k in (first, last)):
                        initial, final = p.parameters[first], p.parameters[last]
                        length = p.end_ms - p.start_ms
                        p.parameters[first] = round(initial + (final - initial) * (clipped_start - p.start_ms) / length)
                        p.parameters[last] = round(initial + (final - initial) * (clipped_end - p.start_ms) / length)
                        p.start_ms, p.end_ms = clipped_start, clipped_end
                    else:
                        partial_animation = True
                kept.append(p)
            if kept:
                result[name] = kept
        return result
    for assignment in scoped.sections:
        assignment.group_effects = visible(assignment.group_effects)
    for name in _SONG_EFFECT_COLLECTIONS:
        setattr(scoped, name, visible(getattr(scoped, name), highlights=name == "highlight_effects"))
    if partial_animation:
        warnings.append("Effects cut by preview boundaries may restart their animation; verify the full sequence in xLights")
    count = sum(len(ps) for a in scoped.sections for ps in a.group_effects.values())
    count += sum(len(ps) for name in _SONG_EFFECT_COLLECTIONS for ps in getattr(scoped, name).values())
    if cancel_token:
        cancel_token.raise_if_cancelled()
    write_xsq(scoped, output_path, hierarchy=hierarchy, audio_path=audio_path,
              scoped_duration_ms=duration, audio_offset_ms=start, lyrics=lyrics,
              words=words, phonemes=phonemes, include_extra_timing=include_extra_timing,
              vocal_diarization=vocal_diarization)
    return PreviewResult(
        section={"label": section.label, "start_ms": section.start_ms,
                 "end_ms": section.end_ms, "energy_score": section.energy_score,
                 "role": section.label, "index": section_index},
        window_ms=duration, theme_name=target.theme.name if target.theme else "unknown",
        placement_count=count, artifact_url="", warnings=warnings,
    )
