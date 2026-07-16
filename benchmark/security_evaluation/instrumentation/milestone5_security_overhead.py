"""
Milestone 5 — Graph 5: Security Overhead Comparison.

Research question
-----------------
What is the TOTAL security overhead — publisher-side security processing +
blockchain interaction + consumer-side verification of every chunk — of the
proposed mechanism, compared with the three alternatives it rejected, as the
number of content chunks grows?

Schemes (all REALLY executed on identical chunk data)
-----------------------------------------------------
rsa      : RSA-2048 PSS baseline (classic PKI auth, no blockchain).
           Publisher/chunk: SHA-256 hash + AES-256-GCM encrypt + RSA sign(hash).
           Consumer/chunk : RSA verify + AES decrypt + re-hash compare.
ecdsa    : ECC baseline (ECDSA-P256, no blockchain).  Same structure, ECDSA
           sign/verify instead of RSA.
existing : Existing blockchain-ICN approach — per-chunk hash anchored
           on-chain.  Publisher/chunk: hash + encrypt + ONE REAL Fabric write
           tx registering the chunk hash.  Consumer/chunk: ONE REAL ledger
           query (Evaluate) + hash compare + decrypt + re-hash.
proposed : The implemented mechanism, real pipeline end-to-end:
           Publisher: per-chunk hash + encrypt + Ed25519 sign(hash);
           build_merkle_tree; 2 real txs (register_content_root +
           store_merkle_tree) — exactly content.publish_content() Step 4.5.
           Consumer/chunk: the full verification chain from
           network_scenario (_get_merkle_proof_for_chunk +
           _verify_chunk_proof + decrypt/re-hash): get_merkle_tree (real
           Evaluate) + proof gen + get_content_root (Evaluate) + proof verify
           + get_producer_key (Evaluate) + Ed25519 verify + decrypt + re-hash.

Chunk bytes come from the system's own synthesiser
(content._synthetic_chunk_bytes); crypto functions for the proposed scheme
are the UNMODIFIED app/crypto_auth.py ones.  RSA/ECDSA baselines exist only
inside this instrumentation file (the simulator deliberately has no RSA) and
use the same `cryptography` library the app uses.

Every component time is time.perf_counter around one real operation; run
totals are sums of the same run's measured components.  Key generation is
measured and reported separately (setup, one-time per producer) and is NOT
included in per-content totals.  Nothing is estimated.

Usage (from app/ so .env credential paths resolve; Fabric must be running):
    python ../benchmark/instrumentation/milestone5_security_overhead.py
"""

from __future__ import annotations

import argparse
import csv
import time
import uuid
from statistics import fmean, pstdev

import matplotlib.pyplot as plt

from cryptography.hazmat.primitives import hashes as _hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# Real, unmodified app modules.
import crypto_auth
from content import _synthetic_chunk_bytes
from fabric.chain import FabricLedger

DEFAULT_CHUNK_COUNTS = [10, 20, 40, 80, 160]
CRYPTO_REPS  = 5   # rsa / ecdsa (compute-only, cheap)
PROPOSED_REPS = 3  # 2 real txs per rep
EXISTING_REPS = 1  # N real txs per rep — expensive by design

RUNS_CSV    = DATA_DIR / "m5_security_overhead_runs.csv"
SUMMARY_CSV = DATA_DIR / "m5_security_overhead_summary.csv"
FIG_STEM    = "graph5_security_overhead_comparison"

COMPONENTS = ["publisher_compute_ms", "chain_write_ms", "chain_read_ms",
              "consumer_compute_ms"]


def _t(fn, *args, **kwargs):
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return (time.perf_counter() - t0) * 1000.0, result


def _chunks(content_id: str, n: int) -> list[bytes]:
    return [_synthetic_chunk_bytes(content_id, i) for i in range(n)]


# ---------------------------------------------------------------------------
# Scheme runners — each returns one run record with measured components.
# ---------------------------------------------------------------------------

