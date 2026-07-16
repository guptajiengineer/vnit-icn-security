"""
Benchmark runner for the ICN simulation framework.

Runs four experiment configurations (chunking × auth), one at a time,
timing each with wall-clock measurements. Outputs land in benchmark/data/raw/.

Usage (from repo root):
    python benchmark/scripts/run_benchmarks.py [--iterations N]

Requires:
  - Python environment with the app's dependencies installed (see app/requirements.txt)
  - Hyperledger Fabric stack running (docker compose up) for with_auth runs.
    The script checks peer liveness before starting and aborts if unreachable.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths relative to this file regardless of CWD.
_SCRIPT_DIR   = Path(__file__).resolve().parent
_SUITE_DIR    = _SCRIPT_DIR.parents[0]               # benchmark/performance_evaluation
_REPO_ROOT    = _SCRIPT_DIR.parents[2]               # repo root (icn)
_RAW_DIR      = _SUITE_DIR / "data" / "raw"
_APP_DIR      = _REPO_ROOT / "app"

sys.path.insert(0, str(_SCRIPT_DIR))
from utils import MODE_DIRS


def _peer_reachable() -> bool:
    """Quick TCP check: can we reach peer0.org1.example.com:7051?"""
    import socket
    try:
        with socket.create_connection(("localhost", 7051), timeout=3):
            return True
    except OSError:
        return False


def _run_one_mode(
    chunking_mode: str,
    auth_mode: str,
    iterations: int,
    publisher_start: int,
    publisher_end: int,
    user_start: int,
    user_end: int,
) -> dict:
    label = MODE_DIRS[(chunking_mode, auth_mode)]
    out_dir = _RAW_DIR / label

    cmd = [
        sys.executable,
        str(_APP_DIR / "run_experiments.py"),
        "--chunking-mode", chunking_mode,
        "--auth-mode",     auth_mode,
        "--iterations",    str(iterations),
        "--publisher-start", str(publisher_start),
        "--publisher-end",   str(publisher_end),
        "--user-start",      str(user_start),
        "--user-end",        str(user_end),
        "--output-dir",      str(out_dir),
    ]

    print(f"\n[benchmark] Starting: {label}")
    print(f"[benchmark] Output dir: {out_dir}")
    print(f"[benchmark] Command: {' '.join(cmd[1:])}")

    t0 = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(_APP_DIR), capture_output=False)
    elapsed = time.perf_counter() - t0

    rows = 0
    raw_csv = out_dir / "raw_results.csv"
    if raw_csv.exists():
        import csv
        with open(raw_csv) as f:
            rows = sum(1 for _ in csv.reader(f)) - 1  # subtract header

    status = "ok" if result.returncode == 0 else f"exit_{result.returncode}"
    print(f"[benchmark] Finished: {label} — {elapsed:.1f}s — {rows} rows — {status}")

    return {
        "mode_label":          label,
        "chunking_mode":       chunking_mode,
        "auth_mode":           auth_mode,
        "wall_clock_seconds":  round(elapsed, 3),
        "iterations":          iterations,
        "rows_written":        rows,
        "exit_code":           result.returncode,
        "status":              status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ICN benchmark runner")
    parser.add_argument("--iterations",       type=int, default=5,  help="Topology seeds per mode (default 5)")
    parser.add_argument("--publisher-start",  type=int, default=4)
    parser.add_argument("--publisher-end",    type=int, default=10)
    parser.add_argument("--user-start",       type=int, default=2)
    parser.add_argument("--user-end",         type=int, default=8)
    parser.add_argument("--skip-auth",        action="store_true",
                        help="Skip with_auth runs (useful if Fabric is not running)")
    args = parser.parse_args()

    _RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Save benchmark config.
    config = {
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "iterations":      args.iterations,
        "publisher_start": args.publisher_start,
        "publisher_end":   args.publisher_end,
        "user_start":      args.user_start,
        "user_end":        args.user_end,
        "skip_auth":       args.skip_auth,
    }
    config_path = _RAW_DIR / "benchmark_config.json"
    config_path.write_text(json.dumps(config, indent=2))
    print(f"[benchmark] Config written to {config_path}")

    # Check Fabric liveness before starting with_auth runs.
    fabric_up = _peer_reachable()
    if not fabric_up:
        print("[benchmark] WARNING: peer0.org1.example.com:7051 is not reachable.")
        if args.skip_auth:
            print("[benchmark] --skip-auth set: running without_auth modes only.")
        else:
            print("[benchmark] Run 'docker compose up -d' from repo root, then retry.")
            print("[benchmark] Or pass --skip-auth to run without_auth modes only.")
            sys.exit(1)

    modes = [
        ("without", "without"),
        ("without", "with"),
        ("with",    "without"),
        ("with",    "with"),
    ]
    if args.skip_auth or not fabric_up:
        modes = [(c, a) for c, a in modes if a == "without"]

    timing_rows = []
    total_t0 = time.perf_counter()

    for chunking_mode, auth_mode in modes:
        row = _run_one_mode(
            chunking_mode=chunking_mode,
            auth_mode=auth_mode,
            iterations=args.iterations,
            publisher_start=args.publisher_start,
            publisher_end=args.publisher_end,
            user_start=args.user_start,
            user_end=args.user_end,
        )
        timing_rows.append(row)

    total_elapsed = time.perf_counter() - total_t0
    print(f"\n[benchmark] All runs complete in {total_elapsed:.1f}s total.")

    # Write timing CSV.
    import csv
    timing_path = _RAW_DIR / "benchmark_timing.csv"
    fieldnames = ["mode_label", "chunking_mode", "auth_mode",
                  "wall_clock_seconds", "iterations", "rows_written",
                  "exit_code", "status"]
    with open(timing_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(timing_rows)
    print(f"[benchmark] Timing written to {timing_path}")

    failed = [r["mode_label"] for r in timing_rows if r["exit_code"] != 0]
    if failed:
        print(f"[benchmark] FAILED modes: {failed}")
        sys.exit(1)

    print("[benchmark] Done. Next step: python benchmark/scripts/analyze_results.py")


if __name__ == "__main__":
    main()
