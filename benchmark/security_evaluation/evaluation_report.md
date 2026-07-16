# Evaluation Report

## Introduction

This report documents the seven evaluation figures produced to validate the
proposed blockchain-anchored security architecture for Information-Centric
Networking (ICN). It is written to be converted directly into the Evaluation
chapter of the internship report, and subsequently into a research paper.

**Purpose of the evaluation.** The proposed architecture makes a specific set
of design decisions: per-chunk content encryption with per-chunk AES-256 keys,
per-chunk integrity via SHA-256 hashes, per-chunk producer authenticity via
Ed25519 signatures over those hashes, aggregation of all chunk hashes into a
single Merkle root, and anchoring of that root (plus producer identity keys) on
a Hyperledger Fabric ledger. Each of these decisions carries a cost and a
benefit. The evaluation exists to measure both, using the real implementation
rather than analytical models, so that the design can be justified with data.

**Why these seven graphs were required.** The research guide specified seven
evaluation dimensions, each answering one question a reviewer would reasonably
ask about a security architecture of this kind:

| # | Graph | Validates |
|---|-------|-----------|
| 1 | Cryptographic processing time | Efficiency of the chosen primitives |
| 2 | Authentication performance | Per-request cost and reliability under load |
| 3 | Blockchain registration performance | Registration scalability with content size |
| 4 | Blockchain storage overhead | On-chain state footprint |
| 5 | Security overhead comparison | Total cost vs. alternative designs |
| 6 | Key management overhead | Cost and containment of the key strategy |
| 7 | Security effectiveness | Whether tampering is actually detected |

**What they collectively validate.** Together the figures characterise the
architecture along the axes of cryptographic efficiency, authentication
performance, blockchain scalability, storage efficiency, security overhead, key
management, and attack-detection capability. Graphs 1, 2, 6 and 7 are executed
against the real cryptographic and verification code paths; Graphs 2, 3, 4, 5
and 7 additionally execute real transactions and queries against a running
Hyperledger Fabric network. No figure is derived from an analytical model.

> **Reproducibility.** All instrumentation lives under
> `benchmark/instrumentation/` as standalone scripts (`milestone1.py` …
> `milestone7_*.py`). No simulator source file was modified to produce any
> figure. Raw per-observation data is written to `data/*.csv`, and figures to
> `graphs/*.png` and `graphs/*.pdf`. Graphs 2–5 and 7 require the Fabric
> network to be running.

---

## Graph 1 — Cryptographic Processing Time

### Objective

Quantify the per-chunk processing time of the cryptographic primitives the
architecture composes, and place them against a naive "sign-the-whole-payload"
baseline, as a function of chunk size.

### Research Question

What is the CPU cost of the proposed per-chunk cryptographic pipeline
(hash → encrypt → sign-the-hash, and its inverse on the consumer side), and how
does it compare to signing/verifying the full chunk payload directly?

### Motivation

