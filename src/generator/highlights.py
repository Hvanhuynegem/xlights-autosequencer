"""Compile reviewed musical intent without modifying its baseline or source clock.

Callers must construct context from current generation inputs. This module does
not load/accept saved plans or enable the runtime export path by itself.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass
import math
import re

from src.effects.library import EffectLibrary
from src.generator.models import EffectPlacement, SequencePlan
from src.grouper.layout import DISPLAY_AS_TO_PROP_TYPE, Layout, prop_type_for_display_as
from src.highlights.models import EventReview, HighlightPlan, PlanContext

RECIPE_VERSION = "1"


@dataclass(frozen=True)
class Recipe:
    event_kinds: frozenset[str]
    min_ms: int
    max_ms: int
    requires_peak: bool


RECIPES = {
    "sustained_wash": Recipe(frozenset({"sweep", "wash", "unknown_texture"}), 250, 30000, True),
    "isolated_impact": Recipe(frozenset({"impact"}), 50, 1000, False),
}
_PROTECTED_EFFECTS = frozenset({"Faces", "Text", "Pictures", "Video", "Moving Head", "DMX", "Servo"})
_SONG_COLLECTIONS = ("vocal_effects", "video_effects", "crash_effects", "picture_effects",
                     "shadow_text_effects", "moving_head_effects", "highlight_effects")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


class HighlightCompileError(ValueError):
    """An actionable reason the complete proposal cannot be applied."""
    def __init__(self, code: str, message: str, treatment_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.treatment_id = treatment_id


def _reject(code, message, treatment_id=None):
    raise HighlightCompileError(code, message, treatment_id)


class _Targets:
    def __init__(self, layout: Layout):
        self.props = {prop.name: prop for prop in layout.props}
        if len(self.props) != len(layout.props):
            _reject("ambiguous_layout", "Duplicate model names")
        self.groups = {}
        for element in layout.raw_tree.getroot().findall(".//modelGroup"):
            name = element.get("name", "")
            if not name or name in self.groups or name in self.props:
                _reject("ambiguous_layout", "Duplicate or empty model/group names")
            self.groups[name] = tuple(n.strip() for n in element.get("models", "").split(",") if n.strip())

    def members(self, name: str, trail=()) -> frozenset[str]:
        if name in self.props:
            return frozenset({name})
        # Submodels share a physical prop: conservative conflict detection.
        if "/" in name:
            parent, sub = name.split("/", 1)
            if parent in self.props and any(s.name == sub for s in self.props[parent].sub_models):
                return frozenset({parent})
        if name in trail:
            _reject("cyclic_group", f"Cyclic layout group: {name}")
        if name not in self.groups or not self.groups[name]:
            _reject("unknown_target", f"Missing or empty layout target: {name}")
        return frozenset().union(*(self.members(member, (*trail, name)) for member in self.groups[name]))


def _aligned(ms: int, frame: int, duration: int) -> int:
    """Nearest frame, ties up; never extend past the last full audio frame."""
    return min((2 * ms + frame) // (2 * frame) * frame, duration // frame * frame)


def _overlap(start, end, placement):
    return start < placement.end_ms and placement.start_ms < end


def _catalog(effect_library: EffectLibrary, level: int):
    effect = effect_library.get("On")
    if effect is None or effect.name != "On" or effect.xlights_id != "eff_ON":
        _reject("recipe_unavailable", "The On effect required by highlight recipes is unavailable")
    parameters = {
        "E_TEXTCTRL_Eff_On_Start": level, "E_TEXTCTRL_Eff_On_End": 0,
        "E_TEXTCTRL_Eff_On_Transparency": 0, "E_TEXTCTRL_Eff_On_Cycles": 1.0,
        "E_CHECKBOX_On_Shimmer": False,
    }
    definitions = {p.storage_name: p for p in effect.parameters}
    for key, value in parameters.items():
        p = definitions.get(key)
        expected = "bool" if type(value) is bool else "float" if type(value) is float else "int"
        if p is None or p.value_type != expected:
            _reject("recipe_unavailable", f"Unsupported On parameter: {key}")
        # Both zero and the peak are used on both brightness endpoints.
        values = (0, level) if key in ("E_TEXTCTRL_Eff_On_Start", "E_TEXTCTRL_Eff_On_End") else (value,)
        if expected != "bool" and any((p.min is not None and v < p.min) or
                                      (p.max is not None and v > p.max) for v in values):
            _reject("recipe_unavailable", f"Catalog range cannot express highlight envelope: {key}")
    return effect, parameters


def _palette(assignment, target, start):
    active = sorted((p for p in assignment.group_effects.get(target, [])
                     if p.start_ms <= start < p.end_ms and p.color_palette), key=lambda p: p.layer)
    if active:
        palette = active[0].color_palette
        shift = 0.0  # Effective baseline palette already contains section adjustments.
    else:
        palette = (assignment.anchor_palette if assignment.anchor_palette and not assignment.theme_overridden
                   else assignment.theme.palette)
        shift = assignment.color_shift
    if not palette or any(not isinstance(c, str) or _COLOR.fullmatch(c) is None for c in palette):
        _reject("palette_unavailable", "Section has no valid inherited palette")
    color = next((c for c in palette if c.lower() != "#000000"), None)
    if color is None:
        _reject("palette_unavailable", "Section palette is entirely black")
    if not isinstance(shift, (int, float)) or not math.isfinite(shift):
        _reject("palette_unavailable", "Invalid section color shift")
    rgb = tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, saturation, value = colorsys.rgb_to_hsv(*rgb)
    shifted = colorsys.hsv_to_rgb((hue + shift) % 1, saturation, value)
    return ["#" + "".join(f"{round(v * 255):02X}" for v in shifted)], bool(active)


def compile_highlights(
    baseline: SequencePlan,
    plan: HighlightPlan,
    *,
    context: PlanContext,
    events: tuple[EventReview, ...],
    layout: Layout,
    effect_library: EffectLibrary,
) -> dict[str, list[EffectPlacement]]:
    """Validate the whole proposal and return placements, or raise without mutation.

    Context must describe the actual current baseline/layout/catalog. It is an
    explicit dependency until the runtime context builder is implemented.
    """
    stale = plan.stale_reasons(context, events)
    if stale:
        _reject("stale_plan", "Changed inputs: " + ", ".join(stale))
    if context.recipe_version != RECIPE_VERSION:
        _reject("recipe_version", "Unsupported highlight recipe version")
    if context.duration_ms != baseline.song_profile.duration_ms:
        _reject("duration_changed", "Baseline duration differs from highlight context")
    frame = baseline.frame_interval_ms
    if type(frame) is not int or frame <= 0:
        _reject("invalid_frame_interval", "Frame interval must be a positive integer")
    if not plan.treatments:
        return {}
    targets = _Targets(layout)
    existing = [(p, False) for section in baseline.sections
                for placements in section.group_effects.values() for p in placements]
    existing += [(p, True) for name in _SONG_COLLECTIONS
                 for placements in getattr(baseline, name).values() for p in placements]
    if any(not 0 <= p.start_ms < p.end_ms <= context.duration_ms or
           p.start_ms % frame or p.end_ms % frame for p, _ in existing):
        _reject("baseline_timing", "Baseline placements must fit the audio and use the sequence frame interval")
    reviews = {review.event.event_id: review for review in plan.events}
    output: dict[str, list[EffectPlacement]] = {}
    claimed = []
    for treatment in plan.treatments:
        recipe = RECIPES.get(treatment.recipe_id)
        review = reviews[treatment.event_id]
        if recipe is None:
            _reject("recipe_unavailable", "Unsupported recipe", treatment.treatment_id)
        if review.status != "accepted" or review.event.kind not in recipe.event_kinds:
            _reject("event_ineligible", "Recipe needs an accepted event of a supported kind", treatment.treatment_id)
        if treatment.intensity <= 0:
            _reject("invisible_treatment", "Highlight intensity must be positive", treatment.treatment_id)
        raw_start, raw_end = treatment.resolve_timing(review.effective_timing)
        start, end = (_aligned(t, frame, context.duration_ms) for t in (raw_start, raw_end))
        if not recipe.min_ms <= end - start <= recipe.max_ms:
            _reject("invalid_duration", "Aligned treatment duration is outside recipe bounds", treatment.treatment_id)
        peak = None
        if recipe.requires_peak:
            measured = review.effective_timing.peak_ms
            if measured is None:
                _reject("missing_peak", "A sustained wash needs a measured or manually marked peak", treatment.treatment_id)
            peak = _aligned(measured, frame, context.duration_ms)
            if not start < peak < end:
                _reject("invalid_peak", "Wash peak must leave a frame for both rise and decay", treatment.treatment_id)
        sections = [a for a in baseline.sections
                    if a.section.start_ms <= min(start, raw_start) and max(end, raw_end) <= a.section.end_ms]
        if len(sections) != 1:
            _reject("section_boundary", "Treatment must fit within one unambiguous reviewed section", treatment.treatment_id)
        assignment = sections[0]
        multiplier = assignment.brightness if recipe.requires_peak else assignment.hit_strength / 0.5
        if not isinstance(multiplier, (int, float)) or not math.isfinite(multiplier) or multiplier < 0:
            _reject("invalid_intensity", "Invalid section intensity override")
        if multiplier == 0:
            _reject("invisible_treatment", "Section overrides reduce the treatment to zero brightness", treatment.treatment_id)
        for target in treatment.targets:
            # Submodels are resolved for collisions but aren't initial recipe targets.
            if "/" in target:
                _reject("target_ineligible", "Initial recipes require complete models or groups", treatment.treatment_id)
            members = targets.members(target)
            palette, already_adjusted = _palette(assignment, target, start)
            # An active baseline palette already carries its section's intensity.
            level = min(100, round(100 * treatment.intensity * (1 if already_adjusted else multiplier)))
            if level <= 0:
                _reject("invisible_treatment", "Treatment rounds to zero brightness", treatment.treatment_id)
            effect, parameters = _catalog(effect_library, level)
            if end - start < effect.min_duration_ms or (peak is not None and
                    min(peak - start, end - peak) < effect.min_duration_ms):
                _reject("invalid_duration", "Placement is shorter than the effect catalog minimum", treatment.treatment_id)
            for member in members:
                prop = targets.props[member]
                if prop.face_definitions or prop.display_as not in DISPLAY_AS_TO_PROP_TYPE:
                    _reject("target_ineligible", f"Protected or unsupported model: {member}", treatment.treatment_id)
                if effect.prop_suitability.get(prop_type_for_display_as(prop.display_as)) not in ("ideal", "good"):
                    _reject("target_ineligible", f"Catalog does not support model: {member}", treatment.treatment_id)
            for other_members, other_start, other_end in claimed:
                if members & other_members and start < other_end and other_start < end:
                    _reject("highlight_collision", "Highlights overlap on the same physical models", treatment.treatment_id)
            for placement, protected in existing:
                if not _overlap(start, end, placement):
                    continue
                if not members & targets.members(placement.model_or_group):
                    continue
                mode = placement.parameters.get("T_CHOICE_LayerMethod", placement.blend_mode)
                if protected or placement.effect_name in _PROTECTED_EFFECTS or mode in ("Min", "Max"):
                    _reject("protected_content", "Highlight overlaps protected content or a fade/mask", treatment.treatment_id)
                if placement.model_or_group != target:
                    _reject("ambiguous_composition", "Overlapping layout groups need compositor arbitration", treatment.treatment_id)
            same_target_layers = [p.layer for p, _ in existing if p.model_or_group == target]
            layer = min([0, *same_target_layers]) - 1
            segments = [(start, end, level, 0)] if peak is None else [(start, peak, 0, level), (peak, end, level, 0)]
            for begin, finish, first, last in segments:
                output.setdefault(target, []).append(EffectPlacement(
                    effect_name=effect.name, xlights_id=effect.xlights_id, model_or_group=target,
                    start_ms=begin, end_ms=finish,
                    parameters={**parameters, "E_TEXTCTRL_Eff_On_Start": first,
                                "E_TEXTCTRL_Eff_On_End": last, "T_CHOICE_LayerMethod": "Additive"},
                    color_palette=list(palette), blend_mode="Additive", layer=layer,
                    buffer_style_override="Default" if target in targets.props else "Per Model Default",
                    frame_interval_ms=frame,
                ))
            claimed.append((members, start, end))
    return output
