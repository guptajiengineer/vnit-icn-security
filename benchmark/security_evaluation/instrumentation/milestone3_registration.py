"""
Milestone 3 — Graph 3: Blockchain Registration Performance.

Research question
-----------------
Does the proposed registration scheme — anchoring ONE Merkle root per content
object on-chain (content.py, Step 4.5) — reduce registration latency and
blockchain transaction cost compared to conventional per-chunk hash
registration, as the number of content chunks grows?

Schemes (both executed for real against the live Fabric network)
-----------------------------------------------------------------
conventional : one real write transaction PER CHUNK — each chunk's SHA-256
               hash is registered under its own key via the same chaincode
               write path (RegisterContentRoot).  Sequential submission,
               each tx a full Endorse → Submit → CommitStatus cycle.
proposed     : the registration step exactly as implemented in
               content.publish_content():
                 crypto_auth.build_merkle_tree(chunk_hashes)   (client-side)
                 ledger.register_content_root(content_id, root)   (1 tx)
                 ledger.store_merkle_tree(content_id, tree)       (1 tx)
               → 2 transactions regardless of chunk count.

Chunk bytes come from the system's own chunk synthesiser
(content._synthetic_chunk_bytes) hashed with crypto_auth.chunk_hash — the
identical data path the simulator publishes.

Measured quantities
-------------------
- Registration time (left y): wall-clock end-to-end time to register one
  content object with N chunks, timed with time.perf_counter.  Every
  individual transaction is also timed and stored in the raw CSV.
- Transaction cost (right y): the COUNT of transactions actually submitted
  (counted, not assumed — incremented only after a submit returns committed).

Every CSV row is a real executed transaction or run.  Nothing is estimated.

Usage (from app/ so .env credential paths resolve):
    python ../benchmark/instrumentation/milestone3_registration.py
"""

from __future__ import annotations

import argparse
import csv
import time
import uuid
from statistics import fmean, pstdev

import matplotlib.pyplot as plt

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# Real, unmodified app modules.
import crypto_auth
from content import _synthetic_chunk_bytes
from fabric.chain import FabricLedger

DEFAULT_CHUNK_COUNTS = [5, 10, 20, 40, 80, 160]
PROPOSED_REPS        = 3   # proposed is cheap (2 tx) → repeat for error bars

RAW_TX_CSV  = DATA_DIR / "m3_registration_tx_raw.csv"
RUN_CSV     = DATA_DIR / "m3_registration_runs.csv"
SUMMARY_CSV = DATA_DIR / "m3_registration_summary.csv"
FIG_STEM    = "graph3_blockchain_registration_performance"


def _chunk_hashes(content_id: str, n: int) -> list[str]:
    """Real chunk hashes from the system's own chunk synthesiser."""
    return [
        crypto_auth.chunk_hash(_synthetic_chunk_bytes(content_id, i))
        for i in range(n)
    ]


def register_conventional(ledger: FabricLedger, content_id: str,
                          hashes: list[str], tx_rows: list[dict]) -> dict:
    """One real write tx per chunk hash. Returns run record."""
    tx_count = 0
    t0 = time.perf_counter()
    for i, h in enumerate(hashes):
        t1 = time.perf_counter()
        ledger.register_content_root(f"{content_id}:chunk{i}", h)
        tx_ms = (time.perf_counter() - t1) * 1000.0
        tx_count += 1
        tx_rows.append({
            "scheme": "conventional", "content_id": content_id,
            "chunk_count": len(hashes), "tx_index": tx_count,
            "tx_kind": "per_chunk_hash", "tx_ms": tx_ms,
        })
    total_ms = (time.perf_counter() - t0) * 1000.0
    return {"scheme": "conventional", "chunk_count": len(hashes),
            "content_id": content_id, "total_ms": total_ms,
            "tx_count": tx_count, "merkle_build_ms": 0.0,
            "root_tx_ms": 0.0, "tree_tx_ms": 0.0}


def register_proposed(ledger: FabricLedger, content_id: str,
                      hashes: list[str], tx_rows: list[dict]) -> dict:
    """The registration step exactly as content.publish_content performs it."""
    tx_count = 0
    t0 = time.perf_counter()

    tb0 = time.perf_counter()
    root, tree_levels = crypto_auth.build_merkle_tree(hashes)
    merkle_build_ms = (time.perf_counter() - tb0) * 1000.0

    tr0 = time.perf_counter()
    ledger.register_content_root(content_id, root)
    root_tx_ms = (time.perf_counter() - tr0) * 1000.0
    tx_count += 1
    tx_rows.append({"scheme": "proposed", "content_id": content_id,
                    "chunk_count": len(hashes), "tx_index": tx_count,
                    "tx_kind": "merkle_root", "tx_ms": root_tx_ms})

    tt0 = time.perf_counter()
    ledger.store_merkle_tree(content_id, tree_levels)
    tree_tx_ms = (time.perf_counter() - tt0) * 1000.0
    tx_count += 1
    tx_rows.append({"scheme": "proposed", "content_id": content_id,
                    "chunk_count": len(hashes), "tx_index": tx_count,
                    "tx_kind": "merkle_tree", "tx_ms": tree_tx_ms})

    total_ms = (time.perf_counter() - t0) * 1000.0
    return {"scheme": "proposed", "chunk_count": len(hashes),
            "content_id": content_id, "total_ms": total_ms,
            "tx_count": tx_count, "merkle_build_ms": merkle_build_ms,
            "root_tx_ms": root_tx_ms, "tree_tx_ms": tree_tx_ms}