The architecture signs a 32-byte hash rather than the chunk payload, and
verifies content via Merkle proofs rather than re-signing. This graph exists to
measure whether that indirection is actually cheaper than the obvious
alternative and to establish the compute floor referenced by later graphs.

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone1.py`
- **Primitives exercised (unmodified `app/crypto_auth.py`):** `chunk_hash`
  (SHA-256), `encrypt_chunk` / `decrypt_chunk` (AES-256-GCM),
  `sign_chunk` / `verify_chunk_signature` (Ed25519 over the hash),
  `build_merkle_tree`, `get_merkle_proof`, `verify_merkle_proof`.
- **Baseline:** an Ed25519 signature and verification computed over the *entire*
  chunk payload (`naive_sign` / `naive_verify`), implemented inside the
  instrumentation file only.
- **Execution path:** each primitive is timed in isolation with
  `time.perf_counter` around a single real operation on real chunk bytes; the
  publisher and consumer "curves" are sums of the relevant component timings.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Chunk sizes | 64, 128, 256, 512, 1024 KB |
| Samples per (size, primitive) | 200 |
| Timing | `time.perf_counter`, milliseconds |
| Blockchain | Not involved (pure local compute) |

Software/hardware: Python 3.11.9, `cryptography` 49.0.0, Windows 10
(build 26200). Single-process, single-thread.

### Metrics Collected

- **Directly measured:** per-primitive mean/std/min/max time (ms) at each chunk
  size, over 200 samples each.
- **Derived:** publisher-side and consumer-side "curve" totals, computed as sums
  of the measured component timings for the same operation.
- **Calculated:** none beyond the above summation.

### Raw Data

- `data/m1_crypto_time_raw.csv` — one row per timed operation.
- `data/m1_crypto_time_summary.csv` — aggregated mean/std/min/max per
  (chunk size, primitive).

### Figure

`graphs/graph1_crypto_processing_time.png` (and `.pdf`).

### Results

At every chunk size, signing the hash is markedly cheaper than signing the
payload. Representative measured means (from `m1_crypto_time_summary.csv`):

| Chunk size | Sign hash (proposed) | Naive payload sign | Verify sig (proposed) | Naive payload verify |
|-----------:|---------------------:|-------------------:|----------------------:|---------------------:|
| 64 KB   | 0.066 ms | 0.343 ms | 0.194 ms | 0.308 ms |
| 256 KB  | 0.164 ms | 2.521 ms | 0.450 ms | 1.538 ms |
| 1024 KB | 0.201 ms | 9.725 ms | 0.458 ms | 4.926 ms |

The proposed signature-generation cost is essentially flat in chunk size
(0.066 → 0.201 ms across a 16× size increase), whereas the naive payload
signature grows roughly linearly with payload size (0.343 → 9.725 ms). Merkle
proof generation and verification remain below ~0.07 ms across all sizes.

### Discussion

Signing a fixed-length hash decouples signature cost from chunk size, which is
the intended engineering property: the dominant size-dependent costs become the
unavoidable hashing and AES operations, not the asymmetric cryptography. At
1 MB chunks the proposed signing path is roughly 48× cheaper than signing the
payload directly. This establishes that the per-chunk security compute is small
in absolute terms and does not scale adversely with chunk size.

### Conclusion

The graph demonstrates that the proposed hash-and-sign construction is
consistently cheaper than payload signing and that its signature cost is
independent of chunk size. It substantiates the choice of Ed25519-over-hash plus
Merkle proofs on efficiency grounds.

### Limitations

These are isolated primitive timings on one machine; they exclude network,
serialization, and blockchain costs (measured in later graphs). Absolute
millisecond values are hardware-dependent; the relative comparison is the
transferable result. The naive baseline uses Ed25519 over the payload — an
RSA payload baseline is examined separately in Graph 5.

---

## Graph 2 — Authentication Performance

### Objective

Measure the per-request authentication delay and success rate of the complete
chunk-verification mechanism as request volume grows, and decompose where that
delay is spent.

### Research Question

Does the proposed blockchain-backed authentication remain fast and reliable as
request volume grows — a bounded per-request delay and zero false rejections of
legitimate content?

### Motivation

Verification runs on every chunk delivery. If per-request cost grew with load,
or if legitimate content were occasionally rejected, the mechanism would be
unusable in practice. This graph tests both properties directly.

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone2_auth_performance.py`
- **Setup:** the real publish pipeline (`publish_content`) registers producers,
  Merkle roots and trees on the live ledger, and wraps manifests via ECIES.
- **One authentication request** executes the full implemented chain:
  1. serving node — `get_merkle_tree` (real gRPC) → `get_merkle_proof`;
  2. receiver — `get_content_root` (gRPC) → `verify_merkle_proof` →
     `get_producer_key` (gRPC) → `verify_chunk_signature`;
  3. consumer — manifest ECIES unwrap (cached per content) → hash match →
     `decrypt_chunk` → re-hash.
- **Backends:** the real `FabricLedger` and an in-memory `SimulatedLedger`
  running the identical chain, to isolate the blockchain's contribution.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Request counts (N) | 100, 200, … 1000 |
| Content pool | 4 contents × 16 chunks, round-robin |
| Requests executed | 5,500 Fabric + 5,500 simulated |
| Fabric | orderer + `peer0.org1` (Fabric 2.5), single peer |

Software/hardware: Python 3.11.9, `grpcio` 1.82.1, Windows 10. Scripts run from
`app/` so `.env` credential paths resolve.

### Metrics Collected

- **Directly measured:** per-request end-to-end delay (ms) and the ten
  individual component timings; per-request success/failure.
- **Derived:** per-(backend, N) mean/std/min/max delay, success rate, and mean
  per-component time.
- **Calculated:** none.

### Raw Data

- `data/m2_auth_performance_raw.csv` — 11,000 rows (one per executed request).
- `data/m2_auth_performance_summary.csv` — per (backend, N) aggregates.

### Figure

`graphs/graph2_authentication_performance.png` (and `.pdf`).

### Results

Measured values (from `m2_auth_performance_summary.csv`):

- **Success rate: 100.0% at every N**, across all 5,500 Fabric-backed requests
  (and 5,500 simulated). No legitimate request was rejected.
- **Delay is bounded and flat**, not growing with N: Fabric mean delay ranges
  ~14.6–20.7 ms across N = 100…1000 with no upward trend.
