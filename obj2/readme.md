# Obj2 — Cryptographic Authentication Layer for ICN Multipath Simulator

## Overview

This folder (`obj2/`) implements **Steps 1–4 of the cryptographic authentication layer** on top of the ICN multipath + chunking simulator developed in `final_code/` (Obj1).

The layer adds:

- **Producer registration** on a simulated blockchain (Ed25519 identity keys)
- **Per-chunk SHA-256 hashing** for content integrity
- **Per-chunk AES-256-GCM encryption** with unique keys per chunk
- **Merkle-tree-based blockchain registration** (root hash only — O(1) on-chain footprint)
- **Consumer manifest encryption** via X25519 ECDH + HKDF + AES-256-GCM (ECIES-style)
- **Cache-poisoning defence** — Merkle proof verified before any cache store or final consumer delivery
- **Auth-mode toggle** (`without` / `with` / `both`) so overhead comparisons can be measured experimentally, mirroring the existing chunking-mode toggle

> **What this is NOT**: This is a simulated-blockchain phase only. No real Hyperledger Fabric or Iroha is used. The ledger interface is abstract and swappable — see the [Chain Swap-Out](#chain-swap-out-for-real-blockchain) section.

---

## Relationship to Obj1 (`final_code/`)

| | Obj1 (`final_code/`) | Obj2 (`obj2/`) |
|---|---|---|
| **ICN topology + routing** | ✅ Implemented | Copied verbatim (unchanged) |
| **Multipath forwarding** | ✅ Implemented | Copied verbatim (unchanged) |
| **Content chunking** | ✅ Implemented | Copied verbatim (unchanged) |
| **LMM-1 / LMM-2 caching** | ✅ Implemented | Copied verbatim + auth hooks added |
| **Per-chunk hash + encrypt** | ❌ | ✅ **New in Obj2** |
| **Blockchain (simulated)** | ❌ | ✅ **New in Obj2** |
| **Merkle tree + proof** | ❌ | ✅ **New in Obj2** |
| **Cache-poisoning defence** | ❌ | ✅ **New in Obj2** |
| **Consumer manifest** | ❌ | ✅ **New in Obj2** |
| **Auth overhead measurement** | ❌ | ✅ **New in Obj2** |

`obj2/` is a **self-contained folder** — it does not import from `final_code/` at runtime. It carries its own copies of all unchanged modules.

---

## Dependencies

### Python version
Python 3.10 or higher (uses `match`/`case`-free code, but `from __future__ import annotations` is used throughout — Python 3.8+ should work).

### Python packages

| Package | Purpose | Already in Obj1? |
|---|---|---|
| `matplotlib` | Plotting (copied from Obj1) | Yes |
| `networkx` | Topology building (copied from Obj1) | Yes |
| `cryptography` | AES-256-GCM, X25519, Ed25519, HKDF | **No — new for Obj2** |

Install all dependencies:

```bash
pip install cryptography matplotlib networkx
```

Or just the new one if Obj1 already runs:

```bash
pip install cryptography
```

The `cryptography` package is used in `crypto_auth.py` only. All other files use standard library only.

---

## File Structure

```
obj2/
│
├── chain.py              ← NEW  Ledger ABC + SimulatedLedger (blockchain abstraction)
├── crypto_auth.py        ← NEW  All cryptographic primitives
├── smoke_test.py         ← NEW  Standalone unit-level smoke tests
│
├── config.py             ← MODIFIED  Added AUTH_MODE_* constants + enabled_auth_modes()
├── models.py             ← MODIFIED  Added DataMessage.chunk_hash, DataMessage.merkle_proof, ChunkRecord
├── content.py            ← MODIFIED  Added publish_content() — Steps 1–4 orchestrator
├── network_scenario.py   ← MODIFIED  Added 4 surgical auth hooks
├── experiments.py        ← MODIFIED  Added auth_mode inner loop
├── run_experiments.py    ← MODIFIED  Added --auth-mode CLI argument
├── simulator.py          ← MODIFIED  Re-exports AUTH_MODE_* constants
│
├── paths.py              ← VERBATIM COPY from final_code/
├── network.py            ← VERBATIM COPY from final_code/
├── learning.py           ← VERBATIM COPY from final_code/
├── metrics.py            ← VERBATIM COPY from final_code/
├── plotting.py           ← VERBATIM COPY from final_code/
├── state.py              ← VERBATIM COPY from final_code/
├── resources.py          ← VERBATIM COPY from final_code/
│
├── output/               ← Generated at runtime (not committed)
└── readme.md             ← This file
```

---

## New Modules (Obj2-Specific)

### `chain.py` — Blockchain Abstraction

Defines the `Ledger` ABC (Abstract Base Class) and `SimulatedLedger` (Phase 1 in-memory implementation).

**`Ledger` (ABC) — the contract:**

```python
register_producer(producer_id: str, public_key: bytes) -> None
register_content_root(content_id: str, merkle_root: str) -> None
get_content_root(content_id: str) -> str        # raises KeyError if not found
get_producer_key(producer_id: str) -> bytes     # raises KeyError if not found
```

**`SimulatedLedger(Ledger)` — Phase 1:**

- `_producers: Dict[str, bytes]` — maps producer_id → Ed25519 public key (32 bytes)
- `_content_roots: Dict[str, str]` — maps content_id → Merkle root hex string
- Pure in-memory. No file I/O. No network. No persistence.
- Also has `is_producer_registered()` and `is_content_registered()` convenience helpers.

**Why an ABC?** When Hyperledger Fabric or Iroha is integrated later, a new class (e.g. `FabricLedger(Ledger)`) is added implementing the same 4 methods. One line changes in `experiments.py`. Zero other changes needed anywhere.

---

### `crypto_auth.py` — Cryptographic Primitives

Pure utility module. No simulator imports. Can be tested in isolation.

| Function | Step | Description |
|---|---|---|
| `chunk_hash(chunk_bytes)` | 2.5 | SHA-256 → 64-char hex string |
| `encrypt_chunk(chunk_bytes)` | 3 | AES-256-GCM; fresh random key+nonce per chunk. Returns `(ciphertext, key, nonce)` |
| `decrypt_chunk(ciphertext, key, nonce)` | 3 | AES-256-GCM decrypt; raises `InvalidTag` on failure |
| `build_merkle_tree(leaf_hashes)` | 4 | Binary Merkle tree. Returns `(root_hash, tree_levels)`. Pads odd levels by duplicating last. |
| `get_merkle_proof(tree_levels, leaf_index)` | 4 | Returns `[str(leaf_index), sib_0, sib_1, ...]` — leaf index embedded so verifier knows left/right |
| `verify_merkle_proof(leaf_hash, proof, root_hash)` | 4 | Re-derives root from leaf + proof; compares with `root_hash`. Returns `bool`. |
| `generate_producer_keypair()` | 1 | Ed25519 private key + 32-byte public key bytes (on-chain identity) |
| `generate_consumer_keypair()` | — | X25519 private + public key (encryption only, NOT identity) |
| `build_manifest(chunk_records)` | 7 | List of `{chunk_hash, chunk_locator, chunk_key}` dicts per chunk |
| `wrap_manifest_for_consumer(manifest_bytes, consumer_public_key)` | 8 | ECIES: ephemeral X25519 → ECDH → HKDF-SHA256 → AES-256-GCM. Returns `ephemeral_pub(32) + nonce(12) + ciphertext` |
| `unwrap_manifest_for_consumer(wrapped, consumer_private_key)` | 8 | Decrypts a manifest encrypted by `wrap_manifest_for_consumer` |

**Key design choices:**

- Each chunk gets an **independent AES-256-GCM key and nonce** — compromise of one chunk key does not affect others.
- Merkle proof format `[str(leaf_index), sib_0, ...]` — the first element encodes the leaf's original index as a string, enabling the verifier to determine left/right hashing at each level without ambiguity.
- **X25519 ≠ Ed25519** — the consumer's X25519 keypair is for manifest encryption only; the producer's Ed25519 keypair is for on-chain identity registration only. They are never mixed.
- **No RSA** — hybrid ECIES (X25519 + HKDF + AES-GCM) is used for manifest encryption per the spec.

---

## Modified Modules (Additive Changes Only)

### `config.py`

Added at the bottom, mirroring the chunking-mode pattern exactly:

```python
AUTH_MODE_WITHOUT = "without"
AUTH_MODE_WITH    = "with"
AUTH_MODE_BOTH    = "both"

def auth_label(auth_enabled: bool) -> str: ...
def enabled_auth_modes(auth_mode: str) -> List[bool]: ...
```

No existing lines were changed.

---

### `models.py`

Two additive changes:

**1. `DataMessage` — two new optional fields (default `None` so all existing code still works):**

```python
chunk_hash:    Optional[str]  = None   # SHA-256 hex of plaintext chunk
merkle_proof:  Optional[list] = None   # [str(leaf_index), sib_0, sib_1, ...]
```

**2. New `ChunkRecord` dataclass:**

```python
@dataclass
class ChunkRecord:
    chunk_id:      int    # zero-based index
    chunk_hash:    str    # SHA-256 hex of the plaintext chunk bytes
    chunk_locator: str    # "{content_id}:{chunk_id}" — NOT a physical path
    chunk_key:     bytes  # 32-byte AES-256 key
    nonce:         bytes  # 12-byte AES-GCM nonce
    ciphertext:    bytes  # authenticated ciphertext
```

`chunk_locator` is deliberately content-addressed and NOT tied to a physical node or path — multipath path selection is dynamic and must stay decoupled from the manifest.

---

### `content.py`

Added `publish_content()` — the Steps 1–4 orchestrator. Existing functions are untouched.

```python
def publish_content(
    content_spec: ContentSpec,
    chunk_count: int,
    ledger: Ledger,
    producer_id: str,
) -> Tuple[List[Dict], List[ChunkRecord]]:
```

What it does internally, in order:

1. **Step 1**: If producer not yet registered, generate Ed25519 keypair and call `ledger.register_producer()`.
2. **Step 2**: Generate `chunk_count` synthetic chunk byte blocks. Since the ICN simulator has no real content, each chunk is `SHA-256("{content_id}:{chunk_id}")` — deterministic, unique, 32 bytes each.
3. **Step 2.5**: Call `crypto_auth.chunk_hash()` on each chunk bytes.
4. **Step 3**: Call `crypto_auth.encrypt_chunk()` on each chunk bytes.
5. **Step 4**: Call `crypto_auth.build_merkle_tree()` over all chunk hashes, then call `ledger.register_content_root(content_id, root_hash)`. Also stores the `tree_levels` on the ledger object under `_merkle_trees[content_id]` for proof retrieval.
6. Builds manifest via `crypto_auth.build_manifest()`.
7. Returns `(manifest, chunk_records)`.

**Why `chunk_count` is a parameter**: In the existing simulator, `chunk_count = len(selected_paths)` is computed at runtime (one chunk per multipath route). It is not fixed at content creation time. `experiments.py` passes `max(1, num_users)` as the upper bound — consistent with the runtime computation.

---

### `network_scenario.py`

Four surgical additions only. All existing logic is preserved character-for-character.

**Addition 1 — `__init__` signature** (new optional parameters):

```python
auth_enabled: bool = False
ledger: Optional[Ledger] = None
chunk_records_map: Optional[Dict[str, List[ChunkRecord]]] = None
```

**Addition 2 — `on_node_interest()` `can_serve` branch** — attaches auth fields to outgoing `DataMessage`:

```python
if self.auth_enabled:
    records = self.chunk_records_map.get(msg.content_id, [])
    if msg.chunk_id < len(records):
        data.chunk_hash = records[msg.chunk_id].chunk_hash
        data.merkle_proof = self._get_merkle_proof_for_chunk(msg.content_id, msg.chunk_id)
```

**Addition 3 — `on_node_data()` LMM-2 cache-store branch** — verifies proof BEFORE caching (cache-poisoning defence):

```python
if not self._verify_chunk_proof(msg.content_id, msg.chunk_hash, msg.merkle_proof):
    print(f"[AUTH] Cache-store REJECTED ...")
    return   # drop message, do not cache, request times out → success_rate = 0
```

**Addition 4 — `on_node_data()` edge consumer branch** — verifies proof BEFORE marking chunk delivered:

```python
if not self._verify_chunk_proof(msg.content_id, msg.chunk_hash, msg.merkle_proof):
    print(f"[AUTH] Consumer delivery REJECTED ...")
    return   # drop, request times out → success_rate = 0
```

`_verify_chunk_proof()` returns `True` (allow) when: `auth_enabled=False`, OR no root registered yet, OR proof is absent. It returns `False` only when auth IS on AND a root IS registered AND the proof verifiably fails — so exploration-phase messages and non-auth runs are never disrupted.

`DataMessage` auth fields are also propagated through intermediate forwarding hops so they survive the full return path.

**`simulate_lmm1()` and `simulate_lmm2()`** both accept and forward `auth_enabled`, `ledger`, `chunk_records_map`.

---

### `experiments.py`

Added `auth_mode` parameter to `evaluate_topology_scenarios()` and `run_full_experiment()`.

Inner loop structure (mirrors chunking-mode exactly):

```python
for chunking_enabled in config.enabled_chunking_modes(chunking_mode):
    for auth_enabled in config.enabled_auth_modes(auth_mode):
        if auth_enabled:
            ledger = SimulatedLedger()
            for content_spec in content_specs:
                _, chunk_records = publish_content(content_spec, num_users, ledger, producer_id)
                chunk_records_map[content_spec.content_id] = chunk_records
        lmm1 = simulate_lmm1(..., auth_enabled=auth_enabled, ledger=ledger, chunk_records_map=...)
        lmm2 = simulate_lmm2(..., auth_enabled=auth_enabled, ledger=ledger, chunk_records_map=...)
```

Output records include the new `auth_mode` field: `"without_auth"` or `"with_auth"`.

---

### `run_experiments.py`

Added `--auth-mode` CLI argument:

```
--auth-mode {without,with,both}
    without : no auth — baseline, identical behaviour to final_code/ (default)
    with    : full cryptographic auth on every run
    both    : runs both and saves separate result bundles for overhead comparison
```

When `--auth-mode both`: output is split into `with_auth/` and `without_auth/` subdirectories (same pattern as `--chunking-mode both` splits into `with_chunking/` and `without_chunking/`).

Manifest JSON printed to terminal now includes `"auth_mode"` field.

---

### `simulator.py`

Added re-exports (mirrors chunking-mode re-exports):

```python
AUTH_MODE_WITHOUT = config.AUTH_MODE_WITHOUT
AUTH_MODE_WITH    = config.AUTH_MODE_WITH
AUTH_MODE_BOTH    = config.AUTH_MODE_BOTH
```

All three added to `__all__`.

---

## Execution Flow

### Entrypoint note

Same as `final_code/`:

- `python experiments.py` only loads the module and exits.
- The practical entrypoint is `run_experiments.py`.
- `run_experiments.py` imports via `simulator.py` which re-exports from `experiments.py`.

### Full call flow (with auth enabled)

```text
run_experiments.py:main()
  -> build_default_content_specs()
  -> run_full_experiment(auth_mode="with")
      -> build_base_topology()
      -> evaluate_topology_scenarios()
          -> assign_content_publishers()
          -> build_exploration_snapshot()          [auth_enabled=False — exploration is unauthenticated]
              -> NetworkScenario(auth_enabled=False)
              -> bootstrap_exploration()
          -> for auth_enabled in [True]:
              -> SimulatedLedger()                 [NEW: create per-(Np,Nu,chunking) ledger]
              -> publish_content() x num_contents  [NEW: Steps 1-4 for each content]
                  -> ledger.register_producer()    [Step 1]
                  -> chunk_hash() x chunk_count    [Step 2.5]
                  -> encrypt_chunk() x chunk_count [Step 3]
                  -> build_merkle_tree()           [Step 4a]
                  -> ledger.register_content_root()[Step 4b]
              -> simulate_lmm1(auth_enabled=True, ledger=..., chunk_records_map=...)
                  -> run_dynamic_scenario()
                      -> NetworkScenario(auth_enabled=True, ...)
                      -> run_round() x total_rounds
                          -> on_user_request()
                          -> on_node_interest()
                              [can_serve] -> attach chunk_hash + merkle_proof to DataMessage [NEW]
                          -> on_node_data()
                              [cache node]  -> verify_merkle_proof() before store_in_cache() [NEW]
                              [edge/consumer] -> verify_merkle_proof() before delivery       [NEW]
              -> simulate_lmm2(auth_enabled=True, ...)   [same as lmm1]
      -> summarize_records()
      -> write_csv() -> output/
```

---

## How to Run

All commands must be run from inside the `obj2/` directory.

```bash
cd "d:/code project/vnit/fin_fyp/fyp/obj2"
```

### 1. Run the smoke tests (cryptographic unit tests)

Verifies all cryptographic primitives independently before running the full simulator.

```bash
python smoke_test.py
```

Expected output:

```
PASS: chain.py
PASS: AES-GCM encrypt/decrypt
PASS: Merkle tree + proof (5 leaves)
PASS: Merkle tree single-leaf
PASS: Tampered hash correctly rejected
PASS: X25519 + HKDF + AES-GCM manifest wrap/unwrap
PASS: Ed25519 producer keypair
PASS: publish_content + Merkle proof round-trip

ALL SMOKE TESTS PASSED
```

---

### 2. Run without authentication (baseline — identical to `final_code/`)

```bash
python run_experiments.py --auth-mode without --chunking-mode with --output-dir output/baseline
```

---

### 3. Run with authentication enabled

```bash
python run_experiments.py --auth-mode with --chunking-mode with --output-dir output/with_auth
```

---

### 4. Run both modes side-by-side for overhead comparison

```bash
python run_experiments.py --auth-mode both --chunking-mode with --output-dir output/auth_comparison
```

This produces:

```
output/auth_comparison/
  raw_results.csv                         ← Combined (all modes)
  summary_by_publishers_and_users.csv     ← Combined summary
  without_auth/
    raw_results.csv
    summary_by_publishers.csv
    summary_by_users.csv
    summary_by_publishers_and_users.csv
    iteration_profile_by_publishers.csv
    iteration_profile_by_users.csv
    summary_curves.png
    iteration_profiles.png
  with_auth/
    raw_results.csv
    summary_by_publishers.csv
    summary_by_users.csv
    ...
```

---

### 5. Combined chunking + auth sweep

```bash
python run_experiments.py --auth-mode both --chunking-mode both --output-dir output/full_sweep
```

Output subdirs: `without_chunking/without_auth/`, `without_chunking/with_auth/`, `with_chunking/without_auth/`, `with_chunking/with_auth/`.

---

### Full CLI reference

```
python run_experiments.py [OPTIONS]

  --iterations N              Number of topology iterations (default: 1)
  --seed-base N               RNG seed base (default: 1200)
  --chunking-mode {without,with,both}
                              Multipath chunking mode (default: with)
  --auth-mode {without,with,both}
                              Cryptographic auth mode (default: without)
  --arrival-window FLOAT      Arrival window in time units (default: 20.0)
  --content-replication-k N   Min publishers per content (default: 10)
  --content-count N           Number of content objects (default: 2)
  --edge-node-count N         Number of edge nodes (default: 1)
  --output-dir PATH           Output directory (default: output/results)
  --load-normalized-arrivals  Scale arrival window with Nu
  --arrival-window-reference-users N
  --plot-topology             Render topology snapshot PNG
  --topology-seed N
  --topology-publishers N
  --topology-users N
```

---

## Output Files

### `raw_results.csv`

One row per `(iteration, seed, num_publishers, num_users, chunking_mode, auth_mode, lmm)` combination.

| Column | Description |
|---|---|
| `iteration` | Experiment iteration index (1-based) |
| `seed` | Topology RNG seed used |
| `num_publishers` | Number of active publisher nodes (Np) |
| `num_users` | Number of concurrent users (Nu) |
| `arrival_window_used` | Effective arrival window |
| `chunking_mode` | `with_chunking` or `without_chunking` |
| `auth_mode` | `with_auth` or `without_auth` |
| `lmm` | `LMM-1` or `LMM-2` |
| `avg_hops` | Mean hops per delivered chunk |
| `avg_delay` | Mean end-to-end delay per request |
| `avg_success_rate` | Mean delivery success rate (0.0–1.0) |

### `summary_by_publishers.csv` / `summary_by_users.csv`

Aggregated over iterations and user/publisher sweep dimensions respectively. Include `_std` columns for each metric.

### `summary_curves.png` / `iteration_profiles.png`

Plots comparing LMM-1 vs LMM-2 across the publisher and user sweeps.

---

## What the Authentication Does (Conceptually)

```
Producer side (publish_content):
  Content → K chunks → SHA-256 each chunk → encrypt each chunk (AES-256-GCM)
                                                    ↓
                              Merkle tree over chunk hashes
                                                    ↓
                              Register only root hash on ledger  ← O(1) on-chain

Network side (network_scenario):
  Provider node serves chunk → attaches [chunk_hash, merkle_proof] to DataMessage
                                                    ↓
  Cache node receives DataMessage:
    verify_merkle_proof(chunk_hash, proof, ledger.get_content_root(content_id))
    ✓ Valid   → store_in_cache()
    ✗ Invalid → DROP message, log rejection, request times out

  Edge/consumer node receives DataMessage:
    verify_merkle_proof(chunk_hash, proof, ledger.get_content_root(content_id))
    ✓ Valid   → mark chunk delivered, update metrics
    ✗ Invalid → DROP, request times out → success_rate = 0.0 in output
```

A cache-poisoning attack (injected fake data) is caught at **two points**: before caching (protecting other consumers) and at final delivery (protecting the requesting consumer). Both rejections appear in the terminal as `[AUTH] ... REJECTED` log lines.

---

## Chain Swap-Out (for Real Blockchain)

To replace `SimulatedLedger` with a real chain:

**Step 1**: Create a new file, e.g. `fabric_ledger.py`:

```python
from chain import Ledger

class FabricLedger(Ledger):
    def __init__(self, gateway_endpoint: str): ...
    def register_producer(self, producer_id, public_key): ...      # Fabric invoke
    def register_content_root(self, content_id, merkle_root): ...  # Fabric invoke
    def get_content_root(self, content_id) -> str: ...             # Fabric query
    def get_producer_key(self, producer_id) -> bytes: ...          # Fabric query
```

**Step 2**: In `experiments.py`, change one line:

```python
# Before:
ledger = SimulatedLedger()

# After:
ledger = FabricLedger(gateway_endpoint="localhost:7051")
```

**That's it.** All of `network_scenario.py`, `content.py`, `models.py`, `crypto_auth.py` remain unchanged. They type against `Ledger` (the ABC) only.

---

## Reserved Extension Points (Future Steps)

Documented in the original algorithm in this readme, these steps are NOT yet implemented but the cryptographic primitives for them exist in `crypto_auth.py`:

| Step | Description | Primitives ready in `crypto_auth.py`? |
|---|---|---|
| Step 5 | Consumer authentication | `generate_consumer_keypair()` ✅ |
| Step 6 | Smart contract authorization | Requires real chain — no ✅ |
| Step 7 | Individual-key manifest generation | `build_manifest()` ✅ |
| Step 8 | Manifest encryption using consumer public key | `wrap_manifest_for_consumer()` ✅ |
| Step 9 | Consumer-side verification + decryption | `unwrap_manifest_for_consumer()` + `decrypt_chunk()` ✅ |
| Step 10 | Security overhead optimization | Obj3 scope |

---

## Class Reference (Obj2 Additions)

| Class / Function | File | Purpose |
|---|---|---|
| `Ledger` (ABC) | `chain.py` | Contract for any blockchain backend |
| `SimulatedLedger` | `chain.py` | Phase 1: in-memory ledger |
| `ChunkRecord` | `models.py` | All crypto material for one chunk |
| `DataMessage.chunk_hash` | `models.py` | SHA-256 carried in network message |
| `DataMessage.merkle_proof` | `models.py` | Sibling-path proof carried in network message |
| `publish_content()` | `content.py` | Steps 1–4 orchestrator |
| `chunk_hash()` | `crypto_auth.py` | SHA-256 of chunk bytes |
| `encrypt_chunk()` | `crypto_auth.py` | AES-256-GCM per-chunk encryption |
| `decrypt_chunk()` | `crypto_auth.py` | AES-256-GCM decryption + auth check |
| `build_merkle_tree()` | `crypto_auth.py` | Binary Merkle tree over chunk hashes |
| `get_merkle_proof()` | `crypto_auth.py` | Sibling-path extraction |
| `verify_merkle_proof()` | `crypto_auth.py` | Proof verification against root |
| `generate_producer_keypair()` | `crypto_auth.py` | Ed25519 identity keypair |
| `generate_consumer_keypair()` | `crypto_auth.py` | X25519 encryption keypair |
| `build_manifest()` | `crypto_auth.py` | Per-chunk manifest list |
| `wrap_manifest_for_consumer()` | `crypto_auth.py` | ECIES manifest encryption |
| `unwrap_manifest_for_consumer()` | `crypto_auth.py` | ECIES manifest decryption |
| `NetworkScenario._verify_chunk_proof()` | `network_scenario.py` | Internal auth gate (cache + consumer) |
| `AUTH_MODE_WITHOUT/WITH/BOTH` | `config.py` / `simulator.py` | Auth mode constants |
| `enabled_auth_modes()` | `config.py` | Auth mode → `List[bool]` iterator |

---

## Important Note for Report / Viva

> `experiments.py` is the experiment orchestration module, but `run_experiments.py` is the executable entrypoint.

> The authentication layer is **additive** — `auth_enabled=False` (the default) produces results byte-identical to `final_code/`. This is by design: the overhead comparison requires a clean baseline from the same codebase.

> Content in this simulator is **virtual** — there are no actual file bytes. Chunk bytes are synthesised deterministically as `SHA-256("{content_id}:{chunk_id}")`. This is the only meaningful approach for a discrete-event network simulator with no real content source, and it preserves all the cryptographic properties (each chunk produces a unique, non-trivial hash and encrypts to unique ciphertext).
