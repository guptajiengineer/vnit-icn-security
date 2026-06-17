from __future__ import annotations

from typing import List


LEARNING_LAMBDA = 0.4
LEARNING_SIGMA = 1.0
LEARNED_WEIGHT_BLEND = 0.55
PATH_WEIGHT_THRESHOLD = 0.08
WARMUP_ROUNDS = 2
MEASUREMENT_ROUNDS = 2

CHUNKING_MODE_WITHOUT = "without"
CHUNKING_MODE_WITH = "with"
CHUNKING_MODE_BOTH = "both"

def chunking_label(chunking_enabled: bool) -> str:
    return "with_chunking" if chunking_enabled else "without_chunking"


def enabled_chunking_modes(chunking_mode: str) -> List[bool]:
    mode_map = {
        CHUNKING_MODE_WITHOUT: [False],
        CHUNKING_MODE_WITH: [True],
        CHUNKING_MODE_BOTH: [False, True],
    }
    if chunking_mode not in mode_map:
        raise ValueError(
            f"chunking_mode must be one of "
            f"{CHUNKING_MODE_WITHOUT!r}, {CHUNKING_MODE_WITH!r}, {CHUNKING_MODE_BOTH!r}; "
            f"got {chunking_mode!r}"
        )
    return mode_map[chunking_mode]