- **Decomposition:** the three ledger gRPC reads dominate (~4.7–6.9 ms each);
  all local cryptography combined (proof verify ~0.05 ms, signature verify
  ~0.25 ms, decrypt ~0.03 ms, re-hash ~0.02 ms) totals well under 0.5 ms. The
  simulated backend mean delay is ~0.19–0.27 ms, confirming that the security
  computation itself is inexpensive.

### Discussion

The per-request cost is dominated by blockchain read latency, not cryptography,
and does not increase with the number of requests. Because the ledger reads are
constant per request and cacheable (root, tree and producer key are static for
a published content), the mechanism scales with load. The near-zero simulated
delay isolates the cryptographic verification as effectively free relative to
the ledger round-trips.

### Conclusion

The graph demonstrates bounded, load-independent authentication delay with a
100% success rate over 5,500 live blockchain-verified requests, validating the
mechanism's reliability and per-request efficiency.

### Limitations

Measurements use a single-peer Fabric network on one host; multi-peer
endorsement and WAN latency are not represented. The 100% success rate concerns
*legitimate* content only — rejection of *tampered* content is the subject of
Graph 7. Ledger-read caching is applied to the manifest (per content) as in the
implementation but not to root/tree/key reads, so measured delay is an upper
bound relative to a fully cached deployment.

---

## Graph 3 — Blockchain Registration Performance

### Objective

Compare the registration latency and transaction cost of anchoring one Merkle
root per content object against conventional per-chunk on-chain hash
registration, as the number of chunks grows.

### Research Question

Does anchoring a single Merkle root per content object reduce registration
latency and blockchain transaction count relative to registering every chunk
hash individually, and how does the gap scale with chunk count?

### Motivation

The registration step (`publish_content`, Step 4.5) is where on-chain cost is
incurred at publish time. Whether the Merkle-root aggregation meaningfully
reduces that cost is a central claim of the architecture and must be measured
against the naive alternative.

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone3_registration.py`
- **Conventional scheme:** one real write transaction per chunk hash, submitted
  sequentially, each a full Endorse → Submit → CommitStatus cycle.
- **Proposed scheme:** exactly as implemented —
  `build_merkle_tree` (client-side) + `register_content_root` (1 tx) +
  `store_merkle_tree` (1 tx).
- **Chunk data:** produced by the system's own synthesiser
  (`_synthetic_chunk_bytes`) hashed with `chunk_hash`.
- **Execution path:** every transaction is timed individually and recorded; the
  transaction count is incremented only after a submit returns committed.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Chunk counts (N) | 5, 10, 20, 40, 80, 160 |
| Proposed repetitions | 3 per N (2 tx each) |
| Conventional repetitions | 1 per N (N tx each) |
| Fabric | orderer + `peer0.org1` (Fabric 2.5), single peer |

Software/hardware: Python 3.11.9, Windows 10. Measured single-transaction
commit latency was ~2.0 s on this network, which set the practical N ceiling.

### Metrics Collected

- **Directly measured:** end-to-end registration wall-clock time per run; each
  individual transaction latency; count of committed transactions.
- **Derived:** per-(scheme, N) mean/std registration time; component split
  (Merkle build, root tx, tree tx) for the proposed scheme.
- **Calculated:** none.

### Raw Data

- `data/m3_registration_tx_raw.csv` — 351 rows, one per committed transaction.
- `data/m3_registration_runs.csv` — per-run records.
- `data/m3_registration_summary.csv` — per-(scheme, N) aggregates.

### Figure

`graphs/graph3_blockchain_registration_performance.png` (and `.pdf`).

### Results

Measured registration time and transaction count:

| N (chunks) | Conventional time / tx | Proposed time / tx |
|-----------:|-----------------------:|-------------------:|
| 5   | 10.3 s / 5   | 4.1 s / 2 |
| 40  | 82.3 s / 40  | 4.1 s / 2 |
| 160 | 327.4 s / 160 | 4.1 s / 2 |

Conventional registration grows linearly (~2.05 s per chunk, the commit
latency); the proposed scheme is flat at 4.1 s and 2 transactions regardless of
chunk count. The client-side Merkle build is sub-millisecond and invisible at
this scale. At N = 160 this is an ~80× reduction in both registration time and
transaction count.

### Discussion

The dominant cost of on-chain registration is per-transaction commit latency,
not payload processing. Collapsing N per-chunk anchors into a single root
converts an O(N) transaction cost into O(1), which the data confirms directly.
The second transaction stores the full Merkle tree as a serving-time
convenience; its byte cost (not its transaction count) is examined in Graph 4.

### Conclusion

The graph proves that Merkle-root registration makes publish-time on-chain cost
independent of content size, whereas per-chunk registration scales linearly,
yielding an order-of-magnitude reduction at modest chunk counts.

### Limitations

Commit latency (~2 s) is specific to this single-peer Fabric configuration and
ordering service; absolute times would differ on other deployments, though the
O(N) vs O(1) relationship would not. Conventional registration was run once per
N (the per-transaction distribution is captured in the raw CSV); the proposed
scheme was repeated three times.

---

## Graph 4 — Blockchain Storage Overhead

### Objective

Measure the on-chain state footprint of alternative content-integrity storage
strategies as a function of chunk count, and confirm the storage complexity of
the proposed single-root anchor.

### Research Question

How many bytes of on-chain state does each storage strategy consume as chunk
count grows, and does the proposed Merkle-root anchor achieve the O(1) footprint
the architecture claims?

### Motivation

Blockchain state is a scarce, replicated, permanent resource. The choice to
anchor only a Merkle root — rather than full per-chunk metadata or all chunk
hashes — is justified only if the storage saving is real and scales favourably.

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone4_storage_overhead.py`
- **Strategies (each written to chaincode, then read back):**
  *full_metadata* (per-chunk public record: hash, locator, nonce, signature;
  AES keys are secret and never on-chain), *chunk_hashes* (JSON list of
  hashes), *merkle_root* (one 64-hex root — the proposed anchor), and
  *merkle_tree* (the full `tree_levels` the implementation additionally stores).
