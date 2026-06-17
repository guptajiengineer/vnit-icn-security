from __future__ import annotations

from typing import List


LEARNING_LAMBDA = 0.4
LEARNING_SIGMA = 1.0
LEARNED_WEIGHT_BLEND = 0.55
PATH_WEIGHT_THRESHOLD = 0.08
WARMUP_ROUNDS = 2
MEASUREMENT_ROUNDS = 2

# ---------------------------------------------------------------------------
# Chunking-mode toggle (unchanged from final_code)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Auth-mode toggle (mirrors chunking-mode pattern exactly)
# Obj2 addition: allows experiments to run with-auth vs without-auth side by
# side so overhead comparisons can be measured.  Auth is never forced always-on.
# ---------------------------------------------------------------------------

AUTH_MODE_WITHOUT = "without"
AUTH_MODE_WITH    = "with"
AUTH_MODE_BOTH    = "both"


def auth_label(auth_enabled: bool) -> str:
    """Return a short string label for CSV/directory naming."""
    return "with_auth" if auth_enabled else "without_auth"


def enabled_auth_modes(auth_mode: str) -> List[bool]:
    """
    Translate an auth_mode string into a list of booleans that the experiment
    loop iterates over — exactly as enabled_chunking_modes() works.

    Parameters
    ----------
    auth_mode : str
        One of AUTH_MODE_WITHOUT, AUTH_MODE_WITH, AUTH_MODE_BOTH.

    Returns
    -------
    List[bool]
        [False] for WITHOUT, [True] for WITH, [False, True] for BOTH.

    Raises
    ------
    ValueError
        If auth_mode is not a recognised constant.
    """
    mode_map = {
        AUTH_MODE_WITHOUT: [False],
        AUTH_MODE_WITH:    [True],
        AUTH_MODE_BOTH:    [False, True],
    }
    if auth_mode not in mode_map:
        raise ValueError(
            f"auth_mode must be one of "
            f"{AUTH_MODE_WITHOUT!r}, {AUTH_MODE_WITH!r}, {AUTH_MODE_BOTH!r}; "
            f"got {auth_mode!r}"
        )
    return mode_map[auth_mode]
