# Comprehensive Architecture Review — ICN Security Simulation

## 1. High-Level Project Architecture

The project is an **Information-Centric Networking (ICN) discrete-event simulation** implemented entirely in Python. It models a wireless/ad-hoc network of ~120 nodes and measures how two routing algorithms (LMM-1 and LMM-2) perform under varying numbers of publishers (Np) and users (Nu), with and without a cryptographic authentication pipeline (Objective 2).

The simulation is fully synthetic — there is no real packet I/O, no OS networking, no threads. Everything runs as scheduled callbacks on a priority-queue event loop inside a single Python process.

**Layers (bottom to top):**

```
┌──────────────────────────────────────────────────────────────────┐
│  run_experiments.py      — CLI entry point, argument parsing      │
├──────────────────────────────────────────────────────────────────┤
│  experiments.py          — Experiment orchestration loop          │
├──────────────────────────────────────────────────────────────────┤
│  network_scenario.py     — Discrete-event simulation engine       │
│  (NetworkScenario, EventLoop, RuntimeNode, EdgeRuntimeNode)       │
├─────────────────┬────────────────────────────────────────────────┤
│  content.py     │  chain.py       crypto_auth.py                 │
│  (chunking,     │  (Ledger ABC,   (AES-256-GCM, SHA-256,         │
│   publish_      │   Simulated-    Merkle tree, X25519,           │
│   content)      │   Ledger)       Ed25519)                        │
├─────────────────┴────────────────────────────────────────────────┤
│  network.py   paths.py   resources.py   state.py   learning.py   │
│  (topology)   (routing)  (node budget)  (cloning)  (RL weights)  │
├──────────────────────────────────────────────────────────────────┤
│  models.py               — All dataclasses                        │
│  config.py               — Constants and mode enums              │
├──────────────────────────────────────────────────────────────────┤
│  metrics.py   plotting.py                                         │
│  (statistics) (matplotlib)                                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Repository Tree — Every File Explained

```
fyp/                                    ← git root
│
├── prompt.txt                          ← Project specification (this file)
├── *.pdf                               ← Research papers/references
│
├── final_code/                         ← ★ ACTIVE CODEBASE (only this matters)
│   ├── run_experiments.py              ← CLI entry point
│   ├── config.py                       ← Constants, mode enums, helper fns
│   ├── models.py                       ← All dataclasses (SimNode, PathRecord,
│   │                                      ContentSpec, DataMessage, ChunkRecord…)
│   ├── network.py                      ← Topology generator (build_base_topology)
│   ├── paths.py                        ← Routing/path algorithms (BFS, multipath)
│   ├── content.py                      ← Content spec building + publish_content()
│   ├── network_scenario.py             ← Simulation engine (NetworkScenario,
│   │                                      EventLoop, LMM-1/LMM-2 runners)
│   ├── experiments.py                  ← Experiment loop, CSV writing
│   ├── simulator.py                    ← Re-export facade (for run_experiments.py)
│   ├── learning.py                     ← Reinforcement learning weight updates
│   ├── resources.py                    ← Node resource consumption/recovery
│   ├── state.py                        ← Deep-clone helpers for topology state
│   ├── metrics.py                      ← Per-round metric aggregation
│   ├── plotting.py                     ← Matplotlib summary + topology plots
│   ├── chain.py                        ← ★ Ledger ABC + SimulatedLedger (Obj2)
│   ├── crypto_auth.py                  ← ★ Crypto primitives (Obj2)
│   ├── smoke_test.py                   ← Unit tests for Obj2 modules
│   │
│   ├── output/                         ← Generated results (gitignored)
│   │   ├── results/                    ← CSV + PNG outputs
│   │   ├── auth_comparison/            ← Auth overhead comparison outputs
│   │   └── auth_test/
│   ├── edge_1_itr100/                  ← Saved experimental runs
│   └── edge_2_itr100/
│
├── paper_repro_clean/                  ← Older cleaner version (no auth)
│   ├── run_experiments.py
│   ├── models.py, network.py, …
│   └── results/                        ← Saved paper reproduction results
│
├── LMM_plus_chunking_final/            ← Intermediate version with chunking
│   └── LMM_plus_chunking/             ← (historical, not active)
│
├── LMM & LMM-1/                        ← Early prototype with metricsCollector
├── lmm-final/                          ← Another intermediate version
├── LMM/                                ← Original LMM-only baseline
├── modified/                           ← Experimental scratch files
└── sem8/                               ← Semester 8 exploratory code
```

**Active codebase: `final_code/` only.** All other directories are historical snapshots.

---

## 3. Entry Points and Complete Execution Flow

```
python run_experiments.py [--iterations N] [--chunking-mode with/without/both]
                          [--auth-mode without/with/both] [--edge-node-count 1]
                          [--publisher-start 4] [--publisher-end 10] ...