- **Chunk records** come from the real pipeline (`_synthetic_chunk_bytes` →
  `chunk_hash` → `encrypt_chunk` → `sign_chunk`).
- **Execution path:** each strategy is written via the real ledger API, read
  back via a real Evaluate call, the returned payload asserted identical to what
  was written, and its size measured as `len(key) + len(value)` in bytes.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Chunk counts (N) | 100, 500, 1000 |
| Strategies | 4 (12 real write+read-back measurements) |
| Fabric | orderer + `peer0.org1` (Fabric 2.5), single peer |

Software/hardware: Python 3.11.9, Windows 10.

### Metrics Collected

- **Directly measured:** stored bytes per (strategy, N), from the payload
  actually returned by the ledger; per-write transaction time.
- **Derived:** amortised bytes-per-chunk (measured bytes ÷ N) in panel (b).
- **Calculated:** none.

### Raw Data

- `data/m4_storage_overhead_raw.csv` — 12 rows, one per write+read-back
  measurement.

### Figure

`graphs/graph4_blockchain_storage_overhead.png` (and `.pdf`).

### Results

Measured on-chain bytes (from `m4_storage_overhead_raw.csv`):

| Strategy | 100 chunks | 500 | 1000 | Scaling |
|----------|-----------:|----:|-----:|---------|
| Full per-chunk metadata | 31,215 | 156,415 | 313,916 | O(N), ~314 B/chunk |
| Per-chunk hashes | 6,823 | 34,023 | 68,024 | O(N), ~68 B/chunk |
| Merkle tree (impl. extra) | 13,977 | 68,245 | 136,248 | O(N), ~136 B/chunk |
| **Merkle root (proposed)** | **85** | **85** | **86** | **O(1)** |

The Merkle root is constant (~85 bytes) irrespective of chunk count. At
N = 1000 this is a ~3,651× reduction versus full metadata and ~791× versus
per-chunk hashes. Panel (b) shows every alternative flat in bytes-per-chunk
(i.e. O(N) total), while the root's per-chunk cost tends toward zero.

### Discussion

The proposed anchor achieves constant on-chain storage while retaining per-chunk
verifiability through Merkle proofs (whose cost is quantified in Graphs 1–2).
The graph also makes explicit an implementation choice: the current code stores
the full Merkle tree on-chain (~136 B/chunk) as a serving-time convenience,
which is O(N) and exceeds plain hash storage. The root alone is cryptographically
sufficient; storing the tree off-chain or caching it at serving nodes would
preserve the O(1) on-chain footprint.

### Conclusion

The graph proves that the proposed root anchor consumes constant on-chain state,
in contrast to the linear growth of all per-chunk strategies — a concrete,
measured storage-efficiency result.

### Limitations

Sizes are measured at the application payload level (key + value bytes) and do
not include Fabric block, endorsement, or world-state indexing overhead, which
adds a roughly constant per-key increment. The O(N) tree-storage finding is a
property of the current implementation, not of the architecture, and is flagged
as an optimisation opportunity rather than a necessity.

---

## Graph 5 — Security Overhead Comparison

### Objective

