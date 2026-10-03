"""Alternate direction between 4-bar blocks of a repeated effect.

Corpus-recipe placements carry mined presets with a fixed direction
(``_make_placement(preserve_directions=True)``), so a section that repeats one
effect on one layer plays it the same way for its whole length -- a 35s run of
Single Strand "Bounce from Right", Ripple "Implode", Spirals rotation 140.
This post-pass mirrors the direction on every other 4-bar block of such a run,
without rewriting the preset: only the direction-bearing parameters change.

A run that already varies direction (per-instance alternation, or a variant's
own direction_cycle) is left alone, so this never fights those mechanisms.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from typing import Any

from src.generator.models import EffectPlacement, SectionAssignment

BARS_PER_BLOCK = 4

_CHASE_MIRROR = {
    "Left-Right": "Right-Left",
    "Right-Left": "Left-Right",
    "Bounce from Left": "Bounce from Right",
    "Bounce from Right": "Bounce from Left",
    "From Middle": "To Middle",
    "To Middle": "From Middle",
    "Bounce from Middle": "Bounce to Middle",
    "Bounce to Middle": "Bounce from Middle",
    "Static Left-Right": "Static Right-Left",
    "Static Right-Left": "Static Left-Right",
}
_WAVE_MIRROR = {"Right to Left": "Left to Right", "Left to Right": "Right to Left"}
_RIPPLE_MIRROR = {"Explode": "Implode", "Implode": "Explode"}

_CHASE_KEY = "E_CHOICE_Chase_Type1"
_WAVE_KEY = "E_CHOICE_Wave_Direction"
_RIPPLE_KEY = "E_CHOICE_Ripple_Movement"
_SPIRALS_SIGNED_KEYS = ("E_SLIDER_Spirals_Rotation", "E_TEXTCTRL_Spirals_Movement")
_PINWHEEL_KEY = "E_CHECKBOX_Pinwheel_Rotation"
# builtin_effects.json default for Pinwheel_Rotation (clockwise/CCW checkbox)
_PINWHEEL_DEFAULT = True


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true")


def _sign(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return (number > 0) - (number < 0)


def _negated(value: Any) -> Any:
    number = float(value)
    flipped = -number
    if isinstance(value, str):
        return str(int(flipped)) if flipped == int(flipped) else str(flipped)
    return int(flipped) if isinstance(value, int) else flipped


def _signature(effect_name: str, params: dict[str, Any]) -> tuple | None:
    """Direction class of a placement; None when the effect has no direction control."""
    if effect_name == "Single Strand":
        return (params.get(_CHASE_KEY),)
    if effect_name == "Wave":
        return (params.get(_WAVE_KEY),)
    if effect_name == "Ripple":
        return (params.get(_RIPPLE_KEY),)
    if effect_name == "Spirals":
        return tuple(_sign(params.get(k)) for k in _SPIRALS_SIGNED_KEYS)
    if effect_name == "Pinwheel":
        return (_truthy(params.get(_PINWHEEL_KEY, _PINWHEEL_DEFAULT)),)
    return None


def _swap(params: dict[str, Any], key: str, table: dict[str, str]) -> None:
    value = params.get(key)
    if value in table:
        params[key] = table[value]


def _mirror(effect_name: str, params: dict[str, Any]) -> None:
    if effect_name == "Single Strand":
        _swap(params, _CHASE_KEY, _CHASE_MIRROR)
    elif effect_name == "Wave":
        _swap(params, _WAVE_KEY, _WAVE_MIRROR)
    elif effect_name == "Ripple":
        _swap(params, _RIPPLE_KEY, _RIPPLE_MIRROR)
    elif effect_name == "Spirals":
        for key in _SPIRALS_SIGNED_KEYS:
            if _sign(params.get(key)):
                params[key] = _negated(params[key])
    elif effect_name == "Pinwheel":
        params[_PINWHEEL_KEY] = not _truthy(params.get(_PINWHEEL_KEY, _PINWHEEL_DEFAULT))


def _block_starts(bar_times_ms: list[int], start_ms: int, end_ms: int) -> list[int]:
    in_section = [t for t in bar_times_ms if start_ms <= t < end_ms]
    return in_section[::BARS_PER_BLOCK]


def alternate_direction_by_bar_block(
    assignments: list[SectionAssignment],
    bar_times_ms: list[int],
) -> None:
    """Mirror direction on every other 4-bar block of each fixed-direction run.

    A run is all placements of one effect on one group layer within a section.
    Mutates ``placement.parameters`` in place. No-op without bar times.
    """
    if not bar_times_ms:
        return
    bar_times_ms = sorted(bar_times_ms)

    for assignment in assignments:
        section = assignment.section
        starts = _block_starts(bar_times_ms, section.start_ms, section.end_ms)
        if len(starts) < 2:
            continue

        runs: dict[tuple[str, int, str], list[EffectPlacement]] = defaultdict(list)
        for group, placements in assignment.group_effects.items():
            for placement in placements:
                if _signature(placement.effect_name, placement.parameters) is None:
                    continue
                runs[(group, placement.layer, placement.effect_name)].append(placement)

        for (_group, _layer, effect_name), run in runs.items():
            if len(run) < 2:
                continue
            if len({_signature(effect_name, p.parameters) for p in run}) > 1:
                continue
            for placement in run:
                block = bisect_right(starts, placement.start_ms) - 1
                if block % 2 == 1:
                    # Copy first: mined presets may hand the same dict to every placement.
                    placement.parameters = dict(placement.parameters)
                    _mirror(effect_name, placement.parameters)