```

**Complete call chain:**

```
main()                                              [run_experiments.py]
  │
  ├─ build_argument_parser()                        parse CLI args
  ├─ build_default_content_specs(content_count)     [content.py]
  │    └─ returns List[ContentSpec]
  │
  └─ run_full_experiment(...)                        [experiments.py via simulator.py]
       │
       ├─ for each iteration:
       │    └─ build_base_topology(seed, edge_node_count)  [network.py]
       │         ├─ place edge nodes (ENi) at fixed positions
       │         ├─ place ~119 router nodes randomly
       │         ├─ connect within communication_range
       │         ├─ ensure_connected() (BFS merge)
       │         └─ pick_publisher_candidates()
       │
       └─ evaluate_topology_scenarios(base, ...)    [experiments.py]
            │
            ├─ for each num_publishers:
            │    ├─ assign_content_publishers(...)   [content.py]
            │    └─ build_exploration_snapshot(...)  [network_scenario.py]
            │         └─ runs NetworkScenario in explore mode once
            │              (pre-builds path tables for all (edge, content) pairs)
            │
            ├─ for each num_users:
            │    ├─ for each chunking_mode ∈ enabled_chunking_modes():
            │    │    └─ for each auth_mode ∈ enabled_auth_modes():
            │    │         │
            │    │         ├─ if auth_enabled:
            │    │         │    └─ publish_content(content_spec, …)  [content.py]
            │    │         │         ├─ generate_producer_keypair()  [crypto_auth.py]
            │    │         │         ├─ ledger.register_producer()   [chain.py]
            │    │         │         ├─ _synthetic_chunk_bytes()
            │    │         │         ├─ chunk_hash()                 [crypto_auth.py]
            │    │         │         ├─ encrypt_chunk()              [crypto_auth.py]
            │    │         │         ├─ build_merkle_tree()          [crypto_auth.py]
            │    │         │         └─ ledger.register_content_root()
            │    │         │
            │    │         ├─ simulate_lmm1(...)    ──┐
            │    │         └─ simulate_lmm2(...)    ──┤  [network_scenario.py]
            │    │                                     │
            │    │              run_dynamic_scenario() │
            │    │                └─ NetworkScenario.__init__()
            │    │                    └─ restore_exploration_snapshot()
            │    │                        │
            │    │                for round in WARMUP+MEASUREMENT:
            │    │                    scenario.run_round(round_index, num_users)
            │    │                        │
            │    │                    EventLoop.run()
            │    │                        ├─ on_user_request()      ← schedules Interest msgs
            │    │                        ├─ on_node_interest()     ← forwards Interest, serves Data
            │    │                        │    └─ [if auth] attach chunk_hash + merkle_proof to DataMsg
            │    │                        ├─ on_node_data()         ← forwards Data upstream
            │    │                        │    ├─ [if auth] _verify_chunk_proof() at cache-node
            │    │                        │    └─ [if auth] _verify_chunk_proof() at edge-node
            │    │                        ├─ update_learning_from_path()  [learning.py]
            │    │                        ├─ touch_path_resources()       [resources.py]
            │    │                        └─ summarize_user_metrics()     [metrics.py]
            │    │
            │    └─ appends dicts {iteration, seed, Np, Nu, lmm, metrics} to records
            │
            └─ returns raw_records
  │
  ├─ summarize_records()             aggregate mean/stddev per key group
  ├─ write_csv(output_dir / *.csv)
  ├─ plot_summary_curves()           [plotting.py]
  ├─ plot_iteration_profiles()       [plotting.py]
  └─ optionally plot_topology()      [plotting.py]
