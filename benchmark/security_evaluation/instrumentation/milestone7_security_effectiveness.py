"""
Milestone 7 — Graph 7: Security Effectiveness.

Research question
-----------------
Does the implemented verification mechanism actually DETECT tampered chunks —
and does it classify correctly overall (no false rejects of clean chunks) —
as the fraction of tampered in-flight chunks grows from 0% to 50%?

Setup (real system, live Fabric ledger)
---------------------------------------
One content object of N chunks is published through the real pipeline:
producer key, Merkle root and tree registered on-chain (real transactions),
manifest ECIES-wrapped for the consumer.  The ledger therefore holds the
LEGITIMATE trust anchors, exactly as in deployment.

Tampering (applied to copies of the in-flight message fields — the ledger and
publisher state are never touched, mirroring an in-network attacker)
--------------------------------------------------------------------
payload_flip : ciphertext bytes flipped (cache-poisoning payload corruption);
               hash/signature/proof fields left untouched.
substitution : full content substitution — attacker's own plaintext, its
               genuine SHA-256 hash, encrypted under the ATTACKER's key
               (the attacker cannot know the manifest chunk key).
sig_forgery  : chunk signature replaced with random 64 bytes.

Tampered chunks are chosen by a seeded RNG (reproducible); each tampered
chunk gets one of the three modes round-robin.

Verification (the real receiver chain, per chunk — code paths of
network_scenario._verify_chunk_proof and _consumer_verify_chunk)
----------------------------------------------------------------
  ledger.get_merkle_tree      (real Fabric Evaluate)  → get_merkle_proof
  ledger.get_content_root     (real Fabric Evaluate)  → verify_merkle_proof
  ledger.get_producer_key     (real Fabric Evaluate)  → verify_chunk_signature
  manifest hash match → decrypt_chunk (AES-GCM tag) → re-hash compare

A chunk is FLAGGED if any stage fails; the first failing stage is recorded.

Metrics (counted from per-chunk outcomes)
-----------------------------------------
detection_rate_pct : flagged∩tampered / tampered × 100   (undefined at 0% —
                     that point is omitted from the curve, never invented)
accuracy_pct       : (true positives + true negatives) / N × 100
                     (also penalises false rejects of clean chunks)

Every CSV row is one actually executed chunk verification.  Nothing is
estimated.

Usage (from app/ so .env credential paths resolve; Fabric must be running):
    python ../benchmark/instrumentation/milestone7_security_effectiveness.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
import uuid
from statistics import fmean

import matplotlib.pyplot as plt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from common import DATA_DIR, apply_style, ensure_dirs, save_fig

# Real, unmodified app modules.
import crypto_auth
from content import _synthetic_chunk_bytes
from fabric.chain import FabricLedger
from models import ChunkRecord

N_CHUNKS       = 200
TAMPER_LEVELS  = [0, 10, 20, 30, 40, 50]      # percent
REPS           = 3
TAMPER_MODES   = ["payload_flip", "substitution", "sig_forgery"]
STAGES         = ["merkle_proof", "signature", "manifest_hash", "decrypt", "rehash"]

RAW_CSV     = DATA_DIR / "m7_security_effectiveness_raw.csv"
SUMMARY_CSV = DATA_DIR / "m7_security_effectiveness_summary.csv"
FIG_STEM    = "graph7_security_effectiveness"


def publish(ledger: FabricLedger, content_id: str):
    """Real publish pipeline: chunks → crypto → on-chain anchors."""
    priv, pub_bytes = crypto_auth.generate_producer_keypair()
    producer_id = f"{content_id}-producer"
    ledger.register_producer(producer_id, pub_bytes)          # real tx

    records: list[ChunkRecord] = []
    hashes: list[str] = []
    for i in range(N_CHUNKS):
        chunk = _synthetic_chunk_bytes(content_id, i)
        h = crypto_auth.chunk_hash(chunk)
        ct, key, nonce = crypto_auth.encrypt_chunk(chunk)
        sig = crypto_auth.sign_chunk(priv, h)
        records.append(ChunkRecord(chunk_id=i, chunk_hash=h,
                                   chunk_locator=f"{content_id}:{i}",
                                   chunk_key=key, nonce=nonce,
                                   ciphertext=ct, chunk_signature=sig))
        hashes.append(h)

    root, tree_levels = crypto_auth.build_merkle_tree(hashes)
    ledger.register_content_root(content_id, root)            # real tx
    ledger.store_merkle_tree(content_id, tree_levels)         # real tx

    manifest = crypto_auth.build_manifest(records)
    consumer_priv, consumer_pub = crypto_auth.generate_consumer_keypair()
    wrapped = crypto_auth.wrap_manifest_for_consumer(
        json.dumps(manifest).encode(), consumer_pub)
    return producer_id, records, wrapped, consumer_priv


def tamper_message(record: ChunkRecord, mode: str) -> dict:
    """Return the tampered in-flight message fields (copies — nothing shared)."""
    msg = {"chunk_hash": record.chunk_hash,
           "ciphertext": record.ciphertext,
           "nonce": record.nonce,
           "signature": record.chunk_signature}
    if mode == "payload_flip":
        ct = bytearray(msg["ciphertext"])
        ct[0] ^= 0xFF                                   # real byte corruption
        msg["ciphertext"] = bytes(ct)
    elif mode == "substitution":
        fake_plain = os.urandom(32)                     # attacker's content
        attacker_key = os.urandom(32)                   # attacker cannot know chunk key
        nonce = os.urandom(12)
        msg["chunk_hash"] = crypto_auth.chunk_hash(fake_plain)
        msg["ciphertext"] = AESGCM(attacker_key).encrypt(nonce, fake_plain, None)
        msg["nonce"] = nonce
    elif mode == "sig_forgery":
        msg["signature"] = os.urandom(64)               # forged signature
    return msg


def verify_chunk(ledger, content_id, producer_id, chunk_id,
                 msg: dict, manifest: list) -> tuple[bool, str, float]:
    """
    The real receiver verification chain.  Returns
    (flagged, first_failing_stage_or_'', elapsed_ms).
    """
    t0 = time.perf_counter()
    flagged, stage = False, ""
    try:
        # Serving node: proof for the requested chunk_id from the ledger tree.
        tree = ledger.get_merkle_tree(content_id)             # real Evaluate
        proof = crypto_auth.get_merkle_proof(tree, chunk_id)

        # _verify_chunk_proof — Merkle then signature.
        root = ledger.get_content_root(content_id)            # real Evaluate
        if not crypto_auth.verify_merkle_proof(msg["chunk_hash"], proof, root):
            flagged, stage = True, "merkle_proof"
        else:
            pkey = ledger.get_producer_key(producer_id)       # real Evaluate
            if not crypto_auth.verify_chunk_signature(
                    pkey, msg["chunk_hash"], msg["signature"]):
                flagged, stage = True, "signature"
            else:
                # _consumer_verify_chunk — manifest hash, decrypt, re-hash.
                entry = manifest[chunk_id]
                if entry["chunk_hash"] != msg["chunk_hash"]:
                    flagged, stage = True, "manifest_hash"
                else:
                    key = bytes.fromhex(entry["chunk_key"])
                    try:
                        plain = crypto_auth.decrypt_chunk(
                            msg["ciphertext"], key, msg["nonce"])
                    except Exception:                          # InvalidTag
                        flagged, stage = True, "decrypt"
                    else:
                        if crypto_auth.chunk_hash(plain) != msg["chunk_hash"]:
                            flagged, stage = True, "rehash"
    except Exception:
        flagged, stage = True, "ledger_error"
    return flagged, stage, (time.perf_counter() - t0) * 1000.0


def summarize(rows: list[dict]) -> list[dict]:
    grouped: dict[int, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r["tamper_pct"], []).append(r)

    out = []
    for pct, group in sorted(grouped.items()):
        tp = sum(1 for r in group if r["tampered"] and r["flagged"])
        fn = sum(1 for r in group if r["tampered"] and not r["flagged"])
        fp = sum(1 for r in group if not r["tampered"] and r["flagged"])
        tn = sum(1 for r in group if not r["tampered"] and not r["flagged"])
        out.append({
            "tamper_pct": pct, "chunks_verified": len(group),
            "tampered": tp + fn, "clean": fp + tn,
            "true_positive": tp, "false_negative": fn,
            "false_positive": fp, "true_negative": tn,
            "detection_rate_pct": (100.0 * tp / (tp + fn)) if (tp + fn) else "",
            "accuracy_pct": 100.0 * (tp + tn) / len(group),
            "mean_verify_ms": fmean([r["verify_ms"] for r in group]),
        })
    return out


def write_csv(path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"[m7] wrote {path} ({len(rows)} rows)")


def plot(summary: list[dict], rows: list[dict]) -> None:
    apply_style()
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(14, 5.5))

    # ── Panel A: detection rate (left) + accuracy (right) ────────────────
    det = [(r["tamper_pct"], r["detection_rate_pct"])
           for r in summary if r["detection_rate_pct"] != ""]
    ax_a.plot([p for p, _ in det], [v for _, v in det],
              marker="o", color="#E91E63", linewidth=2,
              label="Tampered-chunk detection rate")
    ax_a.set_xlabel("Tampered chunks (%)")
    ax_a.set_ylabel("Detection rate (%)")
    ax_a.set_ylim(0, 105)
    ax_a.annotate("0%: no tampered chunks —\ndetection rate undefined",
                  xy=(0, 5), fontsize=8, color="#666666")

    ax_r = ax_a.twinx()
    ax_r.plot([r["tamper_pct"] for r in summary],
              [r["accuracy_pct"] for r in summary],
              marker="s", linestyle="--", color="#1B5E20", linewidth=2,
              label="Content verification accuracy")
    ax_r.set_ylabel("Verification accuracy (%)")
    ax_r.set_ylim(0, 105)
    ax_r.grid(False)

    la, lla = ax_a.get_legend_handles_labels()
    lr, llr = ax_r.get_legend_handles_labels()
    ax_a.legend(la + lr, lla + llr, loc="center right", fontsize=9)
    ax_a.set_title("(a) Tamper detection rate and verification accuracy\n"
                   f"vs. tampered-chunk percentage (N = {N_CHUNKS} chunks × {REPS} runs)")

    # ── Panel B: which defence layer caught each attack type ─────────────
    stage_style = [
        ("merkle_proof",  "Merkle proof vs on-chain root", "#7B1FA2"),
        ("signature",     "Ed25519 producer signature",    "#FF9800"),
        ("manifest_hash", "Manifest hash match",           "#4DB6AC"),
        ("decrypt",       "AES-GCM auth tag (decrypt)",    "#1565C0"),
        ("rehash",        "Plaintext re-hash",             "#BF360C"),
    ]
    tampered_rows = [r for r in rows if r["tampered"]]
    xs = range(len(TAMPER_MODES))
    bottoms = [0.0] * len(TAMPER_MODES)
    for stage, label, color in stage_style:
        vals = [sum(1 for r in tampered_rows
                    if r["tamper_mode"] == m and r["detection_stage"] == stage)
                for m in TAMPER_MODES]
        if any(vals):
            ax_b.bar(list(xs), vals, 0.55, bottom=bottoms, label=label, color=color)
            bottoms = [b + v for b, v in zip(bottoms, vals)]
    missed = [sum(1 for r in tampered_rows
                  if r["tamper_mode"] == m and not r["flagged"])
              for m in TAMPER_MODES]
    if any(missed):
        ax_b.bar(list(xs), missed, 0.55, bottom=bottoms,
                 label="MISSED (undetected)", color="#B71C1C")
    ax_b.set_xticks(list(xs))
    ax_b.set_xticklabels(["Payload bit-flip\n(cache poisoning)",
                          "Full substitution\n(attacker content)",
                          "Signature forgery"], fontsize=9)
    ax_b.set_ylabel("Tampered chunks detected (count, all runs)")
    ax_b.set_title("(b) Defence layer that caught each attack type\n"
                   "(first failing verification stage, measured)")
    ax_b.legend(fontsize=8.5)

    fig.tight_layout()
    for p in save_fig(fig, FIG_STEM):
        print(f"[m7] wrote {p}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph 7: security effectiveness")
    parser.add_argument("--seed-base", type=int, default=1000)
    args = parser.parse_args()

    ensure_dirs()
    run_id = uuid.uuid4().hex[:8]
    content_id = f"m7-{run_id}"
    ledger = FabricLedger()
    rows: list[dict] = []
    try:
        producer_id, records, wrapped, consumer_priv = publish(ledger, content_id)
        manifest = json.loads(crypto_auth.unwrap_manifest_for_consumer(
            wrapped, consumer_priv).decode())
        print(f"[m7] published {N_CHUNKS} chunks on-chain (content {content_id})")

        for pct in TAMPER_LEVELS:
            for rep in range(REPS):
                rng = random.Random(args.seed_base + pct * 10 + rep)
                n_tamper = N_CHUNKS * pct // 100
                tampered_ids = set(rng.sample(range(N_CHUNKS), n_tamper))
                mode_of = {cid: TAMPER_MODES[k % len(TAMPER_MODES)]
                           for k, cid in enumerate(sorted(tampered_ids))}

                for i, record in enumerate(records):
                    if i in tampered_ids:
                        msg = tamper_message(record, mode_of[i])   # real corruption
                    else:
                        msg = {"chunk_hash": record.chunk_hash,
                               "ciphertext": record.ciphertext,
                               "nonce": record.nonce,
                               "signature": record.chunk_signature}
                    flagged, stage, ms = verify_chunk(
                        ledger, content_id, producer_id, i, msg, manifest)
                    rows.append({
                        "tamper_pct": pct, "rep": rep, "chunk_id": i,
                        "tampered": int(i in tampered_ids),
                        "tamper_mode": mode_of.get(i, ""),
                        "flagged": int(flagged),
                        "detection_stage": stage, "verify_ms": ms,
                    })
                caught = sum(r["flagged"] for r in rows
                             if r["tamper_pct"] == pct and r["rep"] == rep
                             and r["tampered"])
                fp = sum(r["flagged"] for r in rows
                         if r["tamper_pct"] == pct and r["rep"] == rep
                         and not r["tampered"])
                print(f"[m7] pct={pct:>2}% rep={rep}: tampered={n_tamper:>3} "
                      f"caught={caught:>3} false_positives={fp}")
    finally:
        ledger.close()

    write_csv(RAW_CSV, rows)
    summary = summarize(rows)
    write_csv(SUMMARY_CSV, summary)
    plot(summary, rows)
    print("[m7] done")


if __name__ == "__main__":
    main()
