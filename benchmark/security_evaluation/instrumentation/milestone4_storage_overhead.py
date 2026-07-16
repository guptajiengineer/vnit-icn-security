"""
Milestone 4 — Graph 4: Blockchain Storage Overhead.

Research question
-----------------
How many bytes of on-chain state does each storage strategy consume, and how
does that scale with the number of content chunks?  This is the storage-side
justification for the proposed design decision to anchor content integrity
with a single Merkle root instead of per-chunk records.

Strategies (each REALLY written to the live Fabric chaincode, then read back
with real Evaluate calls; stored size = UTF-8 bytes of key + value payload
actually returned by the ledger)
--------------------------------------------------------------------------
full_metadata : the complete PUBLIC per-chunk security record the real
                pipeline produces (chunk_hash, chunk_locator, nonce,
                chunk_signature — the AES key is secret and never on-chain),
                serialised as JSON.  What a naive "everything on-chain"
                design would store.
chunk_hashes  : JSON list of the per-chunk SHA-256 hashes only.
merkle_root   : the proposed verification anchor — one 64-hex-char root
                (crypto_auth.build_merkle_tree over the real chunk hashes).
merkle_tree   : the full tree_levels JSON that the CURRENT implementation
                additionally stores via ledger.store_merkle_tree() as a
                serving-time convenience.  Included deliberately: it is O(N)
                and must not be hidden when judging the storage claim.

Chunk records are produced by the real crypto pipeline on the system's own
synthetic chunks (content._synthetic_chunk_bytes → chunk_hash → encrypt_chunk
→ sign_chunk), identical to publish_content().

Every byte count in the CSV is measured from data actually read back from the
running Fabric peer.  Nothing is estimated.

Usage (from app/ so .env credential paths resolve):
    python ../benchmark/instrumentation/milestone4_storage_overhead.py
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import uuid

import matplotlib.pyplot as plt

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# Real, unmodified app modules.
import crypto_auth
from content import _synthetic_chunk_bytes
from fabric.chain import FabricLedger

DEFAULT_CHUNK_COUNTS = [100, 500, 1000]

RAW_CSV     = DATA_DIR / "m4_storage_overhead_raw.csv"
FIG_STEM    = "graph4_blockchain_storage_overhead"

STRATEGIES = ["full_metadata", "chunk_hashes", "merkle_root", "merkle_tree"]


def build_chunk_records(content_id: str, n: int):
    """Real per-chunk security records, exactly as publish_content creates them."""
    priv, pub_bytes = crypto_auth.generate_producer_keypair()
    records = []
    hashes = []
    for i in range(n):
        chunk = _synthetic_chunk_bytes(content_id, i)
        h = crypto_auth.chunk_hash(chunk)
        ciphertext, key, nonce = crypto_auth.encrypt_chunk(chunk)
        sig = crypto_auth.sign_chunk(priv, h)
        hashes.append(h)
        records.append({
            "chunk_hash":      h,
            "chunk_locator":   f"{content_id}:{i}",
            "nonce":           nonce.hex(),
            "chunk_signature": sig.hex(),
        })
    return records, hashes


def store_and_measure(ledger: FabricLedger, run_id: str, n: int) -> list[dict]:
    """
    Write each strategy to the chain, read it back, measure the stored bytes.
    Returns one row per (chunk_count, strategy).
    """
    cid = f"m4-{run_id}-n{n}"
    records, hashes = build_chunk_records(cid, n)
    root, tree_levels = crypto_auth.build_merkle_tree(hashes)

    payloads = {
        "full_metadata": (f"{cid}:metadata", json.dumps(records)),
        "chunk_hashes":  (f"{cid}:hashes",   json.dumps(hashes)),
        "merkle_root":   (f"{cid}:root",     root),
    }

    rows = []
    for strategy, (key, value) in payloads.items():
        t0 = time.perf_counter()
        ledger.register_content_root(key, value)      # real write tx
        write_ms = (time.perf_counter() - t0) * 1000.0

        stored = ledger.get_content_root(key)          # real read back
        assert stored == value                         # ledger holds exactly this
        stored_bytes = len(key.encode()) + len(stored.encode())
        rows.append({"chunk_count": n, "strategy": strategy,
                     "key": key, "stored_bytes": stored_bytes,
                     "write_ms": write_ms})
        print(f"[m4] n={n:>5} {strategy:<14} {stored_bytes:>9,} bytes")

    # merkle_tree — via the implementation's own API (store_merkle_tree).
    tree_key = f"{cid}:tree"
    t0 = time.perf_counter()
    ledger.store_merkle_tree(tree_key, tree_levels)    # real write tx
    write_ms = (time.perf_counter() - t0) * 1000.0
    stored_tree = ledger.get_merkle_tree(tree_key)     # real read back
    assert stored_tree == tree_levels
    stored_bytes = len(tree_key.encode()) + len(json.dumps(stored_tree).encode())
    rows.append({"chunk_count": n, "strategy": "merkle_tree",
                 "key": tree_key, "stored_bytes": stored_bytes,
                 "write_ms": write_ms})
    print(f"[m4] n={n:>5} {'merkle_tree':<14} {stored_bytes:>9,} bytes")
    return rows


def write_csv(path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[m4] wrote {path} ({len(rows)} rows)")


def plot(rows: list[dict], chunk_counts: list[int]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    style = {
        "full_metadata": ("Full per-chunk metadata",              "#E91E63"),
        "chunk_hashes":  ("Per-chunk hashes",                     "#FF9800"),
        "merkle_tree":   ("Merkle tree (implementation extra)",   "#81C784"),
        "merkle_root":   ("Merkle root only (proposed anchor)",   "#1B5E20"),
    }

    def size_of(n, strategy):
        for r in rows:
            if r["chunk_count"] == n and r["strategy"] == strategy:
                return r["stored_bytes"]
        raise KeyError((n, strategy))

    # ── Panel A: measured on-chain bytes, grouped bars, log scale ────────
    width = 0.2
    xs = range(len(chunk_counts))
    for si, strategy in enumerate(["full_metadata", "chunk_hashes",
                                   "merkle_tree", "merkle_root"]):
        label, color = style[strategy]
        vals = [size_of(n, strategy) / 1024.0 for n in chunk_counts]
        pos = [x + (si - 1.5) * width for x in xs]
        bars = ax_a.bar(pos, vals, width, label=label, color=color)
        for b, v in zip(bars, vals):
            txt = f"{v:.2f}" if v < 1 else f"{v:,.0f}"
            ax_a.annotate(txt, (b.get_x() + b.get_width() / 2, v),
                          textcoords="offset points", xytext=(0, 3),
                          ha="center", fontsize=8)
    ax_a.set_yscale("log")
    ax_a.set_xticks(list(xs))
    ax_a.set_xticklabels([str(n) for n in chunk_counts])
    ax_a.set_xlabel("Number of content chunks")
    ax_a.set_ylabel("On-chain storage (KB, log scale)")
    ax_a.set_title("(a) Measured on-chain storage per content object\nby storage strategy")
    ax_a.legend(fontsize=8.5)

    # ── Panel B: per-chunk amortisation (measured bytes ÷ chunk count) ───
    for strategy in ["full_metadata", "chunk_hashes", "merkle_tree", "merkle_root"]:
        label, color = style[strategy]
        vals = [size_of(n, strategy) / n for n in chunk_counts]
        ax_b.plot(chunk_counts, vals, marker="o", color=color, label=label)
    ax_b.set_yscale("log")
    ax_b.set_xlabel("Number of content chunks")
    ax_b.set_ylabel("On-chain bytes per chunk (measured ÷ N, log scale)")
    ax_b.set_title("(b) Amortised on-chain cost per chunk\n(derived: measured bytes ÷ chunk count)")
    ax_b.legend(fontsize=8.5)

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m4] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 4: blockchain storage overhead")
    parser.add_argument("--chunk-counts", type=int, nargs="+", default=DEFAULT_CHUNK_COUNTS)
    args = parser.parse_args()

    ensure_dirs()
    run_id = uuid.uuid4().hex[:8]
    ledger = FabricLedger()
    rows: list[dict] = []
    try:
        for n in args.chunk_counts:
            rows.extend(store_and_measure(ledger, run_id, n))
    finally:
        ledger.close()

    write_csv(RAW_CSV, rows)
    plot(rows, args.chunk_counts)
    print("[m4] done")


if __name__ == "__main__":
    main()