```

---

## 4. Module Dependency Graph

```
run_experiments.py
    └── simulator.py  (facade/re-export only)
         ├── config.py                  ← no deps
         ├── models.py                  ← no deps
         ├── experiments.py
         │    ├── config.py
         │    ├── models.py
         │    ├── network.py
         │    │    ├── models.py
         │    │    └── paths.py
         │    ├── content.py
         │    │    ├── models.py
         │    │    └── crypto_auth.py   ← no simulator deps
         │    ├── chain.py              ← no deps (ABC + impl)
         │    └── network_scenario.py
         │         ├── config.py
         │         ├── models.py
         │         ├── content.py
         │         ├── learning.py
         │         │    ├── config.py
         │         │    └── models.py
         │         ├── metrics.py       ← no deps
         │         ├── paths.py
         │         │    ├── config.py
         │         │    ├── models.py
         │         │    └── content.py
         │         ├── resources.py
         │         │    ├── models.py
         │         │    └── paths.py
         │         ├── state.py
         │         │    └── models.py
         │         ├── network.py
         │         └── crypto_auth.py
         ├── network.py
         └── paths.py

plotting.py
    └── models.py
```

**Key observation:** `crypto_auth.py` and `chain.py` are **leaf nodes** with zero dependencies on simulation code — ideal for unit testing and future replacement.

---

## 5. Call Graph Starting from run_experiments.py

```
run_experiments.main()
├── build_argument_parser()
├── build_default_content_specs()          content.py
├── validate_args()
├── run_full_experiment()                  experiments.py
│   ├── build_base_topology()              network.py
│   │   ├── sample_router()
│   │   ├── shape_metrics_by_distance()
│   │   ├── ensure_connected()
│   │   └── pick_publisher_candidates()
│   └── evaluate_topology_scenarios()      experiments.py
│       ├── get_user_nodes()               network.py
│       ├── assign_content_publishers()    content.py
│       ├── build_exploration_snapshot()   network_scenario.py
│       │   └── NetworkScenario.__init__()
│       │       └── bootstrap_exploration()
│       │           └── EventLoop.run()
│       │               └── on_node_interest() [explore mode]
│       │                   └── register_discovered_path()
│       ├── publish_content()              content.py  [auth only]
│       │   ├── ledger.register_producer() chain.py
│       │   ├── chunk_hash()               crypto_auth.py
│       │   ├── encrypt_chunk()            crypto_auth.py
│       │   ├── build_merkle_tree()        crypto_auth.py
│       │   └── ledger.register_content_root()
│       ├── simulate_lmm1() / simulate_lmm2()   network_scenario.py
│       │   └── run_dynamic_scenario()
│       │       └── NetworkScenario.run_round()
│       │           └── EventLoop.run()
│       │               ├── on_user_request()
│       │               │   └── [schedules Interest msgs per path]
│       │               ├── on_node_interest() [fetch mode]
│       │               │   ├── has_cached_content()    resources.py
│       │               │   └── [if auth] attach chunk_hash/merkle_proof
│       │               ├── on_node_data()
│       │               │   ├── [if cache-node] _verify_chunk_proof()
│       │               │   │   └── verify_merkle_proof()  crypto_auth.py
│       │               │   ├── store_in_cache()            resources.py
│       │               │   ├── [if edge-node] _verify_chunk_proof()
│       │               │   ├── update_learning_from_path() learning.py
│       │               │   ├── refresh_path_table()
│       │               │   │   ├── path_records_from_raw_paths()  paths.py
│       │               │   │   ├── apply_learning_scores()        learning.py
│       │               │   │   ├── select_multipaths()            paths.py
│       │               │   │   └── choose_cache_node()            network.py
│       │               │   └── touch_path_resources()     resources.py
│       │               └── [timeout] on_user_timer()
│       └── [records append] {Np, Nu, lmm, metrics...}
├── summarize_records()                    experiments.py
├── write_csv()                            experiments.py
├── plot_summary_curves()                  plotting.py
├── plot_iteration_profiles()              plotting.py
└── plot_network_topology()                run_experiments.py
    └── plot_topology()                    plotting.py
