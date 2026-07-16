"""
Milestone 6 — Graph 6: Key Management Overhead.

Research question
-----------------
What does the implemented per-chunk-key design (content.publish_content /
crypto_auth.encrypt_chunk: a fresh AES-256 key per chunk) cost in managed
keys and key-store memory, compared with the two standard alternatives —
chunk-group keys and one session key per content — and what does that cost
buy in compromise containment?

Strategies (every chunk of every strategy is REALLY encrypted; sizes are
measured from the real serialised artifacts)
--------------------------------------------
per_chunk : the implemented scheme.  Chunks encrypted with
            crypto_auth.encrypt_chunk (fresh key+nonce each), wrapped into
            real ChunkRecords, and the key-distribution artifact is the real
            crypto_auth.build_manifest() output (hash + locator + key per
            chunk), ECIES-wrapped with wrap_manifest_for_consumer — the
            actual protocol artifacts.
group     : one AES-256 key per group of GROUP_SIZE chunks, fresh 12-byte
            nonce per chunk (GCM nonce reuse under one key is forbidden).
            Manifest: per-chunk {hash, locator, group_id} + group key table.
session   : one AES-256 key for the whole content, fresh nonce per chunk.
            Manifest: per-chunk {hash, locator} + the single key.

Measured quantities (all from actual execution)
-----------------------------------------------
- managed_keys       : count of DISTINCT keys actually used to encrypt.
- manifest_bytes     : len() of the real serialised (JSON) key-distribution
                       manifest for the strategy.
- wrapped_bytes      : len() of the real ECIES-wrapped manifest
                       (crypto_auth.wrap_manifest_for_consumer).
- key_material_bytes : bytes of raw key material managed (measured as the
                       sum of len() of the actual key byte strings).
- blast_radius_chunks: COMPROMISE EXPERIMENT — leak the first key of the
                       strategy's key store, then attempt a real AES-GCM
                       decryption of EVERY chunk ciphertext with it; count
                       the chunks that actually decrypt (InvalidTag = safe).
- keygen/encrypt times: measured, recorded in the CSV (not plotted).

Chunk bytes come from the system's own synthesiser
(content._synthetic_chunk_bytes).  Nothing is estimated.

Usage (from repo root or app/):
    python benchmark/instrumentation/milestone6_key_management.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time

import matplotlib.pyplot as plt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# Real, unmodified app modules.
import crypto_auth
from content import _synthetic_chunk_bytes
from models import ChunkRecord

DEFAULT_CHUNK_COUNTS = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
GROUP_SIZE = 16

RAW_CSV  = DATA_DIR / "m6_key_management_raw.csv"
FIG_STEM = "graph6_key_management_overhead"


def run_per_chunk(content_id: str, n: int) -> dict:
    """The implemented scheme: real pipeline artifacts end-to-end."""
    t0 = time.perf_counter()
    records: list[ChunkRecord] = []
    for i in range(n):
        chunk = _synthetic_chunk_bytes(content_id, i)
        h = crypto_auth.chunk_hash(chunk)
        ct, key, nonce = crypto_auth.encrypt_chunk(chunk)   # fresh key per chunk
        records.append(ChunkRecord(
            chunk_id=i, chunk_hash=h, chunk_locator=f"{content_id}:{i}",
            chunk_key=key, nonce=nonce, ciphertext=ct))
    encrypt_ms = (time.perf_counter() - t0) * 1000.0

    manifest = crypto_auth.build_manifest(records)          # real protocol artifact
    manifest_bytes = json.dumps(manifest).encode()
    _priv, cons_pub = crypto_auth.generate_consumer_keypair()
    wrapped = crypto_auth.wrap_manifest_for_consumer(manifest_bytes, cons_pub)

    keys = [r.chunk_key for r in records]
    ciphertexts = [(r.ciphertext, r.nonce) for r in records]
    return {
        "strategy": "per_chunk", "managed_keys": len(set(keys)),
        "manifest_bytes": len(manifest_bytes), "wrapped_bytes": len(wrapped),
        "key_material_bytes": sum(len(k) for k in set(keys)),
        "encrypt_ms": encrypt_ms,
        "_keys": keys, "_ciphertexts": ciphertexts,
    }


def run_grouped(content_id: str, n: int, group_size: int) -> dict:
    """Group-key baseline: one real AES key per group, real encryptions."""
    t0 = time.perf_counter()
    group_keys = [os.urandom(32) for _ in range((n + group_size - 1) // group_size)]
    entries, ciphertexts, chunk_keys = [], [], []
    for i in range(n):
        chunk = _synthetic_chunk_bytes(content_id, i)
        h = crypto_auth.chunk_hash(chunk)
        key = group_keys[i // group_size]
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, chunk, None)        # real encryption
        entries.append({"chunk_hash": h, "chunk_locator": f"{content_id}:{i}",
                        "group_id": i // group_size})
        ciphertexts.append((ct, nonce))
        chunk_keys.append(key)
    encrypt_ms = (time.perf_counter() - t0) * 1000.0

    manifest = {"entries": entries,
                "group_keys": {str(g): k.hex() for g, k in enumerate(group_keys)}}
    manifest_bytes = json.dumps(manifest).encode()
    _priv, cons_pub = crypto_auth.generate_consumer_keypair()
    wrapped = crypto_auth.wrap_manifest_for_consumer(manifest_bytes, cons_pub)

    return {
        "strategy": "group", "managed_keys": len(group_keys),
        "manifest_bytes": len(manifest_bytes), "wrapped_bytes": len(wrapped),
        "key_material_bytes": sum(len(k) for k in group_keys),
        "encrypt_ms": encrypt_ms,
        "_keys": chunk_keys, "_ciphertexts": ciphertexts,
    }


def run_session(content_id: str, n: int) -> dict:
    """Session-key baseline: one real AES key for the whole content."""
    t0 = time.perf_counter()
    session_key = os.urandom(32)
    entries, ciphertexts = [], []
    for i in range(n):
        chunk = _synthetic_chunk_bytes(content_id, i)
        h = crypto_auth.chunk_hash(chunk)
        nonce = os.urandom(12)
        ct = AESGCM(session_key).encrypt(nonce, chunk, None)  # real encryption
        entries.append({"chunk_hash": h, "chunk_locator": f"{content_id}:{i}"})
        ciphertexts.append((ct, nonce))
    encrypt_ms = (time.perf_counter() - t0) * 1000.0

    manifest = {"entries": entries, "session_key": session_key.hex()}
    manifest_bytes = json.dumps(manifest).encode()
    _priv, cons_pub = crypto_auth.generate_consumer_keypair()
    wrapped = crypto_auth.wrap_manifest_for_consumer(manifest_bytes, cons_pub)

    return {
        "strategy": "session", "managed_keys": 1,
        "manifest_bytes": len(manifest_bytes), "wrapped_bytes": len(wrapped),
        "key_material_bytes": len(session_key),
        "encrypt_ms": encrypt_ms,
        "_keys": [session_key] * n, "_ciphertexts": ciphertexts,
    }


def blast_radius(rec: dict) -> int:
    """
    Compromise experiment: leak the FIRST key of the strategy's key store and
    attempt a REAL AES-GCM decryption of every chunk ciphertext with it.
    Returns the number of chunks that actually decrypted.
    """
    leaked = AESGCM(rec["_keys"][0])
    decrypted = 0
    for ct, nonce in rec["_ciphertexts"]:
        try:
            leaked.decrypt(nonce, ct, None)
            decrypted += 1
        except InvalidTag:
            pass                                            # key does not open this chunk
    return decrypted


def write_csv(path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[m6] wrote {path} ({len(rows)} rows)")


def plot(rows: list[dict], chunk_counts: list[int]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    style = {
        "per_chunk": (f"One key per chunk (implemented)",           "#1B5E20"),
        "group":     (f"Chunk-group key (group size {GROUP_SIZE})", "#FF9800"),
        "session":   ("One session key per content",                "#E91E63"),
    }

    def get(n, strategy, field):
        for r in rows:
            if r["chunk_count"] == n and r["strategy"] == strategy:
                return r[field]
        raise KeyError((n, strategy, field))

    # ── Panel A: managed keys (left, log) + key-store memory (right) ─────
    ax_mem = ax_a.twinx()
    for strategy, (label, color) in style.items():
        ks = [get(n, strategy, "managed_keys") for n in chunk_counts]
        ax_a.plot(chunk_counts, ks, marker="o", color=color,
                  label=f"{label} — managed keys")
        mem = [get(n, strategy, "manifest_bytes") / 1024.0 for n in chunk_counts]
        ax_mem.plot(chunk_counts, mem, marker="s", linestyle="--", color=color,
                    alpha=0.6, label=f"{label} — manifest KB")
    ax_a.set_yscale("log")
    ax_a.set_xlabel("Number of content chunks")
    ax_a.set_ylabel("Managed keys (count, log scale) — solid")
    ax_mem.set_ylabel("Key-distribution manifest size (KB) — dashed")
    ax_mem.grid(False)
    la, lla = ax_a.get_legend_handles_labels()
    lm, llm = ax_mem.get_legend_handles_labels()
    ax_a.legend(la + lm, lla + llm, fontsize=7.5, loc="upper left")
    ax_a.set_title("(a) Key management overhead vs. number of chunks\n"
                   "(measured from real key stores and manifests)")

    # ── Panel B: measured compromise blast radius at max N ───────────────
    n_max = max(chunk_counts)
    order = ["session", "group", "per_chunk"]
    vals = [get(n_max, s, "blast_radius_chunks") for s in order]
    colors = [style[s][1] for s in order]
    bars = ax_b.bar(range(len(order)), vals, 0.55, color=colors)
    for b, v in zip(bars, vals):
        ax_b.annotate(f"{v:,} chunk{'s' if v != 1 else ''}",
                      (b.get_x() + b.get_width() / 2, v),
                      textcoords="offset points", xytext=(0, 4),
                      ha="center", fontsize=9)
    ax_b.set_yscale("log")
    ax_b.set_xticks(range(len(order)))
    ax_b.set_xticklabels([style[s][0].split(" — ")[0] for s in order], fontsize=9)
    ax_b.set_ylabel(f"Chunks actually decrypted with ONE leaked key (of {n_max:,})")
    ax_b.set_title(f"(b) Measured compromise blast radius at N = {n_max:,} chunks\n"
                   "(real decryption attempts with a single leaked key)")

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m6] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 6: key management overhead")
    parser.add_argument("--chunk-counts", type=int, nargs="+", default=DEFAULT_CHUNK_COUNTS)
    args = parser.parse_args()

    ensure_dirs()
    rows: list[dict] = []
    for n in args.chunk_counts:
        cid = f"m6-n{n}"
        for runner in (run_per_chunk,
                       lambda c, k: run_grouped(c, k, GROUP_SIZE),
                       run_session):
            rec = runner(cid, n)
            rec["chunk_count"] = n
            rec["blast_radius_chunks"] = blast_radius(rec)   # real decrypt attempts
            rec.pop("_keys"); rec.pop("_ciphertexts")
            rows.append(rec)
            print(f"[m6] n={n:>5} {rec['strategy']:<10} keys={rec['managed_keys']:>5} "
                  f"manifest={rec['manifest_bytes']:>8,}B "
                  f"blast={rec['blast_radius_chunks']:>5}")

    write_csv(RAW_CSV, rows)
    plot(rows, args.chunk_counts)
    print("[m6] done")


if __name__ == "__main__":
    main()
