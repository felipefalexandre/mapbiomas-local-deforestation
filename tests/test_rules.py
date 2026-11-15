from __future__ import annotations

import numpy as np
import pytest

from mapbiomas_local import rules
from mapbiomas_local.rules import (
    ClassCode,
    apply_deforestation_method,
    apply_frequency_correction,
    apply_rule_kernel,
    apply_rules,
    apply_spatial_filter,
    apply_tail_guard,
    build_lookup,
    class_frequency,
    filter_small_patches,
)

FULL_YEARS = list(range(1985, 2026))
ANTHROPIC = 1
PRIMARY = 2
SECONDARY = 3
SUPPRESSION = 4
RECOVERY = 5
SECONDARY_SUPPRESSION = 6
OTHER = 7


def reference_rule_kernel(series, rule, years, kernel_size):
    before, after, min_start = rule
    out = dict(series)
    for i in range(len(years) - kernel_size + 1):
        if i < min_start:
            continue
        window = years[i : i + kernel_size]
        if all(out[y] == before[k] for k, y in enumerate(window)):
            for k, y in enumerate(window):
                out[y] = after[k]
    return out


def reference_pipeline(initial, years, run_end_rules=True, run_blip_filter=True):
    running = 0
    freq = {}
    for year in years:
        running += initial[year] == ANTHROPIC
        freq[year] = running
    state = dict(initial)
    if run_blip_filter:
        for rule in rules.RULES_KERNEL3_VEG_BLIP:
            state = reference_rule_kernel(state, rule, years, 3)
    if run_end_rules:
        for rule in rules.RULES_KERNEL6_SECONDARY_END:
            state = reference_rule_kernel(state, rule, years[-6:], 6)
        for rule in rules.RULES_KERNEL4_SECONDARY_END_REVERT:
            state = reference_rule_kernel(state, rule, years[-4:], 4)
    for group, size in (
        (rules.RULES_KERNEL4, 4),
        (rules.RULES_KERNEL4_SECONDARY, 4),
        (rules.RULES_KERNEL3_SECONDARY, 3),
    ):
        for rule in group:
            state = reference_rule_kernel(state, rule, years, size)
    for rule in rules.RULES_KERNEL4_END:
        state = reference_rule_kernel(state, rule, years[-4:], 4)
    for year in years:
        if freq[year] > 1 and state[year] == SUPPRESSION:
            state[year] = SECONDARY_SUPPRESSION
        if freq[year] > 0 and state[year] == PRIMARY:
            state[year] = SECONDARY
    nm2, nm1, n = years[-3], years[-2], years[-1]
    if state[nm2] == ANTHROPIC and state[nm1] == SECONDARY:
        state[nm1] = ANTHROPIC
    if state[nm1] == ANTHROPIC and state[n] == SECONDARY:
        state[n] = ANTHROPIC
    return state


def single_pixel(values):
    return np.asarray(values, dtype="uint8").reshape(len(values), 1, 1)


def test_lookup_maps_raw_mapbiomas_classes_to_aggregated_codes():
    lut = build_lookup()
    assert lut[1] == ClassCode.PRIMARY_VEGETATION
    assert lut[3] == ClassCode.PRIMARY_VEGETATION
    assert lut[4] == ClassCode.PRIMARY_VEGETATION
    assert lut[6] == ClassCode.PRIMARY_VEGETATION
    assert lut[13] == ClassCode.PRIMARY_VEGETATION
    assert lut[77] == ClassCode.PRIMARY_VEGETATION
    assert lut[9] == ClassCode.ANTHROPIC
    assert lut[15] == ClassCode.ANTHROPIC
    assert lut[23] == ClassCode.OTHER_TRANSITIONS
    assert lut[255] == ClassCode.NO_DATA
    assert lut[0] == ClassCode.NO_DATA


@pytest.mark.parametrize("n_years", [6, 10, 41])
def test_random_series_match_reference_pipeline(n_years):
    rng = np.random.default_rng(42 + n_years)
    years = list(range(2000, 2000 + n_years))
    for _ in range(100):
        values = rng.choice([0, 1, 2, 3, 4, 5, 6, 7], size=n_years).astype("uint8")
        expected = reference_pipeline(dict(zip(years, values.tolist())), years)
        actual = apply_deforestation_method(single_pixel(values))
        assert actual[:, 0, 0].tolist() == [expected[y] for y in years]


def test_blip_filter_removes_one_year_vegetation_between_anthropic():
    values = [ANTHROPIC, ANTHROPIC, ANTHROPIC, PRIMARY, ANTHROPIC, ANTHROPIC, ANTHROPIC]
    stack = single_pixel(values)
    apply_rules(stack, rules.RULES_KERNEL3_VEG_BLIP, 3)
    assert stack[3, 0, 0] == ANTHROPIC