```

---

## 6. Data Flow Throughout the Simulation

```
Seed ─────────────────────────────────────────────────────────────────┐
                                                                       ▼
                                                          build_base_topology()
                                                                       │
                                                               BaseTopology
                                                          {nodes, adjacency,
                                                           publisher_candidates,
                                                           edge_node_ids}
                                                                       │
                                          ┌────────────────────────────┤
                                          ▼                            ▼
                              assign_content_publishers()    build_exploration_snapshot()
                                          │                            │
                              Dict[content_id → List[publisher]]   ExplorationSnapshot
                                          │                   {provider_hops,
                                          │                    discovered_paths,
                                          │                    path_table}
                              ┌───────────┤                            │
                              ▼           │                            │
[auth=on] publish_content()   │           │                            │
   │                          │           └────────────┐               │
   ├─ ChunkRecord[]           │                        ▼               ▼
   │  {chunk_hash,            │           NetworkScenario.__init__()
   │   chunk_key,             │                        │
   │   ciphertext,            │                   run_round()
   │   locator}               │                        │
   └─ Ledger                  │                   EventLoop
      {producer_key,          │                        │
       merkle_root,           │            ┌───────────┼──────────────┐
       _merkle_trees}         │            ▼           ▼              ▼
                              │     InterestMsg → DataMsg → RequestState
                              │                                        │
                              │     [auth] DataMsg.chunk_hash          │
                              │           DataMsg.merkle_proof         │
                              │                                        │
                              │     _verify_chunk_proof()              │
                              │           │                            │
                              │      True: store/forward          False: DROP
                              │                                        │
                              └──────────────────────────────────────►│
                                                                       ▼
                                                           round_user_records[]
                                                        {hops, delay, success_rate}
                                                                       │
                                                         summarize_user_metrics()
                                                                       │
                                                              Dict {avg_hops,
                                                                    avg_delay,
                                                                    avg_success_rate}
                                                                       │
                                                              raw_records[]
                                                       {iteration, seed, Np, Nu,
                                                        lmm, chunking_mode,
                                                        auth_mode, …metrics}
                                                                       │
                                                         summarize_records()
                                                                       │
                                                    ┌──────────────────┤
                                                    ▼                  ▼
                                              write_csv()         plotting.py
                                          (summary CSVs)         (PNG charts)