def summarize(runs: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = {}
    for r in runs:
        grouped.setdefault((r["scheme"], r["chunk_count"]), []).append(r)

    summary = []
    for (scheme, n), group in sorted(grouped.items()):
        totals = [r["total_ms"] for r in group]
        summary.append({
            "scheme":             scheme,
            "chunk_count":        n,
            "runs":               len(group),
            "mean_total_ms":      fmean(totals),
            "std_total_ms":       pstdev(totals),
            "tx_count":           group[0]["tx_count"],   # identical across reps
            "mean_merkle_build_ms": fmean([r["merkle_build_ms"] for r in group]),
            "mean_root_tx_ms":    fmean([r["root_tx_ms"] for r in group]),
            "mean_tree_tx_ms":    fmean([r["tree_tx_ms"] for r in group]),
        })
    return summary


def write_csv(path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[m3] wrote {path} ({len(rows)} rows)")


def plot(summary: list[dict], chunk_counts: list[int]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    conv = sorted([r for r in summary if r["scheme"] == "conventional"],
                  key=lambda r: r["chunk_count"])
    prop = sorted([r for r in summary if r["scheme"] == "proposed"],
                  key=lambda r: r["chunk_count"])

    # ── Panel A: registration time (left) + tx count (right) ─────────────
    xs_c = [r["chunk_count"] for r in conv]
    xs_p = [r["chunk_count"] for r in prop]
    ax_a.errorbar(xs_c, [r["mean_total_ms"] / 1000.0 for r in conv],
                  yerr=[r["std_total_ms"] / 1000.0 for r in conv],
                  marker="o", color="#E91E63", capsize=3,
                  label="Registration time — conventional (per-chunk tx)")
    ax_a.errorbar(xs_p, [r["mean_total_ms"] / 1000.0 for r in prop],
                  yerr=[r["std_total_ms"] / 1000.0 for r in prop],
                  marker="s", color="#4CAF50", capsize=3,
                  label="Registration time — proposed (Merkle root)")
    ax_a.set_xlabel("Number of content chunks")
    ax_a.set_ylabel("Registration time (s)")
    ax_a.set_ylim(bottom=0)

    ax_r = ax_a.twinx()
    ax_r.plot(xs_c, [r["tx_count"] for r in conv],
              marker="o", linestyle="--", color="#AD1457",
              label="Tx count — conventional")
    ax_r.plot(xs_p, [r["tx_count"] for r in prop],
              marker="s", linestyle="--", color="#2E7D32",
              label="Tx count — proposed")
    ax_r.set_ylabel("Blockchain transactions submitted (count)")
    ax_r.set_ylim(bottom=0)
    ax_r.grid(False)

    la, lla = ax_a.get_legend_handles_labels()
    lr, llr = ax_r.get_legend_handles_labels()
    ax_a.legend(la + lr, lla + llr, loc="upper left", fontsize=8.5)
    ax_a.set_title("(a) Registration time and transaction cost\nvs. number of chunks")

    # ── Panel B: decomposition of the proposed registration ──────────────
    parts = [
        ("mean_merkle_build_ms", "Merkle tree build (client-side)", "#A5D6A7"),
        ("mean_root_tx_ms",      "Tx 1: register Merkle root",      "#4CAF50"),
        ("mean_tree_tx_ms",      "Tx 2: store Merkle tree",         "#1B5E20"),
    ]
    xs = list(range(len(prop)))
    bottoms = [0.0] * len(prop)
    for key, label, color in parts:
        vals = [r[key] / 1000.0 for r in prop]
        ax_b.bar(xs, vals, 0.6, bottom=bottoms, label=label, color=color)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax_b.set_xticks(xs)
    ax_b.set_xticklabels([str(r["chunk_count"]) for r in prop])
    ax_b.set_xlabel("Number of content chunks")
    ax_b.set_ylabel("Mean registration time (s)")
    ax_b.set_title("(b) Decomposition of the proposed registration\n(2 transactions regardless of chunk count)")
    ax_b.legend(fontsize=9)

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m3] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 3: blockchain registration performance")
    parser.add_argument("--chunk-counts", type=int, nargs="+", default=DEFAULT_CHUNK_COUNTS)
    args = parser.parse_args()

    ensure_dirs()
    run_id = uuid.uuid4().hex[:8]
    ledger = FabricLedger()
    tx_rows: list[dict] = []
    runs: list[dict] = []
    try:
        for n in args.chunk_counts:
            # Proposed — repeated for error bars (2 tx per repetition).
            for rep in range(PROPOSED_REPS):
                cid = f"m3-{run_id}-prop-n{n}-r{rep}"
                hashes = _chunk_hashes(cid, n)
                rec = register_proposed(ledger, cid, hashes, tx_rows)
                runs.append(rec)
                print(f"[m3] proposed     n={n:>4} rep={rep}: "
                      f"{rec['total_ms']/1000:.1f}s, {rec['tx_count']} tx")

            # Conventional — one run (per-tx distribution captured in raw CSV).
            cid = f"m3-{run_id}-conv-n{n}"
            hashes = _chunk_hashes(cid, n)
            rec = register_conventional(ledger, cid, hashes, tx_rows)
            runs.append(rec)
            print(f"[m3] conventional n={n:>4}: "
                  f"{rec['total_ms']/1000:.1f}s, {rec['tx_count']} tx")
    finally:
        ledger.close()

    write_csv(RAW_TX_CSV, tx_rows)
    write_csv(RUN_CSV, runs)
    summary = summarize(runs)
    write_csv(SUMMARY_CSV, summary)
    plot(summary, args.chunk_counts)
    print("[m3] done")


if __name__ == "__main__":
    main()
