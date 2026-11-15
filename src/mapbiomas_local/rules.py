from __future__ import annotations

from dataclasses import dataclass


class ClassCode:
    NO_DATA = 0
    ANTHROPIC = 1
    PRIMARY_VEGETATION = 2
    SECONDARY_VEGETATION = 3
    PRIMARY_VEG_SUPPRESSION = 4
    RECOVERY = 5
    SECONDARY_VEG_SUPPRESSION = 6
    OTHER_TRANSITIONS = 7


CLASS_NAMES = {
    0: "No data",
    1: "Anthropic",
    2: "Primary vegetation",
    3: "Secondary vegetation",
    4: "Primary vegetation suppression",
    5: "Recovery to secondary vegetation",
    6: "Secondary vegetation suppression",
    7: "Other transitions",
}

CLASS_COLORS = {
    0: "#ffffff",
    1: "#faf5d1",
    2: "#3f7849",
    3: "#5bcf20",
    4: "#ea1c1c",
    5: "#b4f792",
    6: "#fe9934",
    7: "#303149",
}

CLASS_LOOKUP = (
    (0, 0),
    (1, 2),
    (3, 2),
    (4, 2),
    (5, 2),
    (6, 2),
    (7, 2),
    (9, 1),
    (10, 2),
    (11, 2),
    (12, 2),
    (13, 2),
    (14, 1),
    (15, 1),
    (18, 1),
    (19, 1),
    (20, 1),
    (21, 1),
    (22, 1),
    (23, 7),
    (24, 1),
    (25, 1),
    (26, 7),
    (27, 0),
    (29, 7),
    (30, 1),
    (31, 1),
    (32, 7),
    (33, 7),
    (34, 7),
    (35, 1),
    (36, 1),
    (39, 1),
    (40, 1),
    (41, 1),
    (46, 1),
    (47, 1),
    (48, 1),
    (49, 2),
    (50, 2),
    (61, 7),
    (62, 1),
    (66, 2),
    (68, 7),
    (69, 7),
    (70, 2),
    (72, 1),
    (75, 1),
    (77, 2),
    (84, 2),
    (91, 1),
)

RULES_KERNEL3_VEG_BLIP = [
    [[1, 2, 1], [1, 1, 1], 0],
]

RULES_KERNEL4 = [
    [[2, 2, 1, 1], [2, 2, 4, 1], 0],
]

RULES_KERNEL4_END = [
    [[2, 2, 2, 1], [2, 2, 2, 4], 0],
    [[3, 3, 3, 1], [3, 3, 3, 6], 0],
]

RULES_KERNEL4_SECONDARY = [
    [[1, 2, 2, 2], [1, 5, 3, 3], 1],
    [[5, 3, 3, 2], [5, 3, 3, 3], 0],
    [[3, 2, 2, 2], [3, 3, 3, 3], 1],
    [[3, 2, 2, 4], [3, 3, 3, 4], 1],
    [[3, 3, 2, 4], [3, 3, 3, 6], 0],
    [[3, 3, 2, 2], [3, 3, 3, 3], 0],
    [[3, 3, 3, 2], [3, 3, 3, 3], 0],
    [[1, 2, 2, 4], [1, 1, 1, 1], 0],
]

RULES_KERNEL3_SECONDARY = [
    [[3, 4, 1], [3, 6, 1], 0],
]

RULES_KERNEL6_SECONDARY_END = [
    [[1, 1, 1, 1, 2, 2], [1, 1, 1, 1, 5, 3], 0],
    [[1, 1, 1, 1, 1, 2], [1, 1, 1, 1, 1, 5], 0],
    [[2, 1, 1, 1, 1, 2], [2, 1, 1, 1, 1, 5], 0],
]

RULES_KERNEL4_SECONDARY_END_REVERT = [
    [[1, 2, 2, 1], [1, 1, 1, 1], 0],
]