```

---

## 7. Existing Object Model and Important Classes

| Class | File | Role |
|---|---|---|
| `ResourceBudget` | models.py | Per-resource capacity/remaining/threshold; `weight()`, `consume()`, `recover()` |
| `SimNode` | models.py | A network node with position, resources, cached_contents, dynamic metrics |
| `PathRecord` | models.py | One path between edge↔provider with weight, delay, hops, success_rate |
| `CachedContentState` | models.py | Cached content lifetime tracker per node |
| `ContentSpec` | models.py | Content metadata: id, lifespan, cache_cost, popularity |
| `BaseTopology` | models.py | Frozen snapshot: `{nodes, adjacency, subscriber_id, publisher_candidates, edge_node_ids}` |
| `InterestMessage` | models.py | NDN-style interest packet: content_id, path, chunk_id, request_id |
| `DataMessage` | models.py | NDN-style data reply; adds `chunk_hash`, `merkle_proof` (Obj2) |
| `RequestState` | models.py | Per-request tracking: delivered chunks, timings, paths |
| `ExplorationSnapshot` | models.py | Frozen path-discovery state reused across Nu/chunking sweeps |
| `ChunkRecord` | models.py | Per-chunk crypto material: hash, key, nonce, ciphertext (Obj2) |
| `NetworkScenario` | network_scenario.py | **Core simulation class**: holds all runtime state, processes all events |
| `EventLoop` | network_scenario.py | Min-heap priority queue for discrete-event simulation |
| `RuntimeNode` | network_scenario.py | Thin wrapper dispatching interest/data to NetworkScenario |
| `EdgeRuntimeNode` | network_scenario.py | Extends RuntimeNode: handles user_request, exploration_timer, path_timer |
| `Ledger` | chain.py | **ABC** defining the blockchain interface: 4 abstract methods |
| `SimulatedLedger` | chain.py | In-memory `Ledger` implementation for Phase 1 |

---

## 8. Current Chunking Implementation

**Where chunking starts:** `network_scenario.py:NetworkScenario.on_user_request()` (line 485)

When `chunking_enabled=True`, `request_path_records()` returns **all** selected paths (one per provider), not just the best one. Each path carries one chunk: `chunk_id = 0, 1, 2, ...`

**Where chunks are created:**
- Logically, in `on_user_request()`: one `InterestMessage` per selected path, each with a unique `chunk_id` and `chunk_count = len(selected_paths)`.
- Physically, chunk bytes are synthesised in `content.py:_synthetic_chunk_bytes()` only when auth is enabled (Obj2).
- Without auth, chunks are virtual — the simulation tracks delivery of chunk IDs but no actual bytes exist.

**Where metrics are computed:**
- `on_node_data()` at the edge node: records `chunk_metrics[chunk_id] = {hops, delay, success_rate}` per chunk in `RequestState`.
- `write_completed_request_metrics()`: averages chunk hops; multiplies success rates across chunks.
- `summarize_user_metrics()` in `metrics.py`: averages across all users in a round.
- `summarize_rounds()` in `metrics.py`: averages across measurement rounds.

**Where results are stored:**
- `experiments.py:evaluate_topology_scenarios()` appends one dict per (Np, Nu, chunking_mode, auth_mode, LMM variant) to `raw_records`.
- `write_csv()` flushes to `output/results/raw_results.csv`.
- `summarize_records()` groups and averages into summary CSVs.

**Cache key with chunking:** `resources.py:cache_entry_key()` returns `"{content_id}::chunk::{chunk_id}"` when `chunking_enabled=True`, so each chunk occupies an independent cache slot.

---

## 9. Responsibility Map

| Concern | File(s) |
|---|---|
| **Simulation** | `network_scenario.py` (engine), `experiments.py` (orchestration) |
| **Network topology** | `network.py` — node placement, connectivity, publisher selection |
| **Routing** | `paths.py` — BFS, multipath selection, overlap filtering |
| **Metrics** | `metrics.py` — per-user and per-round aggregation |
| **Plotting** | `plotting.py` — summary bars, iteration profiles, topology PNG |
| **Configuration** | `config.py` — constants and mode enums |
| **Cryptography** | `crypto_auth.py` — AES-256-GCM, SHA-256, Merkle tree, X25519, Ed25519 |
| **Blockchain interface** | `chain.py` — `Ledger` ABC + `SimulatedLedger` |
| **Content publishing** | `content.py` — content specs, publisher assignment, `publish_content()` |
| **Resource tracking** | `resources.py` — CPU/bandwidth/cache/energy consume + cache store/lookup |
| **Learning (RL)** | `learning.py` — reward-weighted path scores |
| **State management** | `state.py` — deep-clone topology and path tables |
| **Data structures** | `models.py` — all dataclasses |

---

## 10. Extension Points for Security Pipeline

### Step 1 — Producer Registration
**Already implemented.** `chain.py:Ledger.register_producer()` + `SimulatedLedger`. `content.py:publish_content()` calls it. Extension point: replace `SimulatedLedger` with `FabricLedger(Ledger)`.

### Step 2 — AES-256 Encryption
**Already implemented.** `crypto_auth.py:encrypt_chunk()` / `decrypt_chunk()`. Called from `publish_content()`.

### Step 3 — SHA-256 Hashing
**Already implemented.** `crypto_auth.py:chunk_hash()`. Called per chunk in `publish_content()`.

### Step 4 — ECC Authentication (Ed25519 keypair)
**Already implemented.** `crypto_auth.py:generate_producer_keypair()` generates Ed25519. Public key bytes are stored on the ledger via `register_producer()`. **Not yet wired:** the private key is discarded after generation and no chunk signatures are actually produced per-chunk. Extending: sign each `chunk_hash` with the Ed25519 private key; store signature in `ChunkRecord`; verify in `_verify_chunk_proof()`.

### Step 5 — Blockchain Metadata Registration Interface
**Already implemented.** `chain.py:Ledger` with methods `register_producer`, `register_content_root`, `get_content_root`, `get_producer_key`. `SimulatedLedger` is the stub. The **Fabric integration hook is exactly at the `SimulatedLedger` construction site** in `experiments.py:evaluate_topology_scenarios()`.

### Step 6 — Consumer Authentication
**Partially implemented.** `crypto_auth.py` has `generate_consumer_keypair()`, `wrap_manifest_for_consumer()`, `unwrap_manifest_for_consumer()` (X25519 + HKDF + AES-256-GCM). `build_manifest()` generates the per-chunk key manifest. **Not yet wired into the simulation loop.** Extension point: `NetworkScenario.on_user_request()` — issue consumer public key; `publish_content()` — wrap manifest with consumer key; edge node verifies on receipt.

### Smart Contract Authorization
Extension point: add `authorize_consumer(consumer_id, content_id) -> bool` to the `Ledger` ABC. Implement in `SimulatedLedger` (always True) and stub in `FabricLedger` (chain chaincode call). Wire into `on_user_request()` as a guard before dispatching Interest messages.

---

## 11. Files That Must Remain Untouched

| File | Reason |
|---|---|
| `models.py` | Stable dataclass contract; all modules import from it. New fields were already added cleanly with `Optional` defaults. |
| `config.py` | Only constants and mode enums; adding new auth constants here is safe but the existing constants must not change. |
| `metrics.py` | Single-responsibility; no changes needed for auth. |
| `state.py` | Deep-clone logic; topology structure has not changed. |
| `learning.py` | RL logic is independent of auth. |
| `plotting.py` | Auth comparison plots can be added but existing functions should not be touched. |
| `smoke_test.py` | Test file; extend with new tests, don't rewrite existing assertions. |

---

## 12. Files Safe to Extend

| File | Safe Extension |
|---|---|
| `chain.py` | Add `FabricLedger(Ledger)`, `authorize_consumer()` to ABC |
| `crypto_auth.py` | Add ECC chunk signing/verification functions; add `sign_chunk()`, `verify_chunk_signature()` |
| `content.py` | Wire chunk signing into `publish_content()`; wire consumer key into manifest |
| `experiments.py` | Swap `SimulatedLedger()` → `FabricLedger()` at the construction site |
| `network_scenario.py` | Add consumer auth check in `on_user_request()`; add ECC signature field to DataMessage forwarding |
| `models.py` | Add `chunk_signature: Optional[bytes]` to `DataMessage` and `ChunkRecord` safely |
| `run_experiments.py` | Add `--fabric-endpoint` flag when Fabric is integrated |

---

## 13. Architectural Issues, Code Smells, and Refactoring Suggestions

### Issues

1. **`simulator.py` is a confusing facade.** It re-exports constants and functions from 6 different modules. `run_experiments.py` imports from `simulator` but the underlying modules are well-structured — the facade adds indirection with no benefit. It is also incomplete (`rank_user_nodes` is listed in `__all__` but not exported).

2. **`_merkle_trees` is stored as a duck-typed attribute on the `Ledger` object.** In `content.py:publish_content()`, `ledger._merkle_trees` is attached directly to the `SimulatedLedger` instance with `setattr`. This is not part of the `Ledger` ABC contract, creating a hidden coupling. A `get_merkle_tree(content_id)` method should be added to the ABC.

3. **`verify_merkle_proof()` has dead code.** The original loop body (lines 285–349 in `crypto_auth.py`) is vestigial documentation with a `break` statement before any work is done. The actual logic is in `_verify_merkle_proof_internal()`. The dead loop should be removed.

4. **`build_request_cycle()` in `content.py` has a hard-coded override** (`weighted_cycle = ["a1", "a2"]` at line 119), overwriting the weighted logic above it. The comment `#tosee` confirms this was noticed but not resolved.