Compare the total end-to-end security overhead (publisher processing +
blockchain interaction + consumer verification of every chunk) of the proposed
mechanism against three alternative designs, as chunk count grows.

### Research Question

What is the total security overhead of the proposed mechanism relative to the
alternatives it rejected — RSA-2048 authentication, ECC/ECDSA-P256
authentication, and existing per-chunk on-chain blockchain-ICN anchoring — and
how does it scale?

### Motivation

Graphs 3–4 examined publish-time and storage costs in isolation. This graph
asks the integrative question: across the full security lifecycle, is the
proposed design competitive with the alternatives a reviewer would propose?

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone5_security_overhead.py`
- **Schemes (all executed on identical chunk data):**
  - *rsa* — RSA-2048 PSS sign/verify over the hash (no blockchain);
  - *ecdsa* — ECDSA-P256 sign/verify over the hash (no blockchain);
  - *existing* — per-chunk hash anchored on-chain: one real write tx per chunk
    at publish, one real ledger query per chunk at verify;
  - *proposed* — the real pipeline: per-chunk hash/encrypt/Ed25519-sign +
    `build_merkle_tree` + 2 txs at publish; full receiver chain (3 ledger reads,
    proof, signature, decrypt, re-hash) per chunk at verify.
- **Chunk data:** the system's own synthesiser; the proposed scheme uses the
  unmodified `crypto_auth`; RSA/ECDSA baselines exist only in the
  instrumentation file, using the same `cryptography` library.
- **Execution path:** each component (`publisher_compute`, `chain_write`,
  `chain_read`, `consumer_compute`) is `perf_counter`-timed; run totals are the
  sum of the same run's components. Key generation is measured but reported
  separately and excluded from per-content totals.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Chunk counts (N) | 10, 20, 40, 80, 160 |
| Repetitions | rsa/ecdsa ×5, proposed ×3, existing ×1 |
| Real transactions | 352 write tx |
| Real queries | 1,410 ledger reads |
| Fabric | orderer + `peer0.org1` (Fabric 2.5), single peer |

Software/hardware: Python 3.11.9, `cryptography` 49.0.0, Windows 10.

### Metrics Collected

- **Directly measured:** the four component times per run; transaction and query
  counts; key-generation time (separate).
- **Derived:** per-run total (sum of components); per-(scheme, N) mean/std;
  composition percentages at N = 160.
- **Calculated:** none.

### Raw Data

- `data/m5_security_overhead_runs.csv` — 70 run rows with per-component times.
- `data/m5_security_overhead_summary.csv` — per-(scheme, N) aggregates.

### Figure

`graphs/graph5_security_overhead_comparison.png` (and `.pdf`).

### Results

Measured total overhead at N = 160 (from `m5_security_overhead_summary.csv`):

| Scheme | Total (N=160) | Transactions | Dominant component |
|--------|--------------:|-------------:|--------------------|
| Existing blockchain-ICN | 325.5 s | 160 | chain writes (99.8%) |
| Proposed | 7.2 s | 2 | chain writes + reads |
| RSA-2048 | 431 ms | 0 | RSA signing (~92%) |
| ECDSA-P256 | 55 ms | 0 | verification |

Between the two blockchain-anchored schemes, the proposed design is ~45× cheaper
at N = 160 while performing additional work (encryption, signatures, Merkle
proofs). Among the compute-only baselines, RSA is the slowest (its publisher
compute is ~398 ms at N = 160); ECDSA is the cheapest overall but provides no
decentralized trust anchoring.

### Discussion

The graph separates the two design decisions with independent evidence. First,
compared with the existing per-chunk on-chain approach under the same trust
model, Merkle-root aggregation reduces total overhead by ~45× at N = 160,
because transaction count drops from N to 2. Second, the compute-only baselines
bound the cryptographic floor: the proposed scheme's entire compute (publisher +
consumer, ~98 ms at N = 160) sits near the ECDSA floor and roughly 4× below RSA.
The remaining growth in the proposed scheme is per-chunk ledger *reads*
(~2.96 s of the 7.2 s at N = 160), which read-side caching would flatten.

### Conclusion

The graph proves that, among blockchain-anchored designs, the proposed mechanism
is substantially cheaper end-to-end, and that its cryptographic choices sit at
the efficient (ECC) end of the spectrum rather than the RSA end.

### Limitations

Pure RSA/ECC baselines are faster in wall-clock than any blockchain scheme but
provide no decentralized trust; the architecturally fair comparison is between
the two blockchain-anchored schemes. Timings are single-host and single-peer;
ledger-read latency dominates the proposed scheme and is deployment-specific.
The existing-ICN scheme was run once per N due to its cost.

---

## Graph 6 — Key Management Overhead

### Objective

Quantify the number of managed keys and the key-distribution memory of the
implemented per-chunk-key design, versus chunk-group keys and one session key
per content, and measure the compromise blast radius of each.

### Research Question

What does the implemented one-key-per-chunk design cost in managed keys and
key-distribution memory, and what containment benefit does that cost buy when a
single key is leaked?

### Motivation

Per-chunk keys are the most expensive key strategy by construction. The design
is justified only if the overhead is modest relative to the containment benefit,
which requires measuring both the cost and the benefit rather than asserting
them.

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone6_key_management.py`
- **Strategies (every chunk of every strategy really encrypted):**
  *per_chunk* (implemented — fresh key per chunk via `encrypt_chunk`, real
  `ChunkRecord`s, real `build_manifest`, real ECIES wrap), *group* (one key per
  16-chunk group, fresh nonce per chunk), *session* (one key for the whole
  content, fresh nonce per chunk).