def run_rsa(content_id: str, n: int) -> dict:
    keygen_ms, priv = _t(rsa.generate_private_key, 65537, 2048)
    pub = priv.public_key()
    pss = padding.PSS(mgf=padding.MGF1(_hashes.SHA256()),
                      salt_length=padding.PSS.MAX_LENGTH)

    pub_ms = wr_ms = rd_ms = con_ms = 0.0
    for chunk in _chunks(content_id, n):
        ms, h = _t(crypto_auth.chunk_hash, chunk); pub_ms += ms
        ms, (ct, key, nonce) = _t(crypto_auth.encrypt_chunk, chunk); pub_ms += ms
        ms, sig = _t(priv.sign, h.encode(), pss, _hashes.SHA256()); pub_ms += ms

        def _verify():
            pub.verify(sig, h.encode(), pss, _hashes.SHA256()); return True
        ms, ok = _t(_verify); con_ms += ms
        assert ok
        ms, pt = _t(crypto_auth.decrypt_chunk, ct, key, nonce); con_ms += ms
        ms, h2 = _t(crypto_auth.chunk_hash, pt); con_ms += ms
        assert h2 == h
    return {"scheme": "rsa", "keygen_ms": keygen_ms,
            "publisher_compute_ms": pub_ms, "chain_write_ms": wr_ms,
            "chain_read_ms": rd_ms, "consumer_compute_ms": con_ms,
            "tx_count": 0, "query_count": 0}


def run_ecdsa(content_id: str, n: int) -> dict:
    keygen_ms, priv = _t(ec.generate_private_key, ec.SECP256R1())
    pub = priv.public_key()

    pub_ms = wr_ms = rd_ms = con_ms = 0.0
    for chunk in _chunks(content_id, n):
        ms, h = _t(crypto_auth.chunk_hash, chunk); pub_ms += ms
        ms, (ct, key, nonce) = _t(crypto_auth.encrypt_chunk, chunk); pub_ms += ms
        ms, sig = _t(priv.sign, h.encode(), ec.ECDSA(_hashes.SHA256())); pub_ms += ms

        def _verify():
            pub.verify(sig, h.encode(), ec.ECDSA(_hashes.SHA256())); return True
        ms, ok = _t(_verify); con_ms += ms
        assert ok
        ms, pt = _t(crypto_auth.decrypt_chunk, ct, key, nonce); con_ms += ms
        ms, h2 = _t(crypto_auth.chunk_hash, pt); con_ms += ms
        assert h2 == h
    return {"scheme": "ecdsa", "keygen_ms": keygen_ms,
            "publisher_compute_ms": pub_ms, "chain_write_ms": wr_ms,
            "chain_read_ms": rd_ms, "consumer_compute_ms": con_ms,
            "tx_count": 0, "query_count": 0}


def run_existing(ledger: FabricLedger, content_id: str, n: int) -> dict:
    """Existing blockchain-ICN: per-chunk on-chain hash anchor."""
    pub_ms = wr_ms = rd_ms = con_ms = 0.0
    tx = q = 0
    enc = []
    for i, chunk in enumerate(_chunks(content_id, n)):
        ms, h = _t(crypto_auth.chunk_hash, chunk); pub_ms += ms
        ms, (ct, key, nonce) = _t(crypto_auth.encrypt_chunk, chunk); pub_ms += ms
        ms, _ = _t(ledger.register_content_root, f"{content_id}:chunk{i}", h)
        wr_ms += ms; tx += 1                                # real write tx
        enc.append((h, ct, key, nonce))
        if (i + 1) % 20 == 0:
            print(f"[m5]   existing n={n}: {i + 1}/{n} chunks registered")

    for i, (h, ct, key, nonce) in enumerate(enc):
        ms, onchain = _t(ledger.get_content_root, f"{content_id}:chunk{i}")
        rd_ms += ms; q += 1                                 # real ledger query
        ms, pt = _t(crypto_auth.decrypt_chunk, ct, key, nonce); con_ms += ms
        ms, h2 = _t(crypto_auth.chunk_hash, pt); con_ms += ms
        assert h2 == h == onchain
    return {"scheme": "existing", "keygen_ms": 0.0,
            "publisher_compute_ms": pub_ms, "chain_write_ms": wr_ms,
            "chain_read_ms": rd_ms, "consumer_compute_ms": con_ms,
            "tx_count": tx, "query_count": q}