DEFORESTATION_CLASSES = (4, 6)
SECONDARY_VEGETATION_CLASSES = (3, 5)


@dataclass(frozen=True)
class RuleSet:
    blip: list = None
    kernel4: list = None
    kernel4_secondary: list = None
    kernel3_secondary: list = None
    kernel4_end: list = None
    kernel6_secondary_end: list = None
    kernel4_secondary_end_revert: list = None

    @classmethod
    def default(cls) -> "RuleSet":
        return cls(
            blip=RULES_KERNEL3_VEG_BLIP,
            kernel4=RULES_KERNEL4,
            kernel4_secondary=RULES_KERNEL4_SECONDARY,
            kernel3_secondary=RULES_KERNEL3_SECONDARY,
            kernel4_end=RULES_KERNEL4_END,
            kernel6_secondary_end=RULES_KERNEL6_SECONDARY_END,
            kernel4_secondary_end_revert=RULES_KERNEL4_SECONDARY_END_REVERT,
        )

import numpy as np


def build_lookup(lookup=CLASS_LOOKUP, size=256, dtype=np.uint8):
    lut = np.zeros(size, dtype=dtype)
    for raw, agg in lookup:
        if 0 <= raw < size:
            lut[raw] = agg
    return lut


def aggregate(stack, lut=None):
    lut = build_lookup() if lut is None else lut
    return lut[np.asarray(stack)]


def _validate_rule(rule):
    if len(rule) != 3:
        raise ValueError(f"Rule must be [before, after, min_start]: {rule}")
    before, after, min_start = rule
    if len(before) != len(after):
        raise ValueError(f"Rule before/after length mismatch: {rule}")
    if not isinstance(min_start, int) or min_start < 0:
        raise ValueError(f"Rule min_start must be a non-negative int: {rule}")


def apply_rule_kernel(stack, rule, indices=None):
    _validate_rule(rule)
    before, after, min_start = rule
    k = len(before)
    if indices is None:
        indices = list(range(stack.shape[0]))
    else:
        indices = list(indices)
    if len(indices) < k:
        return
    for i in range(len(indices) - k + 1):
        if i < min_start:
            continue
        window = indices[i : i + k]
        mask = stack[window[0]] == before[0]
        for j in range(1, k):
            mask &= stack[window[j]] == before[j]
        if not mask.any():
            continue
        for j, year_pos in enumerate(window):
            stack[year_pos][mask] = after[j]


def apply_rules(stack, rules, kernel_size, indices=None):
    for rule in rules:
        if len(rule[0]) != kernel_size:
            raise ValueError(
                f"Rule kernel {len(rule[0])} does not match kernel_size {kernel_size}"
            )
        apply_rule_kernel(stack, rule, indices=indices)


def class_frequency(aggregated, class_id=ClassCode.ANTHROPIC):
    return np.cumsum(aggregated == class_id, axis=0, dtype=np.uint8)


def apply_frequency_correction(stack, frequency):
    stack[(frequency > 1) & (stack == ClassCode.PRIMARY_VEG_SUPPRESSION)] = (
        ClassCode.SECONDARY_VEG_SUPPRESSION
    )
    stack[(frequency > 0) & (stack == ClassCode.PRIMARY_VEGETATION)] = (
        ClassCode.SECONDARY_VEGETATION
    )


def apply_tail_guard(stack):
    if stack.shape[0] < 3:
        return
    t1, t2, t3 = stack[-3], stack[-2], stack[-1]
    t2[(t1 == ClassCode.ANTHROPIC) & (t2 == ClassCode.SECONDARY_VEGETATION)] = (
        ClassCode.ANTHROPIC
    )
    t3[(t2 == ClassCode.ANTHROPIC) & (t3 == ClassCode.SECONDARY_VEGETATION)] = (
        ClassCode.ANTHROPIC
    )


