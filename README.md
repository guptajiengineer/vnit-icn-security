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
├── benchmark/                  ← benchmarking pipeline (scripts + results)
│   ├── scripts/                ← run_benchmarks.py, analyze_results.py, generate_graphs.py
│   ├── data/                   ← raw/ and processed/ CSVs (gitignored)
│   ├── graphs/                 ← PNG, PDF, SVG figures (gitignored)
│   └── README.md               ← benchmark workflow documentation
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

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Docker Desktop | 24+ | Runs the Fabric network |
| Docker Compose | v2 (bundled with Desktop) | Orchestrates all containers |
| Python | 3.11+ | Simulation app and benchmark scripts |
| Git | any | Clone the repository |

Python packages required (install once):

```bash
pip install -r app/requirements.txt
pip install pandas matplotlib numpy   # additional for benchmark pipeline
```

---

## First-Time Deployment

Follow these steps in order on a fresh clone.

### 1. Clone the repository

```bash
git clone <repo-url>
cd icn
```

### 2. Create the environment file

```bash
cp app/.env.example app/.env
```

Edit `app/.env` only if your Fabric peer runs on a non-default address.
The default values work as-is with `docker compose up`.

### 3. Start the Fabric network

```bash
docker compose up --build
```

This single command:
- Generates crypto material (certificates, keys) via `cryptogen`
- Creates the `mychannel` genesis block via `configtxgen`
- Starts the orderer and peer containers
- Joins both to `mychannel`
- Packages, installs, approves, and commits the `icnledger` chaincode

Wait until you see `bootstrap.sh complete.` in the logs (≈ 2 minutes):

```bash
docker compose logs -f fabric-bootstrap
```

After completion, `fabric/creds/` is populated with the TLS credentials that
`app/.env` points to.

### 4. Verify the network

```bash
cd app
python smoke_test.py
```

Expected output: `ALL SMOKE TESTS PASSED`

### 5. Run the simulation

```bash
# Simulation only — no Fabric peer required
python run_experiments.py --auth-mode without

# With blockchain authentication against the live peer
python run_experiments.py --auth-mode with

# Both modes, both chunking strategies, 5 iterations
python run_experiments.py --auth-mode both --chunking-mode both --iterations 5
```

Results land in `app/output/results/` (CSVs + PNG plots).

---

## Docker Image

Build the application image from the repository root:

```bash
docker build -t guptajiengineer/icn:1.0 -f app/Dockerfile .
```

Run it against a running peer (credentials mounted at runtime):

```bash
docker run --rm \
  --network icn_fabric \
  -v ./fabric/creds:/app/fabric/creds:ro \
  --env-file app/.env \
  guptajiengineer/icn:1.0
```

---

## Tear Down

```bash
docker compose down          # stop containers, keep crypto volumes
docker compose down -v       # full reset — wipes ledger state; next up regenerates everything
```

> **Multiple clones on the same machine:** `docker-compose.yml` uses `name: icn`
> so all clones share the same Docker volumes. Run `docker compose down -v`
> before switching between clones to avoid "channel already exists" errors.

---

## Benchmark Pipeline

Runs all four experiment configurations (chunking × auth), generates
publication-quality figures (PNG, PDF, SVG), and saves processed CSVs.

```bash
# Step 1 — run experiments and record wall-clock timing (Fabric must be up)
python benchmark/scripts/run_benchmarks.py --iterations 5

# Step 2 — merge raw CSVs and derive additional datasets
python benchmark/scripts/analyze_results.py

# Step 3 — generate all 10 figures in three formats
python benchmark/scripts/generate_graphs.py
```

Figures are written to `benchmark/graphs/{png,pdf,svg}/`.
See [`benchmark/README.md`](benchmark/README.md) for the full graph catalogue
and reproducibility instructions.

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
| `--publisher-start/end` | `4 / 10` | publisher count sweep range |
| `--user-start/end` | `2 / 8` | user count sweep range |
| `--output-dir PATH` | `output/results/` | where CSVs and plots land |

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
