from __future__ import annotations

import hashlib
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple, TYPE_CHECKING

from models import BaseTopology, ChunkRecord, ContentSpec

if TYPE_CHECKING:
    from chain import Ledger


def build_default_content_specs(content_count: int) -> List[ContentSpec]:
    if content_count <= 0:
        raise ValueError("content_count must be > 0")

    content_specs: List[ContentSpec] = []
    for content_index in range(content_count):
        content_specs.append(
            ContentSpec(
                content_id=f"a{content_index + 1}",
                generation_round=-(content_index + 2),
                lifespan_rounds=8 + (2 * content_index),
                cache_cost=6.0 + (1.5 * content_index),
                availability_threshold=0.22,
                lifetime_threshold=0.0,
                popularity=max(0.35, 1.0 - (0.14 * content_index)),
            )
        )
    return content_specs


def content_provider_ids(
    base: BaseTopology,
    active_publishers: Sequence[str],
    content_id: str,
    include_cached_providers: bool,
    content_publishers: Optional[Dict[str, Sequence[str]]] = None,
) -> List[str]:
    if content_publishers is None:
        provider_ids = list(dict.fromkeys(active_publishers))
    else:
        provider_ids = list(dict.fromkeys(content_publishers.get(content_id, active_publishers)))
    if not include_cached_providers:
        return provider_ids

    cached_provider_ids = sorted(
        node_id
        for node_id, node in base.nodes.items()
        if content_id in node.cached_contents and node_id not in provider_ids
    )
    return provider_ids + cached_provider_ids


def assign_content_publishers(
    active_publishers: Sequence[str],
    content_specs: Sequence[ContentSpec],
    min_publishers_per_content: int,
    seed: int,
) -> Dict[str, List[str]]:
    if min_publishers_per_content <= 0:
        raise ValueError("min_publishers_per_content must be > 0")

    provider_ids = list(dict.fromkeys(active_publishers))
    ordered_contents = sorted(content_specs, key=lambda item: item.content_id)
    if not ordered_contents:
        return {}
    if not provider_ids:
        return {content.content_id: [] for content in ordered_contents}

    min_k = min(len(provider_ids) - 1, max(1, min_publishers_per_content))
    rng = random.Random(seed)
    content_publishers: Dict[str, Set[str]] = {
        content.content_id: set()
        for content in ordered_contents
    }
    content_ids = [content.content_id for content in ordered_contents]

    # Give every active producer at least one randomly chosen content first.
    shuffled_providers = list(provider_ids)
    rng.shuffle(shuffled_providers)
    for provider_id in shuffled_providers:
        chosen_content_id = content_ids[rng.randrange(len(content_ids))]
        content_publishers[chosen_content_id].add(provider_id)

    for content in ordered_contents:
        assigned_providers = content_publishers[content.content_id]
        while len(assigned_providers) < min_k:
            remaining = [
                provider_id
                for provider_id in provider_ids
                if provider_id not in assigned_providers
            ]
            if not remaining:
                break
            assigned_providers.add(rng.choice(remaining))

        remaining = [
            provider_id
            for provider_id in provider_ids
            if provider_id not in assigned_providers
        ]
        if remaining:
            extra_replicas = rng.randint(0, len(remaining))
            rng.shuffle(remaining)
            assigned_providers.update(remaining[:extra_replicas])

    return {
        content_id: sorted(provider_ids_for_content)
        for content_id, provider_ids_for_content in content_publishers.items()
    }

#tosee
def build_request_cycle(content_specs: Sequence[ContentSpec]) -> List[str]:
    weighted_cycle: List[str] = []
    for content in sorted(content_specs, key=lambda item: (-item.popularity, item.content_id)):
        repeats = max(1, round(content.popularity * 4))
        weighted_cycle.extend([content.content_id] * repeats)
    weighted_cycle = ["a1", "a2"]
    return weighted_cycle


# ---------------------------------------------------------------------------
# Obj2 addition — publish_content()
# ---------------------------------------------------------------------------

def _synthetic_chunk_bytes(content_id: str, chunk_id: int) -> bytes:
    """
    Generate deterministic pseudo-bytes for a simulated chunk.

    Since the ICN simulator has no actual content objects (content is purely
    virtual / path-mapped), we synthesise chunk bytes as the SHA-256 digest
    of the string "{content_id}:{chunk_id}".  This gives 32 bytes of
    deterministic, unique, non-trivial data per chunk that can be hashed
    and encrypted like real content.

    The synthesis is deterministic: the same (content_id, chunk_id) always
    produces the same bytes, which means a verifier can independently re-derive
    expected hashes without storing the original plaintext — appropriate for a
    simulation environment.
    """
    return hashlib.sha256(f"{content_id}:{chunk_id}".encode()).digest()