def run_proposed(ledger: FabricLedger, content_id: str, n: int) -> dict:
    """The implemented mechanism — publish + full per-chunk verification."""
    keygen_ms, (priv, pub_bytes) = _t(crypto_auth.generate_producer_keypair)
    producer_id = f"{content_id}-producer"
    ms, _ = _t(ledger.register_producer, producer_id, pub_bytes)
    producer_reg_ms = ms   # one-time identity tx, reported separately

    pub_ms = wr_ms = rd_ms = con_ms = 0.0
    tx = q = 0
    enc = []
    hashes = []
    for chunk in _chunks(content_id, n):
        ms, h = _t(crypto_auth.chunk_hash, chunk); pub_ms += ms
        ms, (ct, key, nonce) = _t(crypto_auth.encrypt_chunk, chunk); pub_ms += ms
        ms, sig = _t(crypto_auth.sign_chunk, priv, h); pub_ms += ms
        hashes.append(h)
        enc.append((h, ct, key, nonce, sig))

    ms, (root, tree_levels) = _t(crypto_auth.build_merkle_tree, hashes)
    pub_ms += ms
    ms, _ = _t(ledger.register_content_root, content_id, root)
    wr_ms += ms; tx += 1                                    # real write tx
    ms, _ = _t(ledger.store_merkle_tree, content_id, tree_levels)
    wr_ms += ms; tx += 1                                    # real write tx

    for i, (h, ct, key, nonce, sig) in enumerate(enc):
        ms, tree = _t(ledger.get_merkle_tree, content_id); rd_ms += ms; q += 1
        ms, proof = _t(crypto_auth.get_merkle_proof, tree, i); con_ms += ms
        ms, onroot = _t(ledger.get_content_root, content_id); rd_ms += ms; q += 1
        ms, ok = _t(crypto_auth.verify_merkle_proof, h, proof, onroot); con_ms += ms
        assert ok
        ms, pkey = _t(ledger.get_producer_key, producer_id); rd_ms += ms; q += 1
        ms, ok = _t(crypto_auth.verify_chunk_signature, pkey, h, sig); con_ms += ms
        assert ok
        ms, pt = _t(crypto_auth.decrypt_chunk, ct, key, nonce); con_ms += ms
        ms, h2 = _t(crypto_auth.chunk_hash, pt); con_ms += ms
        assert h2 == h
    return {"scheme": "proposed", "keygen_ms": keygen_ms,
            "producer_reg_ms": producer_reg_ms,
            "publisher_compute_ms": pub_ms, "chain_write_ms": wr_ms,
            "chain_read_ms": rd_ms, "consumer_compute_ms": con_ms,
            "tx_count": tx, "query_count": q}


# ---------------------------------------------------------------------------

def summarize(runs: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = {}
    for r in runs:
        grouped.setdefault((r["scheme"], r["chunk_count"]), []).append(r)

    out = []
    for (scheme, n), group in sorted(grouped.items()):
        totals = [r["total_ms"] for r in group]
        row = {"scheme": scheme, "chunk_count": n, "runs": len(group),
               "mean_total_ms": fmean(totals),
               "std_total_ms": pstdev(totals) if len(totals) > 1 else 0.0,
               "tx_count": group[0]["tx_count"],
               "query_count": group[0]["query_count"]}
        for c in COMPONENTS:
            row[f"mean_{c}"] = fmean([r[c] for r in group])
        out.append(row)
    return out


def write_csv(path, rows: list[dict]) -> None:
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"[m5] wrote {path} ({len(rows)} rows)")


