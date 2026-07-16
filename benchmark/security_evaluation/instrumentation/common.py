"""Shared paths and plot style for the instrumentation milestones."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Paths ─────────────────────────────────────────────────────────────────────
INSTR_DIR   = Path(__file__).resolve().parent          # security_evaluation/instrumentation
SUITE_DIR   = INSTR_DIR.parent                         # security_evaluation
REPO_ROOT   = INSTR_DIR.parents[2]                     # repo root (icn)
APP_DIR     = REPO_ROOT / "app"
DATA_DIR    = SUITE_DIR / "data"            # raw + summary CSVs (real measurements)
GRAPHS_DIR  = SUITE_DIR / "graphs"          # generated figures (png/ + pdf/ subdirs)
PNG_DIR     = GRAPHS_DIR / "png"
PDF_DIR     = GRAPHS_DIR / "pdf"

# Make the unmodified app modules importable (crypto_auth, content, ...).
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)


def apply_style() -> None:
    """Publication-quality matplotlib style (matches benchmark/scripts/utils.py)."""
    try:
        plt.style.use("seaborn-v0_8-paper")
    except OSError:
        pass
    plt.rcParams.update({
        "font.family":      "sans-serif",
        "font.size":        11,
        "axes.titlesize":   12,
        "axes.labelsize":   11,
        "legend.fontsize":  10,
        "xtick.labelsize":  10,
        "ytick.labelsize":  10,
        "axes.grid":        True,
        "grid.alpha":       0.35,
        "lines.linewidth":  1.8,
        "lines.markersize": 6,
        "figure.dpi":       100,
    })


def save_fig(fig: plt.Figure, stem: str) -> list[Path]:
    """Save a figure as PNG (300 dpi, png/) and PDF (pdf/); return written paths."""
    written = []
    for fmt, out_dir in (("png", PNG_DIR), ("pdf", PDF_DIR)):
        out = out_dir / f"{stem}.{fmt}"
        kw = {"bbox_inches": "tight"}
        if fmt == "png":
            kw["dpi"] = 300
        fig.savefig(out, format=fmt, **kw)
        written.append(out)
    return written