- **Blast-radius experiment:** the first key of each strategy's key store is
  "leaked", then a *real* AES-GCM decryption is attempted against every chunk
  ciphertext; the count that actually decrypt is recorded (`InvalidTag` = safe).
- **Chunk data:** the system's own synthesiser.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Chunk counts (N) | 100, 200, … 1000 |
| Group size | 16 |
| Real encryptions | ~6,000 across the sweep |
| Real decrypt attempts | ~3,000 (blast-radius experiment) |
| Blockchain | Not involved |

Software/hardware: Python 3.11.9, `cryptography` 49.0.0, Windows 10.

### Metrics Collected

- **Directly measured:** count of distinct keys actually used; serialized
  manifest bytes; ECIES-wrapped bytes; raw key-material bytes; keygen/encrypt
  times; chunks actually decrypted by one leaked key.
- **Derived:** none for the plotted quantities (all counts/sizes are measured).
- **Calculated:** none.

### Raw Data

- `data/m6_key_management_raw.csv` — 30 rows (one per strategy × N).

### Figure

`graphs/graph6_key_management_overhead.png` (and `.pdf`).

### Results

Measured at N = 1000 (from `m6_key_management_raw.csv`):

| Strategy | Managed keys | Manifest size | Chunks opened by one leaked key |
|----------|-------------:|--------------:|--------------------------------:|
| One key per chunk (implemented) | 1,000 | ~193 KB | **1** |
| Chunk-group key (16) | 63 | ~134 KB | 16 |
| One session key per content | 1 | ~114 KB | **1,000** |

The per-chunk design manages 1,000 keys versus 1, yet the key-distribution
manifest grows only ~1.7× (193 KB vs 114 KB), because manifest size is dominated
by the per-chunk hash and locator entries every strategy needs. In the leak
experiment, one session key decrypted all 1,000 chunks, one group key decrypted
16, and one per-chunk key decrypted exactly 1.

### Discussion

The cost of the per-chunk strategy is real but modest: under a 2× manifest-size
increase, the compromise blast radius is reduced by three orders of magnitude
relative to a session key. Because the manifest is ECIES-wrapped per consumer,
per-chunk keys additionally enable future per-chunk access control or revocation
without re-encrypting the whole content. Key generation and encryption time were
measured and are negligible.

### Conclusion

The graph proves that per-chunk keying reduces single-key compromise from
total-content exposure to a single chunk, at a memory cost under 2×, quantifying
the security/overhead trade-off the architecture makes.

### Limitations

The blast-radius experiment models a single leaked key; it does not model key
distribution security, attacker access to multiple keys, or side channels.
Manifest sizes are application-level serialized bytes and exclude transport
compression. Group size (16) is one representative configuration.

---

## Graph 7 — Security Effectiveness

### Objective

Determine whether the implemented verification chain actually detects tampered
chunks — at what rate, with what overall classification accuracy — as the
fraction of tampered chunks increases, and identify which defence layer catches
each attack type.

### Research Question

Does the implemented verification mechanism detect tampered chunks and classify
correctly overall (without falsely rejecting clean content) as the tampered
fraction grows from 0% to 50%?

### Motivation

All preceding graphs measure cost. This graph measures the benefit that justifies
the cost: the mechanism must actually reject corrupted content while never
rejecting legitimate content. Without this, efficiency is irrelevant.

### Instrumentation

- **Script:** `benchmark/instrumentation/milestone7_security_effectiveness.py`
- **Setup:** one 200-chunk content is published through the real pipeline, with
  producer key, Merkle root and tree registered on the live ledger and the
  manifest ECIES-wrapped — so the ledger holds the legitimate trust anchors.