def test_blip_filter_keeps_two_year_block():
    values = [ANTHROPIC, ANTHROPIC, PRIMARY, PRIMARY, ANTHROPIC, ANTHROPIC, ANTHROPIC]
    stack = single_pixel(values)
    apply_rules(stack, rules.RULES_KERNEL3_VEG_BLIP, 3)
    assert stack[2, 0, 0] == PRIMARY
    assert stack[3, 0, 0] == PRIMARY


def test_min_start_blocks_first_window():
    rule = ([PRIMARY, PRIMARY, ANTHROPIC, ANTHROPIC], [PRIMARY, PRIMARY, SUPPRESSION, SUPPRESSION], 1)
    blocked = single_pixel([PRIMARY, PRIMARY, ANTHROPIC, ANTHROPIC])
    apply_rule_kernel(blocked, rule)
    assert blocked[:, 0, 0].tolist() == [PRIMARY, PRIMARY, ANTHROPIC, ANTHROPIC]
    allowed = single_pixel([PRIMARY, PRIMARY, PRIMARY, ANTHROPIC, ANTHROPIC, ANTHROPIC])
    apply_rule_kernel(allowed, rule)
    assert allowed[2:5, 0, 0].tolist() == [PRIMARY, SUPPRESSION, SUPPRESSION]


def test_kernel6_end_rule_only_uses_anchored_tail():
    values = [ANTHROPIC] * 35 + [SECONDARY, SECONDARY, SECONDARY, ANTHROPIC, SECONDARY, ANTHROPIC]
    stack = single_pixel(values)
    apply_rules(stack, rules.RULES_KERNEL6_SECONDARY_END, 6, indices=list(range(35, 41)))
    expected = [SECONDARY, SECONDARY, SECONDARY, ANTHROPIC, SECONDARY, ANTHROPIC]
    assert stack[35:, 0, 0].tolist() == expected


def test_frequency_correction_uses_cumulative_frequency():
    values = [PRIMARY, ANTHROPIC, ANTHROPIC, PRIMARY, SUPPRESSION, SUPPRESSION]
    stack = single_pixel(values)
    aggregated = stack.copy()
    frequency = class_frequency(aggregated)
    apply_frequency_correction(stack, frequency)
    assert stack[0, 0, 0] == PRIMARY
    assert stack[3, 0, 0] == SECONDARY
    assert stack[4, 0, 0] == SECONDARY_SUPPRESSION


def test_tail_guard_strips_frequency_induced_secondary():
    values = [ANTHROPIC, ANTHROPIC, SECONDARY, SECONDARY]
    stack = single_pixel(values)
    apply_tail_guard(stack)
    assert stack[2, 0, 0] == ANTHROPIC
    assert stack[3, 0, 0] == ANTHROPIC


def test_tail_guard_preserves_confirmed_secondary():
    values = [SECONDARY, SECONDARY, RECOVERY, SECONDARY]
    stack = single_pixel(values)
    apply_tail_guard(stack)
    assert stack[3, 0, 0] == SECONDARY


def test_spatial_filter_removes_small_patches():
    band = np.full((20, 20), OTHER, dtype="uint8")
    band[5:7, 5:7] = SUPPRESSION
    stack = band[None]
    apply_spatial_filter(stack, threshold=11, years=[2020])
    assert stack[0, 5, 5] == OTHER


def test_spatial_filter_keeps_large_patches():
    band = np.full((20, 20), OTHER, dtype="uint8")
    band[2:6, 2:6] = SUPPRESSION
    stack = band[None]
    apply_spatial_filter(stack, threshold=11, years=[2020])
    assert np.all(stack[0, 2:6, 2:6] == SUPPRESSION)


def test_spatial_filter_converts_secondary_patches():
    band = np.full((20, 20), OTHER, dtype="uint8")
    band[5:7, 5:7] = SECONDARY
    stack = band[None]
    apply_spatial_filter(stack, threshold=11, years=[2020])
    assert stack[0, 5, 5] == OTHER


def test_fallback_labeling_matches_cv2(monkeypatch):
    mask = np.zeros((30, 30), dtype=bool)
    mask[2:6, 3:7] = True
    mask[10:13, 12:30] = True
    labels_cv2, areas_cv2 = rules._label_8_connected_cv2(mask)
    monkeypatch.setattr(rules, "_label_8_connected_cv2", lambda m: (_ for _ in ()).throw(RuntimeError))
    labels_fb, areas_fb = rules._label_8_connected_fallback(mask)
    assert sorted(areas_cv2[1:].tolist()) == sorted(areas_fb[1:][areas_fb[1:] > 0].tolist())
    same = (labels_cv2 > 0) == (labels_fb > 0)
    assert same.all()


def test_filter_small_patches_ignores_disabled_threshold():
    band = np.full((5, 5), SUPPRESSION, dtype="uint8")
    filter_small_patches(band, band == SUPPRESSION, threshold=0)
    assert np.all(band == SUPPRESSION)
