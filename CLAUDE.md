# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Repository Structure

```
ICN/
├── app/                    ← Python simulation application (THE ONLY ACTIVE CODE)
├── fabric/                 ← Hyperledger Fabric infrastructure
├── docs/                   ← Project-level documentation
├── docker-compose.yml      ← Fabric network + optional app container
└── README.md
```

---

## Fabric Network (Self-Contained)

The project includes a self-contained Fabric network in `fabric/network/`. No `fabric-samples` dependency.

```bash
# From project root — starts Fabric, creates channel, deploys icnledger chaincode
docker compose up --build

# Tear down (keeps crypto volumes on disk for reuse)
docker compose down

# Full reset (wipes crypto + ledger state — next up regenerates everything)
docker compose down -v
```

After `docker compose up` succeeds, `fabric/creds/` is populated with the admin TLS credentials that `app/.env` points to.

### Network Layout

```
fabric/
├── network/                   ← self-contained network definition
│   ├── configtx.yaml          ← single-org Raft channel config (Org1 only, V2_5)
│   ├── organizations/
│   │   ├── cryptogen/         ← cryptogen input YAMLs (committed)
│   │   ├── ordererOrganizations/  ← generated at runtime (gitignored)
│   │   └── peerOrganizations/     ← generated at runtime (gitignored)
│   ├── scripts/
│   │   ├── generate.sh        ← cryptogen + configtxgen, copies creds
│   │   └── bootstrap.sh       ← osnadmin join + peer join + chaincode lifecycle
│   └── compose/peercfg/core.yaml  ← peer config (gateway.enabled=true)
├── channel-artifacts/         ← mychannel.block (gitignored, generated)
├── creds/                     ← admin-cert.pem, admin-key.pem, tls-ca.crt (gitignored)
└── icn_ledger/                ← Go chaincode (unchanged)
```

### docker-compose.yml Services (start order)

1. `fabric-generate` — one-shot: runs cryptogen + configtxgen, exits 0
2. `orderer.example.com` — starts after generate completes
3. `peer0.org1.example.com` — starts after orderer is healthy
4. `fabric-bootstrap` — one-shot: channel join + chaincode lifecycle, exits 0

---

## Commands

All commands run from inside `app/`:

```bash
# Simulation only — no Fabric peer required
python run_experiments.py --auth-mode without

# With blockchain auth — requires a running Fabric peer and valid creds in fabric/creds/
python run_experiments.py --auth-mode with

# Run both modes and save separate result bundles
python run_experiments.py --chunking-mode both --auth-mode both --iterations 5

# Smoke tests (unit-level, no Fabric, no matplotlib display)
python smoke_test.py

# Plot topology snapshot
python run_experiments.py --auth-mode without --plot-topology
```

Key CLI flags for `run_experiments.py`:
- `--auth-mode without|with|both` — controls whether the Fabric ledger is used
- `--chunking-mode without|with|both` — single-best-path vs. multipath chunk distribution
- `--iterations N` — how many topology seeds to average over
- `--publisher-start/end`, `--user-start/end` — sweep ranges for Np and Nu
- `--edge-node-count` — number of EN (edge nodes) in the topology
- `--output-dir` — where CSVs and plots land (default: `output/results/`)

---

## Architecture

### Two Operating Modes

```
--auth-mode without
  → SimulatedLedger (in-memory dict, no I/O)
  → dependencies: matplotlib only

--auth-mode with
  → FabricLedger → fabric_client (gRPC) → live Fabric peer
  → dependencies: cryptography, grpcio, protobuf
  → requires .env with FABRIC_* vars and fabric/creds/ PEM files
```

### Module Responsibilities