- **Attacks (applied to copies of in-flight message fields only; ledger and
  publisher state untouched):** *payload_flip* (ciphertext byte corruption),
  *substitution* (attacker plaintext with its genuine hash, encrypted under the
  attacker's key), *sig_forgery* (signature replaced with random bytes).
  Tampered chunks are selected by a seeded RNG and assigned a mode round-robin.
- **Verification:** the real receiver chain per chunk — `get_merkle_tree`
  (gRPC) → proof → `get_content_root` (gRPC) → `verify_merkle_proof` →
  `get_producer_key` (gRPC) → `verify_chunk_signature` → manifest hash match →
  `decrypt_chunk` → re-hash. A chunk is flagged if any stage fails; the first
  failing stage is recorded.

### Experimental Setup

| Parameter | Value |
|-----------|-------|
| Content size | 200 chunks |
| Tamper levels | 0, 10, 20, 30, 40, 50% |
| Repetitions | 3 (seeded, reproducible) |
| Chunk verifications | 3,600 (900 tampered, 2,700 clean) |
| Ledger reads | ~10,800 |
| Fabric | orderer + `peer0.org1` (Fabric 2.5), single peer |

Software/hardware: Python 3.11.9, Windows 10. Seed controllable via
`--seed-base`.

### Metrics Collected

- **Directly measured:** per-chunk flagged/not-flagged and first failing stage;
  per-chunk verification time; tampered/clean ground truth.
- **Derived:** confusion counts (TP/FN/FP/TN), detection rate
  (TP / (TP+FN)), and accuracy ((TP+TN) / N) per tamper level.
- **Calculated:** none.

### Raw Data

- `data/m7_security_effectiveness_raw.csv` — 3,600 rows (one per verification).
- `data/m7_security_effectiveness_summary.csv` — per-tamper-level aggregates.

### Figure

`graphs/graph7_security_effectiveness.png` (and `.pdf`).

### Results

From `m7_security_effectiveness_summary.csv`:

- **Detection rate: 100.0% at every non-zero tamper level** (TP = 900,
  FN = 0 across all runs). At 0% the rate is undefined (no tampered chunks) and
  is omitted from the curve.
- **Accuracy: 100.0% at every level including 0%** — zero false positives across
  2,700 clean verifications (FP = 0, TN = 2,700).
- **Defence layers (panel b):** each attack class was caught by a distinct
  stage — payload flips by the AES-GCM auth tag, full substitution by the Merkle
  proof against the on-chain root, signature forgery by Ed25519 verification. No
  tampered chunk went undetected.

### Discussion

The layered design is non-redundant: removing any single layer would admit one
of the three attack classes (payload flips pass Merkle and signature checks;
substitution passes GCM under the attacker's own key but fails against the
on-chain root; forged signatures pass Merkle). Combined with Graphs 1–2, which
show this verification costs under 0.5 ms of local cryptography per chunk plus
cacheable ledger reads, the mechanism achieves complete tamper detection at
negligible marginal cost on this dataset.

### Conclusion

The graph proves that the implemented mechanism detected 100% of tampered chunks
across three attack models with zero false rejection of legitimate content, and
that its defence layers are complementary rather than redundant.

### Limitations

The three attack models are representative, not exhaustive; adversaries with
access to the producer's private key or the ability to write to the ledger are
out of scope (the trust model assumes ledger integrity). Results are for a
single 200-chunk content over three seeded repetitions; "100%" is an empirical
observation on this experiment, not a formal proof of soundness. The mechanism
detects tampering — it does not by itself locate the malicious node or recover
the correct content.

---

# Overall Evaluation Summary

The seven figures collectively characterise the proposed ICN security
architecture across the dimensions specified by the research guide:

- **Cryptographic efficiency (Graph 1).** Signing a fixed-size hash decouples
  signature cost from chunk size and is up to ~48× cheaper than payload signing
  at 1 MB chunks; Merkle proof operations remain sub-0.07 ms.
- **Authentication performance (Graph 2).** Per-request delay is bounded and
  load-independent (~15–21 ms, dominated by cacheable ledger reads) with a 100%
  success rate over 5,500 live requests.
- **Blockchain scalability (Graph 3).** Merkle-root registration is O(1) in
  transactions and time (2 tx, 4.1 s) versus O(N) for per-chunk registration
  (~80× faster at 160 chunks).
- **Storage efficiency (Graph 4).** The root anchor is constant (~85 bytes)
  regardless of chunk count, versus linear growth for all per-chunk strategies
  (~3,651× smaller than full metadata at 1000 chunks).
- **Security overhead (Graph 5).** Among blockchain-anchored designs the
  proposed mechanism is ~45× cheaper end-to-end than per-chunk anchoring, and
  its cryptographic floor sits near ECDSA rather than RSA.
- **Key management (Graph 6).** Per-chunk keying costs under 2× manifest memory
  while reducing single-key compromise blast radius by three orders of magnitude
  (1 chunk vs the entire content).
- **Attack detection (Graph 7).** 100% detection of tampered chunks across three
  attack models with zero false positives, via complementary defence layers.

Taken together, the data supports the architecture's central thesis: aggregating
per-chunk integrity into a single on-chain Merkle root, combined with
hash-anchored Ed25519 signatures and per-chunk keys, delivers strong,
demonstrable content security while keeping blockchain transaction, storage, and
verification costs low and independent of content size. The principal cost
identified is blockchain read/commit latency, which is deployment-specific and
amenable to caching.

---

# Open Questions, Assumptions and Reviewer Notes

This section is an engineering notebook for later report writing. It records
assumptions, decisions, concerns, and items requiring guide confirmation. It is
maintained as a living document alongside the figures.

### Assumptions made

- **Trust model.** The ledger is assumed correct and tamper-resistant; producer
  private keys are assumed uncompromised. Graph 7's attacks are all in-network
  (content-in-flight) attacks under this assumption.
- **Chunk data.** All graphs use the system's synthetic chunk generator
  (`_synthetic_chunk_bytes`). Cryptographic and storage costs depend on chunk
  *size/count*, not content, so this is considered representative; this should be
  confirmed as acceptable for the report.
- **Single-peer Fabric.** All on-chain measurements use one orderer and one peer
  (Fabric 2.5). Absolute latencies would change with multi-peer endorsement.

### Implementation decisions

- Instrumentation is fully external to the simulator; no `app/` source file was
  modified. Scripts run from `app/` so `.env` relative credential paths resolve.
- RSA/ECDSA baselines (Graph 5) and group/session key strategies (Graph 6) exist
  only inside the instrumentation files, since the production system implements
  neither.
- The proposed scheme's per-chunk verification issues three separate ledger
  reads (tree, root, key). These were deliberately left uncached in Graphs 2, 5
  and 7 to report an upper bound; the manifest is cached per content as in the
  implementation.

### Concerns and limitations to disclose

- The on-chain **Merkle tree storage** (Graph 4) is O(N) and currently dominates
  the deployment's real on-chain footprint. This is an implementation choice, not
  an architectural necessity; recommend moving trees off-chain or caching at
  serving nodes and anchoring only the root.
- "100%" detection/success figures (Graphs 2, 7) are empirical results on the
  tested datasets and attack models, not formal guarantees.
- Absolute blockchain timings are specific to this host and Fabric config.

### Possible reviewer questions

- *Why Ed25519 rather than ECDSA-P256, given ECDSA was cheapest in Graph 5?*
  (Ed25519 offers deterministic signatures and comparable performance; worth
  stating explicitly.)
- *Does the 2 s commit latency reflect Fabric tuning or the ordering service
  batch timeout?* (Batch timeout configuration should be documented.)
- *How would multi-peer endorsement change Graphs 2–5 and 7?*
- *What is the WAN/real-network impact on the ~15 ms authentication delay?*

### Items requiring guide confirmation

- Whether synthetic chunk data is acceptable, or whether a real content corpus
  is expected for the paper.
- Whether the chunk-count ranges (up to 160 for on-chain graphs, 1000 for
  compute/storage graphs) are sufficient, or larger sweeps are required.
- Whether an RSA *and* ECDSA blockchain-anchored variant should be added to
  Graph 5 for completeness.

### Future improvements

- Add read-side caching (root/tree/key) and re-measure Graphs 2 and 5 to show the
  cached lower bound.
- Multi-peer Fabric measurements to characterise endorsement scaling.
- Off-chain Merkle tree storage variant for Graph 4.
- Larger and real-content datasets; multiple hardware profiles for absolute-time
  transferability.

### Doubts encountered during instrumentation

- The Fabric peer became unavailable once mid-session (Docker restart across a
  day boundary); the affected run (Graph 5) was re-executed from scratch after
  verifying ledger connectivity, and only the complete re-run is reported.
- The publish bootstrap reported `mychannel` already existing on a persisted
  volume; this was confirmed benign via a write/read round-trip before any
  measurement was taken.

> **Maintenance note.** After each newly completed milestone, append the new
> graph's documentation using the same section template, and update the Overall
> Evaluation Summary. Preserve heading structure, table formatting, and the
> measured-vs-derived distinction throughout.