def plot(summary: list[dict], chunk_counts: list[int]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    style = {
        "rsa":      ("RSA-2048 authentication (no blockchain)",   "o", "#E91E63"),
        "ecdsa":    ("ECC / ECDSA-P256 authentication (no blockchain)", "s", "#FF9800"),
        "existing": ("Existing blockchain-ICN (per-chunk on-chain)", "^", "#7B1FA2"),
        "proposed": ("Proposed (Merkle root + Ed25519 + Fabric)",  "D", "#1B5E20"),
    }

    # ── Panel A: total measured security overhead vs chunk count ─────────
    for scheme, (label, marker, color) in style.items():
        pts = sorted([r for r in summary if r["scheme"] == scheme],
                     key=lambda r: r["chunk_count"])
        xs = [r["chunk_count"] for r in pts]
        ys = [r["mean_total_ms"] for r in pts]
        yerr = [r["std_total_ms"] for r in pts]
        ax_a.errorbar(xs, ys, yerr=yerr, marker=marker, color=color,
                      capsize=3, label=label)
    ax_a.set_yscale("log")
    ax_a.set_xlabel("Number of content chunks")
    ax_a.set_ylabel("Total security overhead (ms, log scale)")
    ax_a.set_title("(a) Total security overhead per content object\n"
                   "(publish + register + verify all chunks)")
    ax_a.legend(fontsize=8.5)

    # ── Panel B: composition (%) of the overhead at the largest N ────────
    n_max = max(chunk_counts)
    comp_style = [
        ("mean_publisher_compute_ms", "Publisher compute (hash/encrypt/sign/Merkle)", "#90CAF9"),
        ("mean_chain_write_ms",       "Blockchain writes (registration txs)",         "#7B1FA2"),
        ("mean_chain_read_ms",        "Blockchain reads (verification queries)",      "#CE93D8"),
        ("mean_consumer_compute_ms",  "Consumer compute (verify/decrypt/re-hash)",    "#FB8C00"),
    ]
    order = ["rsa", "ecdsa", "existing", "proposed"]
    xs = range(len(order))
    bottoms = [0.0] * len(order)
    rows_max = {r["scheme"]: r for r in summary if r["chunk_count"] == n_max}
    totals = {s: sum(rows_max[s][k] for k, _, _ in comp_style) for s in order}
    for key, label, color in comp_style:
        vals = [100.0 * rows_max[s][key] / totals[s] for s in order]
        ax_b.bar(list(xs), vals, 0.55, bottom=bottoms, label=label, color=color)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    for i, s in enumerate(order):
        t = rows_max[s]["mean_total_ms"]
        txt = f"{t/1000:.1f} s" if t >= 1000 else f"{t:.1f} ms"
        ax_b.annotate(f"total\n{txt}", (i, 102), ha="center", fontsize=8.5)
    ax_b.set_ylim(0, 116)
    ax_b.set_xticks(list(xs))
    ax_b.set_xticklabels([style[s][0].split(" (")[0] for s in order],
                         fontsize=8.5)
    ax_b.set_ylabel("Share of measured overhead (%)")
    ax_b.set_title(f"(b) Composition of total security overhead at N = {n_max} chunks\n"
                   "(percentages of measured component times)")
    ax_b.legend(fontsize=8.5, loc="center left")

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m5] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 5: security overhead comparison")
    parser.add_argument("--chunk-counts", type=int, nargs="+", default=DEFAULT_CHUNK_COUNTS)
    args = parser.parse_args()

    ensure_dirs()
    run_id = uuid.uuid4().hex[:8]
    ledger = FabricLedger()
    runs: list[dict] = []
    try:
        for n in args.chunk_counts:
            for rep in range(CRYPTO_REPS):
                for runner in (run_rsa, run_ecdsa):
                    cid = f"m5-{run_id}-{runner.__name__[4:]}-n{n}-r{rep}"
                    t0 = time.perf_counter()
                    rec = runner(cid, n)
                    rec["total_ms"] = sum(rec[c] for c in COMPONENTS)
                    rec.update({"chunk_count": n, "rep": rep,
                                "wall_ms": (time.perf_counter() - t0) * 1000.0})
                    runs.append(rec)
            print(f"[m5] rsa/ecdsa    n={n:>4}: {CRYPTO_REPS} reps done")

            for rep in range(PROPOSED_REPS):
                cid = f"m5-{run_id}-prop-n{n}-r{rep}"
                rec = run_proposed(ledger, cid, n)
                rec["total_ms"] = sum(rec[c] for c in COMPONENTS)
                rec.update({"chunk_count": n, "rep": rep})
                runs.append(rec)
                print(f"[m5] proposed     n={n:>4} rep={rep}: "
                      f"{rec['total_ms']/1000:.1f}s ({rec['tx_count']} tx, "
                      f"{rec['query_count']} queries)")

            for rep in range(EXISTING_REPS):
                cid = f"m5-{run_id}-exist-n{n}-r{rep}"
                rec = run_existing(ledger, cid, n)
                rec["total_ms"] = sum(rec[c] for c in COMPONENTS)
                rec.update({"chunk_count": n, "rep": rep})
                runs.append(rec)
                print(f"[m5] existing     n={n:>4}: "
                      f"{rec['total_ms']/1000:.1f}s ({rec['tx_count']} tx, "
                      f"{rec['query_count']} queries)")
    finally:
        ledger.close()

    write_csv(RUNS_CSV, runs)
    summary = summarize(runs)
    write_csv(SUMMARY_CSV, summary)
    plot(summary, args.chunk_counts)
    print("[m5] done")


if __name__ == "__main__":
    main()
