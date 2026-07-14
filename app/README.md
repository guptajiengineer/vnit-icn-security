# ICN Application

Python simulation for LMM-1 / LMM-2 adaptive routing in Information-Centric
Networks, with optional Hyperledger Fabric blockchain authentication.

---

## Running

```bash
# Simulation only — no Fabric peer required
python run_experiments.py --auth-mode without

# With blockchain auth — requires a running Fabric peer (docker compose up from root)
python run_experiments.py --auth-mode with

# Both modes, multipath chunking, 5 topology iterations
python run_experiments.py --chunking-mode both --auth-mode both --iterations 5

# Smoke tests (no Fabric, no display required)
python smoke_test.py

# Plot topology snapshot
python run_experiments.py --auth-mode without --plot-topology
```

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--auth-mode` | `without` | `without` / `with` / `both` |
| `--chunking-mode` | `without` | `without` / `with` / `both` |
| `--iterations N` | `3` | topology seeds to average |
| `--publisher-start/end` | `2/6` | sweep range for Np |
| `--user-start/end` | `2/6` | sweep range for Nu |
| `--edge-node-count N` | `6` | number of edge nodes |
| `--output-dir PATH` | `output/results/` | where CSVs and plots land |

## Environment

Copy `.env.example` to `.env` before running with `--auth-mode with`:

```bash
cp .env.example .env
```

Credentials (`../fabric/creds/`) are populated automatically by
`docker compose up` from the project root.

## Module Map

| Module | Role |
|--------|------|
| `run_experiments.py` | CLI entry point |
| `experiments.py` | Experiment orchestration, outer loops |
| `network_scenario.py` | Core simulation engine, LMM-1 / LMM-2 |
| `network.py` | Topology builder |
| `paths.py` | BFS path discovery, scoring, multipath |
| `content.py` | Content publishing, chunk assignment |
| `crypto_auth.py` | AES-GCM, Ed25519, X25519, Merkle tree |
| `models.py` | Shared dataclasses |
| `config.py` | Tunable constants |
| `fabric/chain.py` | Ledger ABC + SimulatedLedger + FabricLedger |
| `fabric_client/client.py` | Fabric Gateway gRPC client |

See [`docs/architecture.md`](docs/architecture.md) for the full execution flow.