5. **`get_user_nodes()` in `network.py`** has a hard-coded `return candidate_ids` at the bottom (line 479) that bypasses the scoring sort above it. The comment `#tosee / remove` confirms this is known.

6. **No ECC chunk signatures yet despite `generate_producer_keypair()` being called.** The private key is discarded immediately in `publish_content()`. Steps 4 and 5 from the research objective are structurally incomplete.

7. **`chunking_mode` constants are duplicated** — defined in both `config.py` and re-exported verbatim through `simulator.py`. One source of truth is enough.

8. **`recover_topology_after_round()` is commented out** in `run_dynamic_scenario()`. This means node resources never recover between rounds, making later rounds increasingly stressed. This is a correctness concern for multi-round experiments.

### Refactoring Suggestions

- Add `get_merkle_tree(content_id) -> List[List[str]]` to the `Ledger` ABC to eliminate the duck-typed `_merkle_trees` attachment.
- Remove `simulator.py` and update `run_experiments.py` to import directly from the modules it needs.
- Add `sign_chunk(private_key, chunk_hash) -> bytes` and `verify_chunk_signature(public_key_bytes, chunk_hash, signature) -> bool` to `crypto_auth.py`.
- Store the Ed25519 private key in `ChunkRecord` (or a separate producer state dict) so chunk signatures can be applied.
- Resolve the two `#tosee` / hardcoded overrides.

