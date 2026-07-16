"""
Milestone 2 — Graph 2: Authentication Performance of the proposed
blockchain-backed authentication mechanism.

Research question
-----------------
Does authentication remain fast and reliable as the number of authentication
requests grows — bounded per-request delay, and 0 false rejects for
legitimate content?

What one "authentication request" is
------------------------------------
The COMPLETE per-chunk authentication chain the implemented system executes
(code paths in app/network_scenario.py, functions imported UNMODIFIED from
app/crypto_auth.py and app/fabric/chain.py):

  Serving node   (_send_data → _get_merkle_proof_for_chunk):
    ledger.get_merkle_tree(content_id)      ← real Fabric gRPC Evaluate
    crypto_auth.get_merkle_proof(tree, idx)

  Receiving node (_verify_chunk_proof):
    ledger.get_content_root(content_id)     ← real Fabric gRPC Evaluate
    crypto_auth.verify_merkle_proof(...)
    ledger.get_producer_key(producer_id)    ← real Fabric gRPC Evaluate
    crypto_auth.verify_chunk_signature(...)

  Consumer       (_consumer_verify_chunk):
    manifest access (ECIES unwrap on first request per content, then cached —
    exactly like NetworkScenario._manifest_cache)
    manifest hash match
    crypto_auth.decrypt_chunk(...)
    re-hash and compare

Setup is the real publish pipeline: content.publish_content() against the
live FabricLedger (real Endorse→Submit→CommitStatus transactions), producer
keys registered on-chain.

Sweep
-----
For each request count N in --request-counts, N real requests are issued
round-robin over CONTENT_COUNT contents x CHUNKS_PER_CONTENT chunks.
  Left  y-axis : mean per-request authentication delay (ms), measured
                 end-to-end with time.perf_counter around each request.
  Right y-axis : authentication success rate (%) — a request succeeds only if
                 every verification step actually passed.

Baseline
--------
The identical chain over SimulatedLedger (in-memory dict) isolates the
blockchain's contribution to authentication delay. Panel (b) decomposes the
Fabric per-request delay into ledger-read vs local-crypto components.

Every CSV row is one actually executed request. Nothing is estimated.

Usage (from repo root, Fabric stack must be running):
    python benchmark/instrumentation/milestone2_auth_performance.py
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import uuid
from statistics import fmean, pstdev

import matplotlib.pyplot as plt

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# Real, unmodified app modules (path set by common.py).
import crypto_auth
from content import publish_content
from fabric.chain import FabricLedger, SimulatedLedger
from models import ContentSpec

CONTENT_COUNT      = 4
CHUNKS_PER_CONTENT = 16
DEFAULT_COUNTS     = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]

RAW_CSV     = DATA_DIR / "m2_auth_performance_raw.csv"
SUMMARY_CSV = DATA_DIR / "m2_auth_performance_summary.csv"
FIG_STEM    = "graph2_authentication_performance"

LEDGER_COMPONENTS = ["ledger_get_tree", "ledger_get_root", "ledger_get_key"]
LOCAL_COMPONENTS  = ["proof_gen", "proof_verify", "sig_verify",
                     "manifest_access", "hash_check", "decrypt", "rehash"]


def _timed(fn, *args):
    t0 = time.perf_counter()
    result = fn(*args)
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0, result


def make_content_specs(run_id: str) -> list[ContentSpec]:
    """Run-unique content ids so persisted Fabric state never collides."""
    return [
        ContentSpec(
            content_id=f"m2-{run_id}-a{i + 1}",
            generation_round=-(i + 2),
            lifespan_rounds=8 + 2 * i,
            cache_cost=6.0 + 1.5 * i,
            availability_threshold=0.22,
            lifetime_threshold=0.0,
            popularity=max(0.35, 1.0 - 0.14 * i),
        )
        for i in range(CONTENT_COUNT)
    ]


def publish_all(ledger, run_id: str):
    """
    Real publish pipeline (content.publish_content, unmodified): registers
    producers + Merkle roots + trees on the ledger, returns everything a
    consumer-side verifier needs.
    """
    specs = make_content_specs(run_id)
    consumer_priv, consumer_pub = crypto_auth.generate_consumer_keypair()
    published = {}
    for i, spec in enumerate(specs):
        producer_id = f"m2-{run_id}-p{i + 1}"
        priv, pub_bytes = crypto_auth.generate_producer_keypair()
        ledger.register_producer(producer_id, pub_bytes)
        _manifest, chunk_records, wrapped = publish_content(
            content_spec=spec,
            chunk_count=CHUNKS_PER_CONTENT,
            ledger=ledger,
            producer_id=producer_id,
            consumer_public_key=consumer_pub,
            producer_private_key=priv,
        )
        published[spec.content_id] = {
            "producer_id":   producer_id,
            "chunk_records": chunk_records,
            "wrapped":       wrapped,
        }
    return published, consumer_priv


def run_requests(ledger, published, consumer_priv, n_requests: int,
                 backend: str) -> list[dict]:
    """Issue n_requests real authentication requests; one raw row each."""
    rows = []
    content_ids = sorted(published.keys())
    manifest_cache: dict[str, list] = {}   # mirrors NetworkScenario._manifest_cache

    for req in range(n_requests):
        content_id = content_ids[req % len(content_ids)]
        chunk_id = (req // len(content_ids)) % CHUNKS_PER_CONTENT
        pub = published[content_id]
        record = pub["chunk_records"][chunk_id]

        t: dict[str, float] = {c: 0.0 for c in LEDGER_COMPONENTS + LOCAL_COMPONENTS}
        success = True
        error = ""
        t_req0 = time.perf_counter()
        try:
            # ── Serving node: proof retrieval (_get_merkle_proof_for_chunk) ──
            t["ledger_get_tree"], tree_levels = _timed(
                ledger.get_merkle_tree, content_id)
            t["proof_gen"], proof = _timed(
                crypto_auth.get_merkle_proof, tree_levels, chunk_id)

            # ── Receiving node: _verify_chunk_proof ──────────────────────────
            t["ledger_get_root"], root = _timed(
                ledger.get_content_root, content_id)
            t["proof_verify"], ok = _timed(
                crypto_auth.verify_merkle_proof, record.chunk_hash, proof, root)
            if not ok:
                raise RuntimeError("merkle proof rejected")

            t["ledger_get_key"], producer_key = _timed(
                ledger.get_producer_key, pub["producer_id"])
            t["sig_verify"], ok = _timed(
                crypto_auth.verify_chunk_signature,
                producer_key, record.chunk_hash, record.chunk_signature)
            if not ok:
                raise RuntimeError("signature rejected")

            # ── Consumer: _consumer_verify_chunk ─────────────────────────────
            def _manifest_access():
                if content_id not in manifest_cache:
                    raw = crypto_auth.unwrap_manifest_for_consumer(
                        pub["wrapped"], consumer_priv)
                    manifest_cache[content_id] = json.loads(raw.decode("utf-8"))
                return manifest_cache[content_id]
            t["manifest_access"], manifest = _timed(_manifest_access)

            def _hash_check():
                entry = manifest[chunk_id]
                return entry["chunk_hash"] == record.chunk_hash
            t["hash_check"], ok = _timed(_hash_check)
            if not ok:
                raise RuntimeError("manifest hash mismatch")

            key_bytes = bytes.fromhex(manifest[chunk_id]["chunk_key"])
            t["decrypt"], plaintext = _timed(
                crypto_auth.decrypt_chunk, record.ciphertext, key_bytes, record.nonce)
            t["rehash"], h2 = _timed(crypto_auth.chunk_hash, plaintext)
            if h2 != record.chunk_hash:
                raise RuntimeError("re-hash mismatch")
        except Exception as exc:            # real failure — recorded, not hidden
            success = False
            error = f"{type(exc).__name__}: {exc}"
        total_ms = (time.perf_counter() - t_req0) * 1000.0

        rows.append({
            "backend":         backend,
            "target_requests": n_requests,
            "request_index":   req,
            "content_id":      content_id,
            "chunk_id":        chunk_id,
            "success":         int(success),
            "error":           error,
            "total_ms":        total_ms,
            **t,
        })
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = {}
    for r in rows:
        grouped.setdefault((r["backend"], r["target_requests"]), []).append(r)

    summary = []
    for (backend, n), group in sorted(grouped.items()):
        totals = [r["total_ms"] for r in group]
        row = {
            "backend":            backend,
            "target_requests":    n,
            "samples":            len(group),
            "success_rate_pct":   100.0 * sum(r["success"] for r in group) / len(group),
            "mean_delay_ms":      fmean(totals),
            "std_delay_ms":       pstdev(totals),
            "min_delay_ms":       min(totals),
            "max_delay_ms":       max(totals),
        }
        for c in LEDGER_COMPONENTS + LOCAL_COMPONENTS:
            row[f"mean_{c}_ms"] = fmean([r[c] for r in group])
        summary.append(row)
    return summary


def write_csv(path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[m2] wrote {path} ({len(rows)} rows)")


def plot(summary: list[dict], counts: list[int]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    fab = [r for r in summary if r["backend"] == "fabric"]
    sim = [r for r in summary if r["backend"] == "simulated"]
    fab.sort(key=lambda r: r["target_requests"])
    sim.sort(key=lambda r: r["target_requests"])

    # ── Panel A: delay (left) + success rate (right) vs request count ────
    xs_f = [r["target_requests"] for r in fab]
    ax_a.errorbar(xs_f, [r["mean_delay_ms"] for r in fab],
                  yerr=[r["std_delay_ms"] for r in fab],
                  marker="o", color="#9C27B0", capsize=3,
                  label="Auth delay — proposed (Fabric ledger)")
    if sim:
        xs_s = [r["target_requests"] for r in sim]
        ax_a.errorbar(xs_s, [r["mean_delay_ms"] for r in sim],
                      yerr=[r["std_delay_ms"] for r in sim],
                      marker="s", linestyle="--", color="#607D8B", capsize=3,
                      label="Auth delay — in-memory ledger baseline")
    ax_a.set_xlabel("Number of authentication requests")
    ax_a.set_ylabel("Authentication delay per request (ms)")
    ax_a.set_ylim(bottom=0)

    ax_r = ax_a.twinx()
    ax_r.plot(xs_f, [r["success_rate_pct"] for r in fab],
              marker="^", color="#4CAF50",
              label="Success rate — proposed (Fabric ledger)")
    ax_r.set_ylabel("Authentication success rate (%)")
    ax_r.set_ylim(0, 105)
    ax_r.grid(False)

    lines_a, labels_a = ax_a.get_legend_handles_labels()
    lines_r, labels_r = ax_r.get_legend_handles_labels()
    ax_a.legend(lines_a + lines_r, labels_a + labels_r,
                loc="center right", fontsize=8.5)
    ax_a.set_title("(a) Authentication delay and success rate\nvs. number of requests")

    # ── Panel B: component decomposition of the Fabric per-request delay ─
    parts = [
        ("ledger_get_tree",  "Ledger read: Merkle tree (gRPC)",  "#7B1FA2"),
        ("ledger_get_root",  "Ledger read: content root (gRPC)", "#9C27B0"),
        ("ledger_get_key",   "Ledger read: producer key (gRPC)", "#CE93D8"),
        ("proof_gen",        "Merkle proof generation",          "#FFB74D"),
        ("proof_verify",     "Merkle proof verify",              "#FB8C00"),
        ("sig_verify",       "Ed25519 signature verify",         "#E65100"),
        ("manifest_access",  "Manifest access (ECIES/cache)",    "#4DB6AC"),
        ("decrypt",          "AES-256-GCM decrypt",              "#00796B"),
        ("rehash",           "SHA-256 re-hash",                  "#004D40"),
    ]
    xs = list(range(len(fab)))
    bottoms = [0.0] * len(fab)
    for name, label, color in parts:
        vals = [r[f"mean_{name}_ms"] for r in fab]
        ax_b.bar(xs, vals, 0.6, bottom=bottoms, label=label, color=color)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax_b.set_xticks(xs)
    ax_b.set_xticklabels([str(r["target_requests"]) for r in fab])
    ax_b.set_xlabel("Number of authentication requests")
    ax_b.set_ylabel("Mean per-request delay (ms)")
    ax_b.set_title("(b) Decomposition of per-request authentication delay\n(proposed, Fabric ledger)")
    ax_b.legend(fontsize=8)

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m2] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 2: authentication performance")
    parser.add_argument("--request-counts", type=int, nargs="+", default=DEFAULT_COUNTS)
    args = parser.parse_args()

    ensure_dirs()
    all_rows: list[dict] = []

    for backend, make_ledger in (("fabric", FabricLedger), ("simulated", SimulatedLedger)):
        for n in args.request_counts:
            run_id = uuid.uuid4().hex[:8]
            ledger = make_ledger()
            try:
                published, consumer_priv = publish_all(ledger, run_id)
                t0 = time.perf_counter()
                rows = run_requests(ledger, published, consumer_priv, n, backend)
                elapsed = time.perf_counter() - t0
                ok = sum(r["success"] for r in rows)
                print(f"[m2] {backend:>9} N={n:>4}: {ok}/{n} succeeded "
                      f"in {elapsed:.1f}s")
                all_rows.extend(rows)
            finally:
                if hasattr(ledger, "close"):
                    ledger.close()

    write_csv(RAW_CSV, all_rows)
    summary = summarize(all_rows)
    write_csv(SUMMARY_CSV, summary)
    plot(summary, args.request_counts)
    print("[m2] done")


if __name__ == "__main__":
    main()
