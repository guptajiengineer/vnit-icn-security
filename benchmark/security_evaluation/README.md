# Security Evaluation

This suite evaluates the **cost and effectiveness of the proposed ICN security
architecture**. It produces the seven graphs required by the research guide.

> These experiments evaluate the **security mechanisms**. For network/routing
> performance, see [`../performance_evaluation/`](../performance_evaluation/).

---

## Purpose

Quantify what the proposed security design (per-chunk encryption, per-chunk
Ed25519 signatures over hashes, Merkle-root aggregation, and Hyperledger Fabric
anchoring) *costs* and *achieves*, measured directly against the real
implementation rather than analytical models.

## Instrumentation framework

The `instrumentation/` directory is a **measurement framework**, not a
reimplementation. It **observes the simulator without changing its behaviour**:
each milestone script imports the real, unmodified functions from `app/`
(`crypto_auth.py`, `content.py`, `fabric/chain.py`, …) and times, counts, or
sizes their actual execution.

Two rules are enforced throughout:

- **No simulator source file is modified** by this suite.
- **Every graph is generated from real, measured execution.** No fabricated,
  estimated, or interpolated data is permitted — every CSV row corresponds to an
  operation that actually ran (including real Fabric transactions and queries).

---

## Workflow

```
instrumentation      milestone scripts import the real app/ code paths
      ↓
real execution       crypto ops run; real Fabric transactions & queries execute
      ↓
CSV generation       measured values written to data/*.csv
      ↓
graph generation     figures rendered to graphs/png/ and graphs/pdf/
      ↓
evaluation report    findings written up in evaluation_report.md
```

---

## Directory layout

```
security_evaluation/
├── README.md
├── instrumentation/
│   ├── common.py                        ← shared paths + plot style
│   ├── milestone1_crypto_time.py
│   ├── milestone2_auth_performance.py
│   ├── milestone3_registration.py
│   ├── milestone4_storage_overhead.py
│   ├── milestone5_security_overhead.py
│   ├── milestone6_key_management.py
│   └── milestone7_security_effectiveness.py
├── data/                                ← raw + summary CSVs (measured)
├── graphs/
│   ├── png/
│   └── pdf/
└── evaluation_report.md                 ← full technical write-up
```

---

## How to run

Milestones 2–5 and 7 execute real transactions/queries against Hyperledger
Fabric, so the stack must be running for those. Run **from `app/`** so the
`.env` credential paths resolve:

```bash
docker compose up -d          # from repo root (needed for milestones 2–5, 7)
cd app
python ../benchmark/security_evaluation/instrumentation/milestone1_crypto_time.py
python ../benchmark/security_evaluation/instrumentation/milestone2_auth_performance.py
# … milestone3 … milestone7
```

Milestones 1 and 6 are pure local computation and do not require Fabric.

Each script writes its CSVs to `data/` and its figures to `graphs/png|pdf/`.

---

## Milestones

These correspond directly to the research-guide evaluation requirements.

| # | Milestone | Measures |
|---|-----------|----------|
| 1 | **Cryptographic Processing Time** | Per-primitive time (hash, encrypt, sign-the-hash, Merkle) vs. a naive payload-signing baseline, across chunk sizes. |
| 2 | **Authentication Performance** | End-to-end per-request verification delay and success rate as request volume grows; component breakdown. |
| 3 | **Blockchain Registration Performance** | Registration latency and transaction count: one Merkle root vs. per-chunk on-chain hashes, as chunk count grows. |
| 4 | **Blockchain Storage Overhead** | On-chain bytes for full metadata vs. per-chunk hashes vs. Merkle root vs. full tree. |
| 5 | **Security Overhead Comparison** | Total security overhead of the proposed scheme vs. RSA, ECDSA, and existing per-chunk on-chain anchoring. |
| 6 | **Key Management Overhead** | Managed keys and key-distribution memory for per-chunk vs. group vs. session keys, plus measured compromise blast radius. |
| 7 | **Security Effectiveness** | Tamper-detection rate and classification accuracy under real attack injection (payload flip, substitution, signature forgery). |

Full methodology, measured results, and per-graph discussion are documented in
[`evaluation_report.md`](evaluation_report.md).
