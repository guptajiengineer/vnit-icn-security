# ICN System Overview

## Research Objective

Evaluate adaptive routing strategies (LMM-1 and LMM-2) in Information-Centric
Networks and quantify the overhead of integrating Hyperledger Fabric blockchain
authentication for content producer registration and Merkle-tree chunk integrity
verification.

---

## Network Model

The simulated topology consists of three node classes:

| Class | Symbol | Role |
|-------|--------|------|
| Service Node | SN | Content routing backbone |
| Edge Node | EN | Last-hop access point |
| Cache Node | CN | Selected EN acting as content cache |

Publishers register content with the ledger and distribute chunks across ENs.
User nodes request content via Interest messages routed through SNs.

---

## Routing Algorithms

### LMM-1 — Single Best Path
Routes each Interest along the single highest-weighted path discovered during
a warm-up exploration phase. Path weights decay with congestion and recover
with successful deliveries.

### LMM-2 — Multipath Chunk Distribution
Splits content into chunks and distributes them over multiple scored paths
simultaneously, balancing load and improving resilience to node failures.

---

## Blockchain Authentication Layer

When `--auth-mode with` is used:

1. **Producer registration** — each publisher's Ed25519 public key is
   registered on-chain via `register_producer`.
2. **Content root registration** — Merkle root of published chunks stored
   via `register_content_root`.
3. **Chunk verification** — on retrieval, Merkle proofs are verified against
   the on-chain root via `get_content_root` + `get_merkle_tree`.

The Python client (`app/fabric_client/`) speaks the Fabric Gateway gRPC
protocol directly — no peer CLI, no shell scripts.

---

## Key Constants

| Constant | Value | Effect |
|----------|-------|--------|
| `LEARNING_LAMBDA` | 0.4 | Exponential smoothing for path weight updates |
| `LEARNED_WEIGHT_BLEND` | 0.55 | Blend ratio of learned vs. static weight |
| `PATH_WEIGHT_THRESHOLD` | 0.08 | Paths below this weight are dropped |
| `WARMUP_ROUNDS` | 2 | Exploration rounds before measurement |
| `MEASUREMENT_ROUNDS` | 2 | Rounds averaged for results |

---

## Output

Results land in `app/output/` (gitignored):

```
output/
└── results/
    ├── raw_results.csv
    ├── summary_by_publishers.csv
    ├── summary_by_users.csv
    ├── summary_curves.png
    └── iteration_profiles.png
```
