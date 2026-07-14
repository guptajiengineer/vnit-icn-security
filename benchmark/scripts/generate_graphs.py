"""
Publication-quality graph generation for the ICN benchmark.

Reads from benchmark/data/processed/   →   writes to benchmark/graphs/{png,pdf,svg}/

Figures produced (each in PNG, PDF, SVG):
  fig01_lmm_delay_vs_publishers     LMM-1 vs LMM-2: avg_delay vs Np
  fig02_lmm_delay_vs_users          LMM-1 vs LMM-2: avg_delay vs Nu
  fig03_lmm_hops_vs_publishers      LMM-1 vs LMM-2: avg_hops vs Np
  fig04_lmm_success_vs_publishers   LMM-1 vs LMM-2: avg_success_rate vs Np
  fig05_lmm_success_vs_users        LMM-1 vs LMM-2: avg_success_rate vs Nu
  fig06_chunking_impact             with/without chunking: delay + success rate
  fig07_auth_wallclock_overhead     wall-clock time per mode combo
  fig08_failure_rate_vs_publishers  failure_rate vs Np (all mode combos)
  fig09_effective_throughput        derived throughput vs Np
  fig10_iteration_convergence       metric stability across iterations

Usage (from repo root):
    python benchmark/scripts/generate_graphs.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from utils import (
    PROCESSED_DIR, RAW_DIR, LMM_COLORS, LMM_MARKERS, MODE_COLORS,
    FIG_W_SINGLE, FIG_H_SINGLE, FIG_W_WIDE, FIG_H_WIDE,
    apply_style, save_fig,
)

# ── Helper ─────────────────────────────────────────────────────────────────────

def _require(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"[graphs] SKIP (missing): {path.name} — run analyze_results.py first")
        return pd.DataFrame()
    return pd.read_csv(path)


def _errorbar(ax, x, y, yerr, label, color, marker, ls="-", **kw):
    ax.errorbar(
        x, y, yerr=yerr,
        label=label, color=color, marker=marker,
        linestyle=ls, capsize=4, capthick=1.2,
        **kw,
    )


# ── Figure 1: LMM delay vs publishers ─────────────────────────────────────────

def fig01(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))
    for lmm, grp in df.groupby("lmm"):
        _errorbar(ax, grp["num_publishers"], grp["avg_delay"], grp["avg_delay_std"],
                  label=lmm, color=LMM_COLORS[lmm], marker=LMM_MARKERS[lmm])
    ax.set_xlabel("Number of publishers (Np)")
    ax.set_ylabel("Average simulated delay (time units)")
    ax.set_title("LMM-1 vs LMM-2: Routing Delay vs Publisher Count\n(with chunking, with auth)")
    ax.legend()
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig01_lmm_delay_vs_publishers")
    plt.close(fig)
    print("[graphs] fig01_lmm_delay_vs_publishers — saved")


# ── Figure 2: LMM delay vs users ──────────────────────────────────────────────

def fig02(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))
    for lmm, grp in df.groupby("lmm"):
        _errorbar(ax, grp["num_users"], grp["avg_delay"], grp["avg_delay_std"],
                  label=lmm, color=LMM_COLORS[lmm], marker=LMM_MARKERS[lmm])
    np_fixed = int(df["num_publishers"].iloc[0]) if "num_publishers" in df.columns else "?"
    ax.set_xlabel("Number of users (Nu)")
    ax.set_ylabel("Average simulated delay (time units)")
    ax.set_title(f"LMM-1 vs LMM-2: Routing Delay vs User Count (Np={np_fixed})\n(with chunking, with auth)")
    ax.legend()
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig02_lmm_delay_vs_users")
    plt.close(fig)
    print("[graphs] fig02_lmm_delay_vs_users — saved")


# ── Figure 3: LMM hops vs publishers ──────────────────────────────────────────

def fig03(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))
    for lmm, grp in df.groupby("lmm"):
        _errorbar(ax, grp["num_publishers"], grp["avg_hops"], grp["avg_hops_std"],
                  label=lmm, color=LMM_COLORS[lmm], marker=LMM_MARKERS[lmm])
    ax.set_xlabel("Number of publishers (Np)")
    ax.set_ylabel("Average path length (hops)")
    ax.set_title("LMM-1 vs LMM-2: Path Length vs Publisher Count\n(with chunking, with auth)")
    ax.legend()
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig03_lmm_hops_vs_publishers")
    plt.close(fig)
    print("[graphs] fig03_lmm_hops_vs_publishers — saved")


# ── Figure 4: LMM success rate vs publishers ──────────────────────────────────

def fig04(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))
    for lmm, grp in df.groupby("lmm"):
        _errorbar(ax, grp["num_publishers"], grp["avg_success_rate"], grp["avg_success_rate_std"],
                  label=lmm, color=LMM_COLORS[lmm], marker=LMM_MARKERS[lmm])
    ax.set_xlabel("Number of publishers (Np)")
    ax.set_ylabel("Average success rate")
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.set_title("LMM-1 vs LMM-2: Success Rate vs Publisher Count\n(with chunking, with auth)")
    ax.legend()
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig04_lmm_success_vs_publishers")
    plt.close(fig)
    print("[graphs] fig04_lmm_success_vs_publishers — saved")


# ── Figure 5: LMM success rate vs users ───────────────────────────────────────

def fig05(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))
    for lmm, grp in df.groupby("lmm"):
        _errorbar(ax, grp["num_users"], grp["avg_success_rate"], grp["avg_success_rate_std"],
                  label=lmm, color=LMM_COLORS[lmm], marker=LMM_MARKERS[lmm])
    np_fixed = int(df["num_publishers"].iloc[0]) if "num_publishers" in df.columns else "?"
    ax.set_xlabel("Number of users (Nu)")
    ax.set_ylabel("Average success rate")
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.set_title(f"LMM-1 vs LMM-2: Success Rate vs User Count (Np={np_fixed})\n(with chunking, with auth)")
    ax.legend()
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig05_lmm_success_vs_users")
    plt.close(fig)
    print("[graphs] fig05_lmm_success_vs_users — saved")


# ── Figure 6: Chunking impact (dual-axis) ─────────────────────────────────────

def fig06(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax1 = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))
    ax2 = ax1.twinx()

    colors = {"with_chunking": "#4CAF50", "without_chunking": "#9E9E9E"}
    ls_map  = {"with_chunking": "-",      "without_chunking": "--"}
    markers = {"with_chunking": "o",      "without_chunking": "s"}

    for chunk_mode, grp in df.groupby("chunking_mode"):
        label_suffix = "with chunking" if chunk_mode == "with_chunking" else "without chunking"
        c = colors[chunk_mode]
        ls = ls_map[chunk_mode]
        m  = markers[chunk_mode]
        ax1.errorbar(grp["num_publishers"], grp["avg_delay"], grp["avg_delay_std"],
                     label=f"Delay — {label_suffix}", color=c, marker=m,
                     linestyle=ls, capsize=4, capthick=1.2)
        ax2.errorbar(grp["num_publishers"], grp["avg_success_rate"], grp["avg_success_rate_std"],
                     label=f"Success — {label_suffix}", color=c, marker=m,
                     linestyle=ls, capsize=4, capthick=1.2, alpha=0.55)

    ax1.set_xlabel("Number of publishers (Np)")
    ax1.set_ylabel("Average simulated delay (time units)", color="#333333")
    ax2.set_ylabel("Average success rate", color="#333333")
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)

    ax1.set_title("Chunking Impact: Delay & Success Rate vs Publisher Count\n(LMM-2, with auth)")
    ax1.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig06_chunking_impact")
    plt.close(fig)
    print("[graphs] fig06_chunking_impact — saved")


# ── Figure 7: Wall-clock timing (auth overhead) ────────────────────────────────

def fig07(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))

    labels = df["mode_label"].str.replace("__", "\n").str.replace("_", " ")
    x = np.arange(len(df))
    colors = [MODE_COLORS.get(m, "#888888") for m in df["mode_label"]]

    bars = ax.bar(x, df["wall_clock_seconds"], color=colors, width=0.5, edgecolor="white", linewidth=0.8)

    for bar, row in zip(bars, df.itertuples()):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{row.wall_clock_seconds:.1f}s\n({row.rows_written} rows)",
                ha="center", va="bottom", fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Wall-clock time (seconds)")
    iterations = int(df["iterations"].iloc[0]) if "iterations" in df.columns else "?"
    ax.set_title(
        f"Authentication Overhead: Total Benchmark Duration per Mode\n"
        f"({iterations} iterations; with_auth runs include Fabric gRPC roundtrips)"
    )
    fig.tight_layout()
    save_fig(fig, "fig07_auth_wallclock_overhead")
    plt.close(fig)
    print("[graphs] fig07_auth_wallclock_overhead — saved")


# ── Figure 8: Failure rate vs publishers ──────────────────────────────────────

def fig08(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_WIDE, FIG_H_WIDE))

    for (chunk, auth, lmm), grp in df.groupby(["chunking_mode", "auth_mode", "lmm"]):
        chunk_label = "chunk" if chunk == "with_chunking" else "no-chunk"
        auth_label  = "auth"  if auth  == "with_auth"     else "no-auth"
        label = f"{lmm} / {chunk_label} / {auth_label}"
        color = LMM_COLORS[lmm]
        ls    = "-" if chunk == "with_chunking" else "--"
        alpha = 1.0 if auth == "with_auth" else 0.55
        _errorbar(ax, grp["num_publishers"], grp["failure_rate"], grp["failure_rate_std"],
                  label=label, color=color, marker=LMM_MARKERS[lmm], ls=ls, alpha=alpha)

    ax.set_xlabel("Number of publishers (Np)")
    ax.set_ylabel("Failure rate  (1 − success rate)")
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
    ax.set_title("Request Failure Rate vs Publisher Count — All Mode Combinations")
    ax.legend(fontsize=8, ncol=2)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig08_failure_rate_vs_publishers")
    plt.close(fig)
    print("[graphs] fig08_failure_rate_vs_publishers — saved")


# ── Figure 9: Effective throughput ────────────────────────────────────────────

def fig09(df: pd.DataFrame) -> None:
    if df.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_W_SINGLE, FIG_H_SINGLE))

    wa_df = df[df["auth_mode"] == "with_auth"].copy()
    for (chunk, lmm), grp in wa_df.groupby(["chunking_mode", "lmm"]):
        chunk_label = "with chunking" if chunk == "with_chunking" else "no chunking"
        label = f"{lmm} / {chunk_label}"
        ls    = "-" if chunk == "with_chunking" else "--"
        _errorbar(ax, grp["num_publishers"], grp["avg_throughput"], grp["avg_throughput_std"],
                  label=label, color=LMM_COLORS[lmm], marker=LMM_MARKERS[lmm], ls=ls)

    ax.set_xlabel("Number of publishers (Np)")
    ax.set_ylabel("Effective throughput  (requests / time unit)")
    ax.set_title("Effective Request Throughput vs Publisher Count\n"
                 "(derived: Nu × success_rate / arrival_window; with auth)")
    ax.legend()
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout()
    save_fig(fig, "fig09_effective_throughput")
    plt.close(fig)
    print("[graphs] fig09_effective_throughput — saved")


# ── Figure 10: Iteration convergence ──────────────────────────────────────────

def fig10(raw_dir: Path) -> None:
    # Load iteration profile from with_chunking/with_auth (richest config).
    src = raw_dir / "with_chunking__with_auth" / "iteration_profile_by_publishers.csv"
    if not src.exists():
        print(f"[graphs] fig10 SKIP (missing): {src}")
        return

    df = pd.read_csv(src)
    np_values = sorted(df["num_publishers"].unique())

    fig, axes = plt.subplots(1, 2, figsize=(FIG_W_WIDE, FIG_H_WIDE))
    metrics = [
        ("avg_delay",        "avg_delay_std",        "Average simulated delay"),
        ("avg_success_rate", "avg_success_rate_std",  "Average success rate"),
    ]

    for ax, (metric, metric_std, ylabel) in zip(axes, metrics):
        for lmm in ["LMM-1", "LMM-2"]:
            for np_val in np_values:
                mask = (df["lmm"] == lmm) & (df["num_publishers"] == np_val)
                grp  = df[mask].sort_values("iteration")
                ls   = "-" if lmm == "LMM-1" else "--"
                ax.plot(grp["iteration"], grp[metric],
                        color=LMM_COLORS[lmm], linestyle=ls,
                        marker=LMM_MARKERS[lmm], markersize=4,
                        label=f"{lmm} Np={np_val}", alpha=0.7)

        ax.set_xlabel("Iteration")
        ax.set_ylabel(ylabel)
        if metric == "avg_success_rate":
            ax.set_ylim(0, 1.05)
            ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1))
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    axes[0].set_title("Delay Convergence Across Iterations")
    axes[1].set_title("Success Rate Convergence Across Iterations")

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=8,
               bbox_to_anchor=(0.5, -0.08))
    fig.suptitle("Metric Stability Across Iterations (with chunking, with auth)", y=1.01)
    fig.tight_layout()
    save_fig(fig, "fig10_iteration_convergence")
    plt.close(fig)
    print("[graphs] fig10_iteration_convergence — saved")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    apply_style()

    lmm_pub  = _require(PROCESSED_DIR / "lmm_comparison_publishers.csv")
    lmm_user = _require(PROCESSED_DIR / "lmm_comparison_users.csv")
    chunk_df = _require(PROCESSED_DIR / "chunking_impact.csv")
    timing   = _require(PROCESSED_DIR / "benchmark_timing.csv")
    fail_df  = _require(PROCESSED_DIR / "failure_rates.csv")
    tp_df    = _require(PROCESSED_DIR / "effective_throughput.csv")

    fig01(lmm_pub)
    fig02(lmm_user)
    fig03(lmm_pub)
    fig04(lmm_pub)
    fig05(lmm_user)
    fig06(chunk_df)
    fig07(timing)
    fig08(fail_df)
    fig09(tp_df)
    fig10(RAW_DIR)

    print("\n[graphs] All figures written to benchmark/graphs/{png,pdf,svg}/")
    print("[graphs] Done.")


if __name__ == "__main__":
    main()
