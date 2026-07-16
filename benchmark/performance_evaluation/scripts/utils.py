"""Shared utilities for the ICN benchmarking pipeline."""

from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Paths ──────────────────────────────────────────────────────────────────────
SUITE_DIR     = Path(__file__).resolve().parents[1]   # benchmark/performance_evaluation
REPO_ROOT     = Path(__file__).resolve().parents[3]   # repo root (icn)
RAW_DIR       = SUITE_DIR / "data" / "raw"
PROCESSED_DIR = SUITE_DIR / "data" / "processed"
GRAPHS_DIR    = SUITE_DIR / "graphs"
APP_DIR       = REPO_ROOT / "app"

# ── Mode labels (used as subdirectory names under raw/) ───────────────────────
MODE_DIRS = {
    ("without", "without"): "without_chunking__without_auth",
    ("without", "with"):    "without_chunking__with_auth",
    ("with",    "without"): "with_chunking__without_auth",
    ("with",    "with"):    "with_chunking__with_auth",
}

# ── Plot aesthetics ────────────────────────────────────────────────────────────
LMM_COLORS   = {"LMM-1": "#2196F3", "LMM-2": "#FF9800"}
LMM_MARKERS  = {"LMM-1": "o",       "LMM-2": "s"}
CHUNK_LS     = {"with_chunking": "-",    "without_chunking": "--"}
AUTH_ALPHA   = {"with_auth": 1.0,        "without_auth": 0.55}
MODE_COLORS  = {
    "without_chunking__without_auth": "#607D8B",
    "without_chunking__with_auth":    "#E91E63",
    "with_chunking__without_auth":    "#4CAF50",
    "with_chunking__with_auth":       "#9C27B0",
}

FIG_W_SINGLE  = 8
FIG_H_SINGLE  = 5
FIG_W_WIDE    = 12
FIG_H_WIDE    = 5
DPI           = 300


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def save_fig(fig: plt.Figure, stem: str) -> None:
    """Save figure as PNG (300 dpi), PDF, and SVG."""
    for fmt, subdir in (("png", "png"), ("pdf", "pdf"), ("svg", "svg")):
        out = GRAPHS_DIR / subdir / f"{stem}.{fmt}"
        kw = {"bbox_inches": "tight", "dpi": DPI} if fmt == "png" else {"bbox_inches": "tight"}
        fig.savefig(out, format=fmt, **kw)


def apply_style() -> None:
    """Apply a consistent publication-quality matplotlib style."""
    try:
        plt.style.use("seaborn-v0_8-paper")
    except OSError:
        plt.style.use("seaborn-paper")
    plt.rcParams.update({
        "font.family":       "sans-serif",
        "font.size":         11,
        "axes.titlesize":    12,
        "axes.labelsize":    11,
        "legend.fontsize":   10,
        "xtick.labelsize":   10,
        "ytick.labelsize":   10,
        "axes.grid":         True,
        "grid.alpha":        0.35,
        "lines.linewidth":   1.8,
        "lines.markersize":  6,
        "figure.dpi":        100,
    })