| Module | Role |
|---|---|
| `run_experiments.py` | CLI entry point — parses args, calls `run_full_experiment()`, writes output |
| `simulator.py` | Thin re-export shim — imports from `experiments.py`, `content.py`, `network.py`, `paths.py` |
| `experiments.py` | Experiment orchestration — outer loops over iterations, Np, Nu, auth/chunking modes |
| `network_scenario.py` | Core simulation engine — event loop, LMM-1 and LMM-2 routing behaviour, `NetworkScenario` class |
| `network.py` | Topology builder — `build_base_topology()`, cache node selection |
| `paths.py` | BFS path discovery, scoring, multipath selection |
| `content.py` | `publish_content()`, chunk assignment, content-to-publisher mapping |
| `crypto_auth.py` | All cryptographic primitives — AES-GCM, Ed25519 sign/verify, X25519 ECIES, Merkle tree |
| `models.py` | Shared dataclasses (`BaseTopology`, `SimNode`, `PathRecord`, `ChunkRecord`, `ContentSpec`, …) |
| `learning.py` | Path weight updates from prior observations |
| `resources.py` | Node resource consumption and recovery simulation |
| `metrics.py` | Per-user and per-round result aggregation |
| `state.py` | Deep-clone helpers for topology and snapshot state |
| `plotting.py` | matplotlib output (summary curves, topology PNG) |
| `config.py` | All tunable constants (`LEARNING_LAMBDA`, `WARMUP_ROUNDS`, mode strings, etc.) |
| `fabric/chain.py` | `Ledger` ABC + `SimulatedLedger` (Phase 1) + `FabricLedger` (Phase 2, gRPC) |
| `fabric_client/client.py` | Pure-Python Fabric Gateway gRPC client — no peer CLI, no shell scripts |
| `fabric_client/config.py` | Reads `.env` via `python-dotenv`; validates all `FABRIC_*` env vars |

### Execution Flow

```
run_experiments.py:main()
  └─ run_full_experiment()         ← experiments.py
       └─ build_base_topology()    ← network.py
       └─ evaluate_topology_scenarios()
            └─ build_exploration_snapshot()   ← one-time path discovery
                 └─ NetworkScenario.bootstrap_exploration()
            └─ simulate_lmm1()  ─┐
            └─ simulate_lmm2()  ─┘ ← network_scenario.py
                 └─ run_dynamic_scenario()
                      └─ run_round() × (WARMUP + MEASUREMENT)
                           └─ EventLoop with InterestMessage / DataMessage
```

### Ledger Swap-In Contract

`Ledger` (ABC in `app/fabric/chain.py`) defines six methods: `register_producer`, `register_content_root`, `get_content_root`, `get_producer_key`, `store_merkle_tree`, `get_merkle_tree`. Only `experiments.py` instantiates a concrete ledger — no other file knows about Fabric. To switch backends, change one line in `experiments.py` (line ~114).

### Blockchain Layer

- **Chaincode**: `fabric/icn_ledger/icn_ledger.go` — Go chaincode using `fabric-contract-api-go/v2`; implements the same six methods as the Python `Ledger` ABC.
- **Python client**: `app/fabric_client/` connects via Fabric Gateway gRPC protocol (Endorse → Submit → CommitStatus for writes; Evaluate for reads). Signs with Ed25519 or ECDSA-P256; enforces low-S ECDSA.
- **Credentials**: TLS CA cert, admin signing cert, admin private key — read from paths in `app/.env` (pointing into `../fabric/creds/`).

### Credentials

`fabric/creds/` is gitignored and populated at runtime by `generate.sh`. The Python client reads
`../fabric/creds/tls-ca.crt`, `admin-cert.pem`, and `admin-key.pem` via `app/.env`.
If creds are missing, run `docker compose up` (or just `docker compose run --rm fabric-generate`).

---

## Key Constants (`app/config.py`)

```python
LEARNING_LAMBDA      = 0.4   # exponential smoothing for path weight learning
LEARNING_SIGMA       = 1.0
LEARNED_WEIGHT_BLEND = 0.55
PATH_WEIGHT_THRESHOLD = 0.08  # paths below this weight are dropped
WARMUP_ROUNDS        = 2
MEASUREMENT_ROUNDS   = 2
```

---

## Environment (`app/.env`)

Required when `--auth-mode with`:

```
FABRIC_PEER_ENDPOINT          # e.g. localhost:7051 or peer0-org1:7051
FABRIC_PEER_HOSTNAME_OVERRIDE # e.g. peer0.org1.example.com
FABRIC_CHANNEL                # e.g. mychannel
FABRIC_CHAINCODE              # e.g. icnledger
FABRIC_MSP_ID                 # e.g. Org1MSP
FABRIC_TLS_CERT_PATH          # path to TLS CA cert PEM
FABRIC_CERT_PATH              # path to admin signing cert PEM
FABRIC_PRIVATE_KEY_PATH       # path to admin private key PEM
LEDGER_BACKEND                # "fabric" or "simulated"
```
