"""Tests for src/generator/direction_alternation.py."""
from src.generator.direction_alternation import (
    BARS_PER_BLOCK,
    alternate_direction_by_bar_block,
)
from src.generator.models import EffectPlacement, SectionAssignment, SectionEnergy

BAR_MS = 2000
BLOCK_MS = BAR_MS * BARS_PER_BLOCK
# 4 blocks of 4 bars: 0-8s, 8-16s, 16-24s, 24-32s
BAR_TIMES = list(range(0, 4 * BLOCK_MS, BAR_MS))


def _placement(effect, start_ms, params, layer=0, group="06_PROP_Arch"):
    return EffectPlacement(
        effect_name=effect, xlights_id=effect, model_or_group=group,
        start_ms=start_ms, end_ms=start_ms + 400, parameters=dict(params), layer=layer,
    )


def _assignment(placements_by_group, end_ms=4 * BLOCK_MS):
    return SectionAssignment(
        section=SectionEnergy(
            label="chorus", start_ms=0, end_ms=end_ms,
            energy_score=50, mood_tier="structural", impact_count=0,
        ),
        theme=None,
        group_effects=placements_by_group,
    )


def _per_beat(effect, params, **kw):
    # One placement every 500ms across the whole section.
    return [_placement(effect, t, params, **kw) for t in range(0, 4 * BLOCK_MS, 500)]


def _values(placements, key):
    return [p.parameters[key] for p in placements]


def test_fixed_chase_direction_flips_on_alternate_blocks():
    run = _per_beat("Single Strand", {"E_CHOICE_Chase_Type1": "Bounce from Right"})
    alternate_direction_by_bar_block([_assignment({"06_PROP_Arch": run})], BAR_TIMES)

    by_block = {}
    for p in run:
        by_block.setdefault(p.start_ms // BLOCK_MS, set()).add(p.parameters["E_CHOICE_Chase_Type1"])
    assert by_block == {
        0: {"Bounce from Right"}, 1: {"Bounce from Left"},
        2: {"Bounce from Right"}, 3: {"Bounce from Left"},
    }


def test_spirals_sign_flips_and_magnitude_is_kept():
    params = {"E_SLIDER_Spirals_Rotation": "140", "E_TEXTCTRL_Spirals_Movement": "4"}
    run = _per_beat("Spirals", params, group="08_HERO_Mega_Tree")
    alternate_direction_by_bar_block([_assignment({"08_HERO_Mega_Tree": run})], BAR_TIMES)

    block1 = [p for p in run if p.start_ms // BLOCK_MS == 1]
    assert {p.parameters["E_SLIDER_Spirals_Rotation"] for p in block1} == {"-140"}
    assert {p.parameters["E_TEXTCTRL_Spirals_Movement"] for p in block1} == {"-4"}
    block0 = [p for p in run if p.start_ms // BLOCK_MS == 0]
    assert {p.parameters["E_SLIDER_Spirals_Rotation"] for p in block0} == {"140"}


def test_ripple_and_wave_and_pinwheel_flip():
    ripple = _per_beat("Ripple", {"E_CHOICE_Ripple_Movement": "Implode"}, group="08_HERO_Matrix")
    wave = _per_beat("Wave", {"E_CHOICE_Wave_Direction": "Left to Right"}, group="08_HERO_Mega_Tree")
    pin = _per_beat("Pinwheel", {"E_CHECKBOX_Pinwheel_Rotation": "1"}, group="08_HERO_Matrix", layer=1)
    alternate_direction_by_bar_block(
        [_assignment({"08_HERO_Matrix": ripple + pin, "08_HERO_Mega_Tree": wave})], BAR_TIMES,
    )

    odd = lambda run: [p for p in run if p.start_ms // BLOCK_MS == 1]
    assert {p.parameters["E_CHOICE_Ripple_Movement"] for p in odd(ripple)} == {"Explode"}
    assert {p.parameters["E_CHOICE_Wave_Direction"] for p in odd(wave)} == {"Right to Left"}
    assert {p.parameters["E_CHECKBOX_Pinwheel_Rotation"] for p in odd(pin)} == {False}


def test_pinwheel_without_rotation_param_uses_catalog_default():
    run = _per_beat("Pinwheel", {"E_SLIDER_Pinwheel_Speed": 6}, group="08_HERO_Matrix")
    alternate_direction_by_bar_block([_assignment({"08_HERO_Matrix": run})], BAR_TIMES)

    block1 = [p for p in run if p.start_ms // BLOCK_MS == 1]
    assert {p.parameters["E_CHECKBOX_Pinwheel_Rotation"] for p in block1} == {False}


def test_run_that_already_alternates_is_left_alone():
    directions = ["Left-Right", "Right-Left"]
    run = [
        _placement("Single Strand", t, {"E_CHOICE_Chase_Type1": directions[i % 2]})
        for i, t in enumerate(range(0, 4 * BLOCK_MS, 500))
    ]
    before = [p.parameters["E_CHOICE_Chase_Type1"] for p in run]
    alternate_direction_by_bar_block([_assignment({"06_PROP_Arch": run})], BAR_TIMES)
    assert [p.parameters["E_CHOICE_Chase_Type1"] for p in run] == before


def test_directionless_effects_are_untouched():
    run = _per_beat("Shockwave", {"E_SLIDER_Shockwave_Cycles": "1"})
    alternate_direction_by_bar_block([_assignment({"06_PROP_Star": run})], BAR_TIMES)
    assert {tuple(p.parameters.items()) for p in run} == {(("E_SLIDER_Shockwave_Cycles", "1"),)}


def test_no_bar_data_or_single_block_is_a_noop():
    run = _per_beat("Single Strand", {"E_CHOICE_Chase_Type1": "Bounce from Right"})
    alternate_direction_by_bar_block([_assignment({"06_PROP_Arch": run})], [])
    # one block only (bars span 0-8s, section ends at 8s)
    short = [p for p in run if p.start_ms < BLOCK_MS]
    alternate_direction_by_bar_block(
        [_assignment({"06_PROP_Arch": short}, end_ms=BLOCK_MS)], BAR_TIMES,
    )
    assert {p.parameters["E_CHOICE_Chase_Type1"] for p in run} == {"Bounce from Right"}


def test_placements_sharing_one_parameter_dict_do_not_all_flip():
    shared = {"E_CHOICE_Chase_Type1": "Left-Right"}
    run = [
        EffectPlacement("Single Strand", "ss", "06_PROP_Arch", t, t + 400, parameters=shared)
        for t in range(0, 4 * BLOCK_MS, 500)
    ]
    alternate_direction_by_bar_block([_assignment({"06_PROP_Arch": run})], BAR_TIMES)

    assert shared == {"E_CHOICE_Chase_Type1": "Left-Right"}
    assert {p.parameters["E_CHOICE_Chase_Type1"] for p in run} == {"Left-Right", "Right-Left"}


def test_missing_direction_key_is_not_invented():
    run = _per_beat("Single Strand", {"E_SLIDER_Number_Chases": "1"})
    alternate_direction_by_bar_block([_assignment({"06_PROP_Arch": run})], BAR_TIMES)
    assert all("E_CHOICE_Chase_Type1" not in p.parameters for p in run)