def publish_content(
    content_spec: ContentSpec,
    chunk_count: int,
    ledger: "Ledger",
    producer_id: str,
) -> Tuple[List[Dict], List[ChunkRecord]]:
    """
    Execute Steps 1–4 of the cryptographic authentication protocol for one
    content object.

    Step 1 — Producer registration
    --------------------------------
    If ``producer_id`` is not yet registered on the ledger, generate an Ed25519
    keypair and register the public key.  This is idempotent — calling
    publish_content multiple times for the same producer is safe.

    Step 2 — Content chunking (reuses existing count, no new logic)
    ----------------------------------------------------------------
    ``chunk_count`` is the number of chunks to produce.  The caller passes the
    same value that ``NetworkScenario`` derives at runtime (= number of selected
    multipath records), so the auth layer is always consistent with the network
    layer.  We do NOT recompute chunk_count here — we accept it as a parameter.

    Step 2.5 — Per-chunk hash generation
    -------------------------------------
    For each chunk i, compute SHA-256(chunk_bytes_i).

    Step 3 — Per-chunk encryption
    --------------------------------
    For each chunk i, encrypt with AES-256-GCM (fresh key + nonce per chunk).

    Step 4 — Blockchain hash registration via Merkle root
    -------------------------------------------------------
    Build a binary Merkle tree over all chunk hashes, then register only the
    root on the ledger.  This keeps on-chain footprint O(1) per content object
    regardless of chunk count — ready for real Fabric/Iroha swap-in.

    Parameters
    ----------
    content_spec : ContentSpec
        The content specification (provides content_id).
    chunk_count : int
        Number of chunks to produce.  Must be >= 1.
    ledger : Ledger
        The chain interface to register producer and content root.
    producer_id : str
        The node_id (or stable identifier) of the producing node.

    Returns
    -------
    (manifest, chunk_records) : Tuple[List[Dict], List[ChunkRecord]]
        manifest      : JSON-serialisable list of {chunk_hash, chunk_locator,
                        chunk_key} dicts — one entry per chunk.
        chunk_records : List of ChunkRecord objects carrying all crypto material
                        (used by NetworkScenario to attach hash+proof to
                        outgoing DataMessages).

    Raises
    ------
    ValueError
        If chunk_count < 1.
    """
    # Local imports to avoid circular dependency at module level.
    import crypto_auth

    if chunk_count < 1:
        raise ValueError(f"publish_content: chunk_count must be >= 1, got {chunk_count}")

    content_id = content_spec.content_id

    # ------------------------------------------------------------------
    # Step 1: Producer registration (simulated on-chain)
    # ------------------------------------------------------------------
    if not ledger.is_producer_registered(producer_id):  # type: ignore[attr-defined]
        # SimulatedLedger exposes is_producer_registered(); for real ledgers
        # this check can be omitted (register is idempotent).
        _private_key, pub_key_bytes = crypto_auth.generate_producer_keypair()
        ledger.register_producer(producer_id, pub_key_bytes)

    # ------------------------------------------------------------------
    # Steps 2 + 2.5 + 3: chunk synthesis → hash → encrypt
    # ------------------------------------------------------------------
    chunk_hashes: List[str] = []
    chunk_records: List[ChunkRecord] = []

    for chunk_id in range(chunk_count):
        # Step 2: synthesise chunk bytes (deterministic pseudo-content).
        chunk_bytes = _synthetic_chunk_bytes(content_id, chunk_id)

        # Step 2.5: per-chunk hash.
        h = crypto_auth.chunk_hash(chunk_bytes)
        chunk_hashes.append(h)

        # Step 3: per-chunk encryption.
        ciphertext, key, nonce = crypto_auth.encrypt_chunk(chunk_bytes)

        locator = f"{content_id}:{chunk_id}"
        chunk_records.append(
            ChunkRecord(
                chunk_id=chunk_id,
                chunk_hash=h,
                chunk_locator=locator,
                chunk_key=key,
                nonce=nonce,
                ciphertext=ciphertext,
            )
        )

    # ------------------------------------------------------------------
    # Step 4: Merkle tree + ledger registration
    # ------------------------------------------------------------------
    root_hash, tree_levels = crypto_auth.build_merkle_tree(chunk_hashes)
    ledger.register_content_root(content_id, root_hash)

    # Store tree_levels on the ledger so NetworkScenario can retrieve proofs.
    # SimulatedLedger stores it via a secondary attribute; real ledgers would
    # reconstruct the tree from the chunk_records kept at the producer.
    # We attach it directly to the ledger object here to avoid API surface bloat.
    if not hasattr(ledger, "_merkle_trees"):
        ledger._merkle_trees: Dict[str, List[List[str]]] = {}  # type: ignore[attr-defined]
    ledger._merkle_trees[content_id] = tree_levels  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Build manifest (Step 7 utility — no consumer key here, just the list)
    # ------------------------------------------------------------------
    manifest = crypto_auth.build_manifest(chunk_records)

    return manifest, chunk_records
