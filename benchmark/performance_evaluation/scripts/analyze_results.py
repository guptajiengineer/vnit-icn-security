"""
Analyze raw benchmark outputs into processed datasets.

Reads from benchmark/data/raw/   →   writes to benchmark/data/processed/

Processed files:
  all_raw.csv                     — all mode combos concatenated
  summary_by_publishers.csv       — mean ± std per (num_publishers, lmm, chunking, auth)
  summary_by_users.csv            — mean ± std per (num_users, lmm, chunking, auth)
  lmm_comparison_publishers.csv  — LMM-1 vs LMM-2, with_chunking/with_auth only
  lmm_comparison_users.csv       — same, by num_users
  chunking_impact.csv             — with/without chunking, LMM-2, with_auth
  failure_rates.csv               — adds failure_rate = 1 - avg_success_rate
  effective_throughput.csv        — derived: num_users * avg_success_rate / arrival_window_used
  benchmark_timing.csv            — copy of raw timing (convenience)

Usage (from repo root):
    python benchmark/scripts/analyze_results.py
"""

import shutil
import sys
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from utils import MODE_DIRS, PROCESSED_DIR, RAW_DIR


def _load_all_raw() -> pd.DataFrame:
    frames = []
    for (chunking_mode, auth_mode), label in MODE_DIRS.items():
        csv_path = RAW_DIR / label / "raw_results.csv"
        if not csv_path.exists():
            print(f"[analyze] SKIP (missing): {csv_path}")
            continue
        df = pd.read_csv(csv_path)
        # Ensure mode columns are present (app always writes them, but be safe).
        if "chunking_mode" not in df.columns:
            df["chunking_mode"] = f"{chunking_mode}_chunking"
        if "auth_mode" not in df.columns:
            df["auth_mode"] = f"{auth_mode}_auth"
        frames.append(df)

    if not frames:
        print("[analyze] ERROR: No raw_results.csv files found under benchmark/data/raw/.")
        print("[analyze] Run 'python benchmark/scripts/run_benchmarks.py' first.")
        sys.exit(1)

    combined = pd.concat(frames, ignore_index=True)
    print(f"[analyze] Loaded {len(combined)} rows from {len(frames)} mode(s).")
    return combined


def _summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    agg = (
        df.groupby(group_cols, sort=False)
        .agg(
            samples=("avg_delay", "count"),
            avg_hops=("avg_hops", "mean"),
            avg_hops_std=("avg_hops", "std"),
            avg_delay=("avg_delay", "mean"),
            avg_delay_std=("avg_delay", "std"),
            avg_success_rate=("avg_success_rate", "mean"),
            avg_success_rate_std=("avg_success_rate", "std"),
        )
        .reset_index()
    )
    agg = agg.fillna(0.0)
    return agg


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    all_raw = _load_all_raw()

    # ── all_raw.csv ──────────────────────────────────────────────────────────
    out = PROCESSED_DIR / "all_raw.csv"
    all_raw.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(all_raw)} rows")

    # ── summary_by_publishers.csv ─────────────────────────────────────────────
    pub_summary = _summarize(all_raw, ["chunking_mode", "auth_mode", "num_publishers", "lmm"])
    out = PROCESSED_DIR / "summary_by_publishers.csv"
    pub_summary.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(pub_summary)} rows")

    # ── summary_by_users.csv ──────────────────────────────────────────────────
    # Fix num_publishers to the highest value in the data for a clean user sweep.
    max_np = int(all_raw["num_publishers"].max())
    user_df = all_raw[all_raw["num_publishers"] == max_np].copy()
    user_summary = _summarize(user_df, ["chunking_mode", "auth_mode", "num_publishers", "num_users", "lmm"])
    out = PROCESSED_DIR / "summary_by_users.csv"
    user_summary.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(user_summary)} rows (Np={max_np})")

    # ── lmm_comparison_publishers.csv ────────────────────────────────────────
    lmm_mask = (
        (pub_summary["chunking_mode"] == "with_chunking") &
        (pub_summary["auth_mode"]     == "with_auth")
    )
    lmm_pub = pub_summary[lmm_mask].copy()
    out = PROCESSED_DIR / "lmm_comparison_publishers.csv"
    lmm_pub.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(lmm_pub)} rows")

    # ── lmm_comparison_users.csv ──────────────────────────────────────────────
    lmm_user_mask = (
        (user_summary["chunking_mode"] == "with_chunking") &
        (user_summary["auth_mode"]     == "with_auth")
    )
    lmm_user = user_summary[lmm_user_mask].copy()
    out = PROCESSED_DIR / "lmm_comparison_users.csv"
    lmm_user.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(lmm_user)} rows")

    # ── chunking_impact.csv ───────────────────────────────────────────────────
    chunk_mask = (
        (pub_summary["auth_mode"] == "with_auth") &
        (pub_summary["lmm"]       == "LMM-2")
    )
    chunk_df = pub_summary[chunk_mask].copy()
    out = PROCESSED_DIR / "chunking_impact.csv"
    chunk_df.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(chunk_df)} rows")

    # ── failure_rates.csv ─────────────────────────────────────────────────────
    fr = pub_summary.copy()
    fr["failure_rate"]     = 1.0 - fr["avg_success_rate"]
    fr["failure_rate_std"] = fr["avg_success_rate_std"]
    out = PROCESSED_DIR / "failure_rates.csv"
    fr.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(fr)} rows")

    # ── effective_throughput.csv ──────────────────────────────────────────────
    tp = all_raw.copy()
    tp["effective_throughput"] = (
        tp["num_users"] * tp["avg_success_rate"] / tp["arrival_window_used"]
    )
    tp_summary = _summarize(tp.assign(avg_delay=tp["effective_throughput"]),
                            ["chunking_mode", "auth_mode", "num_publishers", "lmm"])
    tp_summary = tp_summary.rename(columns={
        "avg_delay":     "avg_throughput",
        "avg_delay_std": "avg_throughput_std",
    })
    tp_summary = tp_summary.drop(columns=["avg_hops", "avg_hops_std",
                                          "avg_success_rate", "avg_success_rate_std"])
    out = PROCESSED_DIR / "effective_throughput.csv"
    tp_summary.to_csv(out, index=False)
    print(f"[analyze] Wrote {out.name}: {len(tp_summary)} rows")

    # ── benchmark_timing.csv ──────────────────────────────────────────────────
    timing_src = RAW_DIR / "benchmark_timing.csv"
    if timing_src.exists():
        shutil.copy2(timing_src, PROCESSED_DIR / "benchmark_timing.csv")
        print(f"[analyze] Copied benchmark_timing.csv to processed/")
    else:
        print("[analyze] WARNING: benchmark_timing.csv not found (run_benchmarks.py not run?)")

    print("[analyze] Done. Next step: python benchmark/scripts/generate_graphs.py")


if __name__ == "__main__":
    main()