---

## 14. Proposed Integration Strategy for the New Security Pipeline

The existing architecture already has the correct seams. The recommended integration strategy minimises changes to the simulation core:

**New file: `chain_fabric.py`**
- Implements `FabricLedger(Ledger)` using the Hyperledger Fabric Python SDK.
- Also adds `authorize_consumer()` when the ABC grows that method.
- **No other file changes required for the swap-in.**

**Extend `chain.py` (Ledger ABC only):**
- Add `get_merkle_tree(content_id) -> List[List[str]]` (replaces duck-typed `_merkle_trees`).
- Add `authorize_consumer(consumer_id: str, content_id: str) -> bool` for Step 7.

**Extend `crypto_auth.py`:**
- Add `sign_chunk(private_key, chunk_hash_hex: str) -> bytes`.
- Add `verify_chunk_signature(public_key_bytes: bytes, chunk_hash_hex: str, signature: bytes) -> bool`.

**Extend `models.py` (additive only):**
- Add `chunk_signature: Optional[bytes] = None` to `DataMessage` and `ChunkRecord`.

**Extend `content.py:publish_content()`:**
- Retain the private key from `generate_producer_keypair()`.
- Call `sign_chunk()` per chunk; store signature in `ChunkRecord`.
- Wrap manifest with consumer public key if provided.

**Extend `network_scenario.py` (surgical, two locations):**
- `on_node_interest()`: attach `chunk_signature` to `DataMessage` alongside `chunk_hash`.
- `on_node_data()`: call `verify_chunk_signature()` inside `_verify_chunk_proof()`.
- `on_user_request()`: add `authorize_consumer()` guard (Step 7).

**Construction site — `experiments.py`:**
- One-line change: `ledger = FabricLedger(endpoint=...)` instead of `SimulatedLedger()`.

This keeps the entire simulation engine agnostic to which ledger backend is active, and the cryptographic layer entirely decoupled from the networking layer.