def apply_deforestation_method(
    aggregated,
    blip=True,
    secondary_end_rules=True,
    rule_set=None,
):
    rs = RuleSet.default() if rule_set is None else rule_set
    stack = np.array(aggregated, copy=True)
    n_years = stack.shape[0]

    if blip:
        apply_rules(stack, rs.blip, 3)
    if secondary_end_rules:
        apply_rules(
            stack,
            rs.kernel6_secondary_end,
            6,
            indices=list(range(max(0, n_years - 6), n_years)),
        )
        apply_rules(
            stack,
            rs.kernel4_secondary_end_revert,
            4,
            indices=list(range(max(0, n_years - 4), n_years)),
        )
    apply_rules(stack, rs.kernel4, 4)
    apply_rules(stack, rs.kernel4_secondary, 4)
    apply_rules(stack, rs.kernel3_secondary, 3)
    apply_rules(stack, rs.kernel4_end, 4, indices=list(range(max(0, n_years - 4), n_years)))

    frequency = class_frequency(aggregated)
    apply_frequency_correction(stack, frequency)
    apply_tail_guard(stack)
    return stack


def _label_8_connected_cv2(mask):
    import cv2

    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    return labels, stats[:, cv2.CC_STAT_AREA]


def _label_8_connected_fallback(mask):
    h, w = mask.shape
    runs_by_row = {}
    run_starts = []
    run_ends = []
    for row in range(h):
        line = mask[row]
        if not line.any():
            continue
        padded = np.zeros(w + 2, dtype="int8")
        padded[1:-1] = line
        diff = np.diff(padded)
        starts = np.flatnonzero(diff == 1)
        ends = np.flatnonzero(diff == -1) - 1
        runs = []
        for start, end in zip(starts.tolist(), ends.tolist()):
            runs.append((start, end, len(run_starts)))
            run_starts.append(start)
            run_ends.append(end)
        runs_by_row[row] = runs

    n_runs = len(run_starts)
    labels = np.zeros((h, w), dtype="int32")
    if n_runs == 0:
        return labels, np.zeros(1, dtype=np.int64)

    parent = list(range(n_runs))
    sizes = [1] * n_runs

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if sizes[ra] < sizes[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        sizes[ra] += sizes[rb]

    for row in range(1, h):
        current = runs_by_row.get(row)
        previous = runs_by_row.get(row - 1)
        if not current or not previous:
            continue
        j = 0
        for start, end, index in current:
            while j < len(previous) and previous[j][1] < start - 1:
                j += 1
            jj = j
            while jj < len(previous) and previous[jj][0] <= end + 1:
                union(index, previous[jj][2])
                jj += 1

    areas = np.zeros(n_runs + 1, dtype=np.int64)
    for index, (start, end) in enumerate(zip(run_starts, run_ends)):
        root = find(index)
        areas[root + 1] += end - start + 1
    for row, runs in runs_by_row.items():
        for start, end, index in runs:
            labels[row, start : end + 1] = find(index) + 1
    return labels, areas


def filter_small_patches(band, mask, threshold, replace=ClassCode.OTHER_TRANSITIONS):
    if threshold <= 0 or not mask.any():
        return
    try:
        labels, areas = _label_8_connected_cv2(mask)
    except Exception:
        labels, areas = _label_8_connected_fallback(mask)
    keep = np.zeros(areas.shape[0], dtype=bool)
    keep[1:] = areas[1:] > threshold
    band[mask & ~keep[labels]] = replace


def apply_spatial_filter(
    stack,
    threshold=11,
    exception_years=(),
    exception_threshold=11,
    years=None,
):
    if years is None:
        years = list(range(stack.shape[0]))
    exception = set(exception_years)
    for pos, year in enumerate(years):
        band = stack[pos]
        thr = exception_threshold if year in exception else threshold
        for classes in (DEFORESTATION_CLASSES, SECONDARY_VEGETATION_CLASSES):
            mask = np.isin(band, classes)
            if not mask.any():
                continue
            filter_small_patches(band, mask, thr)
