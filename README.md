# ICN — Blockchain-Authenticated Information-Centric Networking Simulator

A research simulator for evaluating **LMM-1 / LMM-2 adaptive routing** in
Information-Centric Networks (ICN), with optional **Hyperledger Fabric** blockchain
authentication of content producers and chunk integrity.

---

## Repository Layout

```
ICN/
├── app/                        ← Python simulation application
│   ├── docs/                   ← application-level documentation
│   ├── fabric/                 ← Ledger ABC + SimulatedLedger + FabricLedger
│   ├── fabric_client/          ← pure-Python Fabric Gateway gRPC client
│   ├── output/                 ← generated results (gitignored)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── .env.example
│   └── run_experiments.py      ← main entry point
│
├── fabric/                     ← Hyperledger Fabric infrastructure
│   ├── network/                ← crypto configs, channel config, peer config, scripts
│   ├── icn_ledger/             ← Go chaincode (icnledger)
│   ├── channel-artifacts/      ← genesis block (gitignored, generated)
│   └── creds/                  ← admin PEM files (gitignored, generated)
│
├── docs/                       ← project-level documentation
├── docker-compose.yml          ← brings up Fabric + optionally the app
├── .gitignore
└── README.md
```

---

## Quick Start

### Simulation only (no blockchain)

```bash
cd app
python run_experiments.py --auth-mode without
```

No Docker, no Fabric peer required — uses an in-memory ledger.

### Full stack (Fabric + app)

```bash
# From project root — starts Fabric, creates channel, deploys icnledger chaincode
docker compose up --build

# Run the app against the live peer
docker compose --profile app up --build
```

After `docker compose up` completes, `fabric/creds/` is populated with the TLS
credentials that `app/.env` points to.

### Tear down

```bash
docker compose down          # keeps crypto volumes
docker compose down -v       # full reset — wipes ledger state, next up regenerates
```

> **Multiple clones on the same machine:** `docker-compose.yml` uses
> `name: icn` so all clones share the same Docker volumes. Run
> `docker compose down -v` in each clone before starting another to avoid
> "channel already exists" errors during `fabric-bootstrap`.


---

## Two Operating Modes

| Flag | Ledger | Dependencies |
|------|--------|-------------|
| `--auth-mode without` | `SimulatedLedger` (in-memory) | matplotlib only |
| `--auth-mode with`    | `FabricLedger` (gRPC to peer) | Fabric peer + creds |

---

## Key CLI Flags (`run_experiments.py`)

| Flag | Default | Description |
|------|---------|-------------|
| `--auth-mode` | `without` | `without` / `with` / `both` |
| `--chunking-mode` | `without` | `without` / `with` / `both` |
| `--iterations N` | `3` | topology seeds to average |
| `--edge-node-count N` | `6` | number of edge nodes |
| `--output-dir PATH` | `output/results/` | where CSVs and plots land |

---

## Environment Setup (`app/.env`)

Copy `app/.env.example` to `app/.env` and adjust if needed:

```bash
cp app/.env.example app/.env
```

Credential paths in `.env` resolve relative to `app/` and point into
`../fabric/creds/` — populated automatically by `docker compose up`.

---

## Running Tests

```bash
cd app
python smoke_test.py
```

---

## Architecture

See [`app/docs/architecture.md`](app/docs/architecture.md) for the full
execution flow, module responsibilities, and the blockchain layer design.

---

## Blockchain Layer

- **Chaincode**: `fabric/icn_ledger/icn_ledger.go` — Go chaincode using
  `fabric-contract-api-go/v2`; implements `register_producer`,
  `register_content_root`, `get_content_root`, `get_producer_key`,
  `store_merkle_tree`, `get_merkle_tree`.
- **Python client**: `app/fabric_client/` connects via Fabric Gateway gRPC
  (Endorse → Submit → CommitStatus for writes; Evaluate for reads).
- **Credentials**: TLS CA cert, admin signing cert, admin private key — mounted
  at runtime; never baked into the Docker image.
