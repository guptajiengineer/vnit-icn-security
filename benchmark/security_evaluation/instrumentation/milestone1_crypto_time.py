"""
Milestone 1 (rework) — Graph 1: Cryptographic Processing Time of the
PROPOSED security mechanism.

What is measured
----------------
Not library primitives in isolation, but the per-chunk code paths exactly as
the proposed protocol composes them (app/content.py publish_content() on the
publisher side; app/network_scenario.py _verify_chunk_proof() +
_consumer_verify_chunk() on the receiver side).  All functions are imported
UNMODIFIED from app/crypto_auth.py.

Per repetition, each individual component is timed with time.perf_counter()
around one real execution on a fresh os.urandom payload:

  Publisher-side components
    hash          : chunk_hash(chunk)                       (SHA-256, Step 2.5)
    encrypt       : encrypt_chunk(chunk)                    (AES-256-GCM, Step 3)
    sign          : sign_chunk(priv, hash)                  (Ed25519 over the 32-byte
                                                             hash — Step 4; NOT over
                                                             the payload)
    merkle_build  : build_merkle_tree(16 real leaf hashes)  (Step 4.5, per content)

  Receiver-side components
    proof_gen     : get_merkle_proof(tree, idx)             (serving node, _send_data)
    proof_verify  : verify_merkle_proof(hash, proof, root)  (_verify_chunk_proof)
    sig_verify    : verify_chunk_signature(pub, hash, sig)  (_verify_chunk_proof)
    decrypt       : decrypt_chunk(ct, key, nonce)           (_consumer_verify_chunk)
    rehash        : chunk_hash(plaintext)                   (_consumer_verify_chunk)

  Contrast baseline (the design the mechanism deliberately avoids)
    naive_sign    : Ed25519 sign(raw chunk bytes)           (sign-the-payload)
    naive_verify  : Ed25519 verify(raw chunk bytes)

Graph 1 curves (panel A) are per-repetition sums of components measured in the
SAME repetition, matching the protocol's composition:

  Encryption (publisher)        = hash + encrypt
  Decryption (consumer)         = decrypt + rehash
  Signature Generation          = sign                       → flat in chunk size
  Signature Verification        = proof_gen + proof_verify + sig_verify
                                                             → flat in chunk size
  Naive payload sign / verify   = contrast curves            → grow with chunk size

Panel B stacks the measured per-chunk component costs into total publisher-side
and receiver-side pipeline cost per chunk size.  The Merkle tree is built once
per content (16 chunks here); its measured build time is shown amortized
(÷ 16) and labelled as such — the only arithmetic applied to any measurement
besides mean/std.

Chunk sizes: 64, 128, 256, 512, 1024 KB (docs/graphs_notes.md, Graph 1).
Every CSV row is one actual timed execution.  Nothing is estimated.

Usage (from repo root):
    python benchmark/instrumentation/milestone1_crypto_time.py [--repetitions 200]
"""

from __future__ import annotations

import argparse
import csv
import os
import time
from statistics import fmean, pstdev

import matplotlib.pyplot as plt

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# App imports (path set up by common.py) — the real, unmodified module.
import crypto_auth

CHUNK_SIZES_KB     = [64, 128, 256, 512, 1024]
CHUNKS_PER_CONTENT = 16   # leaves in the per-content Merkle tree

RAW_CSV     = DATA_DIR / "m1_crypto_time_raw.csv"
SUMMARY_CSV = DATA_DIR / "m1_crypto_time_summary.csv"
FIG_STEM    = "graph1_crypto_processing_time"

# Component → which side of the pipeline it belongs to (for panel B).
PUBLISHER_COMPONENTS = ["hash", "encrypt", "sign"]          # + amortized merkle_build
RECEIVER_COMPONENTS  = ["proof_gen", "proof_verify", "sig_verify", "decrypt", "rehash"]

# Curve definitions (panel A): curve name → list of components summed
# per-repetition.  Composition mirrors the protocol code paths.
CURVES = {
    "encryption_publisher":       ["hash", "encrypt"],
    "decryption_consumer":        ["decrypt", "rehash"],
    "signature_generation":       ["sign"],
    "signature_verification":     ["proof_gen", "proof_verify", "sig_verify"],
    "naive_payload_signature":    ["naive_sign"],
    "naive_payload_verification": ["naive_verify"],
}


def _timed(fn, *args, **kwargs):
    """Run fn(*args) once; return (elapsed_ms, result)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    t1 = time.perf_counter()
    return (t1 - t0) * 1000.0, result


def measure(repetitions: int) -> list[dict]:
    """
    One raw CSV row per repetition per chunk size, holding every measured
    component time (ms) for that repetition.
    """
    rows: list[dict] = []
    priv, pub_bytes = crypto_auth.generate_producer_keypair()
    pub_key_obj = None  # built lazily for the naive-verify baseline

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    pub_key_obj = Ed25519PublicKey.from_public_bytes(pub_bytes)

    for size_kb in CHUNK_SIZES_KB:
        size_bytes = size_kb * 1024

        # Sibling chunks for the per-content Merkle tree: 15 REAL chunks of
        # this size, generated and hashed once per size (they are context, not
        # the measured subject — the target chunk is fresh every repetition).
        sibling_hashes = [
            crypto_auth.chunk_hash(os.urandom(size_bytes))
            for _ in range(CHUNKS_PER_CONTENT - 1)
        ]

        for rep in range(repetitions):
            chunk = os.urandom(size_bytes)
            leaf_index = rep % CHUNKS_PER_CONTENT
            t: dict[str, float] = {}

            # ── Publisher side ────────────────────────────────────────────
            t["hash"], h = _timed(crypto_auth.chunk_hash, chunk)

            t["encrypt"], (ciphertext, key, nonce) = _timed(
                crypto_auth.encrypt_chunk, chunk
            )

            t["sign"], signature = _timed(crypto_auth.sign_chunk, priv, h)

            leaf_hashes = list(sibling_hashes)
            leaf_hashes.insert(leaf_index, h)
            t["merkle_build"], (root, tree_levels) = _timed(
                crypto_auth.build_merkle_tree, leaf_hashes
            )

            # ── Serving / receiver side ───────────────────────────────────
            t["proof_gen"], proof = _timed(
                crypto_auth.get_merkle_proof, tree_levels, leaf_index
            )

            t["proof_verify"], proof_ok = _timed(
                crypto_auth.verify_merkle_proof, h, proof, root
            )
            assert proof_ok  # real verification succeeded (outside timing)

            t["sig_verify"], sig_ok = _timed(
                crypto_auth.verify_chunk_signature, pub_bytes, h, signature
            )
            assert sig_ok

            t["decrypt"], plaintext = _timed(
                crypto_auth.decrypt_chunk, ciphertext, key, nonce
            )
            t["rehash"], h2 = _timed(crypto_auth.chunk_hash, plaintext)
            assert h2 == h  # real round-trip integrity (outside timing)

            # ── Contrast baseline: sign/verify the RAW PAYLOAD ────────────
            t["naive_sign"], naive_sig = _timed(priv.sign, chunk)

            def _naive_verify():
                pub_key_obj.verify(naive_sig, chunk)
                return True
            t["naive_verify"], _ = _timed(_naive_verify)

            rows.append({"chunk_size_kb": size_kb, "repetition": rep, **t})

        print(f"[m1] {size_kb:>5} KB — {repetitions} repetitions done")

    return rows


def summarize(rows: list[dict]) -> list[dict]:
    """
    Mean/std per (chunk_size, metric).  Metrics are every measured component
    plus each composed curve (per-repetition sum of that repetition's
    measured components).
    """
    component_names = [k for k in rows[0] if k not in ("chunk_size_kb", "repetition")]

    grouped: dict[tuple, list[float]] = {}
    for r in rows:
        for name in component_names:
            grouped.setdefault((r["chunk_size_kb"], "component", name), []).append(r[name])
        for curve, parts in CURVES.items():
            grouped.setdefault((r["chunk_size_kb"], "curve", curve), []).append(
                sum(r[p] for p in parts)
            )

    summary = []
    for (size_kb, kind, name), values in sorted(grouped.items()):
        summary.append({
            "chunk_size_kb": size_kb,
            "kind":          kind,
            "metric":        name,
            "samples":       len(values),
            "mean_time_ms":  fmean(values),
            "std_time_ms":   pstdev(values),
            "min_time_ms":   min(values),
            "max_time_ms":   max(values),
        })
    return summary


def write_csv(path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[m1] wrote {path} ({len(rows)} rows)")


def _curve_points(summary: list[dict], curve: str):
    pts = [r for r in summary if r["kind"] == "curve" and r["metric"] == curve]
    pts.sort(key=lambda r: r["chunk_size_kb"])
    return ([r["chunk_size_kb"] for r in pts],
            [r["mean_time_ms"] for r in pts],
            [r["std_time_ms"] for r in pts])


def _component_mean(summary: list[dict], size_kb: int, name: str) -> float:
    for r in summary:
        if (r["kind"] == "component" and r["metric"] == name
                and r["chunk_size_kb"] == size_kb):
            return r["mean_time_ms"]
    raise KeyError((size_kb, name))


def plot(summary: list[dict]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    # ── Panel A: protocol-composed curves + naive-baseline contrast ──────
    style = {
        "encryption_publisher":       ("Encryption  (SHA-256 + AES-256-GCM)",        "o", "-",  "#2196F3"),
        "decryption_consumer":        ("Decryption  (AES-256-GCM + re-hash)",        "s", "-",  "#FF9800"),
        "signature_generation":       ("Signature Generation  (Ed25519 over hash)",  "^", "-",  "#4CAF50"),
        "signature_verification":     ("Signature Verification  (Merkle proof + Ed25519)", "v", "-", "#E91E63"),
        "naive_payload_signature":    ("Naive baseline: sign raw payload",           "x", "--", "#616161"),
        "naive_payload_verification": ("Naive baseline: verify raw payload",         "+", "--", "#9E9E9E"),
    }
    for curve, (label, marker, ls, color) in style.items():
        xs, ys, yerr = _curve_points(summary, curve)
        ax_a.errorbar(xs, ys, yerr=yerr, marker=marker, linestyle=ls,
                      color=color, capsize=3, label=label)

    ax_a.set_xlabel("Chunk size (KB)")
    ax_a.set_ylabel("Processing time per chunk (ms)")
    ax_a.set_title("(a) Cryptographic processing time — proposed mechanism\n"
                   "vs. naive sign-the-payload baseline")
    ax_a.set_xscale("log", base=2)
    ax_a.set_xticks(CHUNK_SIZES_KB)
    ax_a.set_xticklabels([str(s) for s in CHUNK_SIZES_KB])
    ax_a.legend(fontsize=8.5)

    # ── Panel B: stacked per-chunk pipeline cost, publisher vs receiver ──
    pub_parts = [
        ("hash",         "SHA-256 hash",                        "#90CAF9"),
        ("encrypt",      "AES-256-GCM encrypt",                 "#2196F3"),
        ("sign",         "Ed25519 sign (hash)",                 "#1565C0"),
        ("merkle_amort", f"Merkle build (per-content ÷ {CHUNKS_PER_CONTENT})", "#0D47A1"),
    ]
    rec_parts = [
        ("proof_gen",    "Merkle proof generation",             "#FFCC80"),
        ("proof_verify", "Merkle proof verify",                 "#FFA726"),
        ("sig_verify",   "Ed25519 verify (hash)",               "#F57C00"),
        ("decrypt",      "AES-256-GCM decrypt",                 "#E65100"),
        ("rehash",       "SHA-256 re-hash",                     "#BF360C"),
    ]

    x = range(len(CHUNK_SIZES_KB))
    width = 0.38

    def stack(ax, offsets, parts, side_offset):
        bottoms = [0.0] * len(CHUNK_SIZES_KB)
        for name, label, color in parts:
            vals = []
            for size_kb in CHUNK_SIZES_KB:
                if name == "merkle_amort":
                    v = _component_mean(summary, size_kb, "merkle_build") / CHUNKS_PER_CONTENT
                else:
                    v = _component_mean(summary, size_kb, name)
                vals.append(v)
            ax.bar([i + side_offset for i in x], vals, width,
                   bottom=bottoms, label=label, color=color)
            bottoms = [b + v for b, v in zip(bottoms, vals)]
        return bottoms

    stack(ax_b, x, pub_parts, -width / 2)
    stack(ax_b, x, rec_parts, +width / 2)

    ax_b.set_xticks(list(x))
    ax_b.set_xticklabels([str(s) for s in CHUNK_SIZES_KB])
    ax_b.set_xlabel("Chunk size (KB)  —  left bar: publisher, right bar: receiver")
    ax_b.set_ylabel("Total pipeline time per chunk (ms)")
    ax_b.set_title("(b) Per-chunk security pipeline cost by component")
    ax_b.legend(fontsize=8, ncol=1)

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m1] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 1: crypto processing time (protocol-composed)")
    parser.add_argument("--repetitions", type=int, default=200,
                        help="Timed repetitions per chunk size (default 200)")
    args = parser.parse_args()

    ensure_dirs()
    rows = measure(args.repetitions)
    write_csv(RAW_CSV, rows)
    summary = summarize(rows)
    write_csv(SUMMARY_CSV, summary)
    plot(summary)
    print("[m1] done")


if __name__ == "__main__":
    main()
