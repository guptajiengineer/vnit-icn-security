from __future__ import annotations

import hashlib
import json
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple, TYPE_CHECKING

from models import BaseTopology, ChunkRecord, ContentSpec

if TYPE_CHECKING:
    from fabric.chain import Ledger
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


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
    consumer_public_key: "Optional[X25519PublicKey]" = None,
    producer_private_key: "Optional[Ed25519PrivateKey]" = None,
) -> Tuple[List[Dict], List[ChunkRecord], Optional[bytes]]:
    """
    Execute Steps 1–6 of the cryptographic authentication protocol for one
    content object.

    Step 1 — Producer registration
    --------------------------------
    If *producer_private_key* is None, generate a fresh Ed25519 keypair and
    register the public key on the ledger.  If a key is supplied, that key is
    used for signing and no ledger write is performed — the caller is responsible
    for ensuring the matching public key is already registered.  Callers that
    publish multiple content objects for the same producer_id must supply the
    same private key for every call; otherwise the ledger entry would be
    overwritten and earlier ChunkRecord signatures would no longer verify.

    Step 2 — Content chunking (reuses existing count, no new logic)
    ----------------------------------------------------------------
    ``chunk_count`` is accepted as a parameter from the caller (NetworkScenario
    derives it as the number of simultaneously selected multipath records).

    Step 2.5 — Per-chunk SHA-256 hash generation

    Step 3 — Per-chunk AES-256-GCM encryption (fresh key + nonce per chunk)

    Step 4 — Per-chunk Ed25519 signature over the chunk hash
    ---------------------------------------------------------
    sign_chunk(private_key, chunk_hash) signs the hex-encoded SHA-256 hash of
    each chunk's plaintext.  The signature is stored in ChunkRecord.chunk_signature
    and attached to outgoing DataMessages by NetworkScenario so receivers can
    verify the chunk came from the registered producer.

    Step 4.5 — Blockchain registration via Merkle root
    ---------------------------------------------------
    Build a binary Merkle tree over all chunk hashes.  Register only the root
    on the ledger (O(1) on-chain footprint regardless of chunk count).  Also
    store the full tree_levels via ledger.store_merkle_tree() so per-chunk
    proofs can be derived at serving time.

    Step 5 — Consumer manifest wrapping (optional)
    -----------------------------------------------
    If ``consumer_public_key`` is supplied, the plaintext manifest
    (List[{chunk_hash, chunk_locator, chunk_key}]) is JSON-serialised and
    encrypted with ECIES-style hybrid encryption (X25519 + HKDF + AES-256-GCM)
    so only the holder of the corresponding private key can read the chunk keys.
    The wrapped bytes are returned as the third element of the return tuple.

    Parameters
    ----------
    content_spec : ContentSpec
    chunk_count : int   — must be >= 1
    ledger : Ledger
    producer_id : str
    consumer_public_key : Optional[X25519PublicKey]
        If provided, the manifest is wrapped for this consumer.

    Returns
    -------
    (manifest, chunk_records, wrapped_manifest)
        manifest         : plaintext manifest (JSON-serialisable list).
        chunk_records    : List[ChunkRecord] carrying all crypto material.
        wrapped_manifest : ECIES-wrapped manifest bytes, or None if
                           consumer_public_key was not supplied.

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
    # Step 1: Producer registration.
    # If the caller supplies a producer_private_key the producer is already
    # registered on the ledger — skip generation and re-registration so that
    # the on-ledger public key stays stable across multiple publish_content
    # calls for the same producer_id.  Overwriting the ledger entry would
    # invalidate all ChunkRecord signatures produced by earlier calls.
    # ------------------------------------------------------------------
    if producer_private_key is not None:
        private_key = producer_private_key
    else:
        private_key, pub_key_bytes = crypto_auth.generate_producer_keypair()
        ledger.register_producer(producer_id, pub_key_bytes)

    # ------------------------------------------------------------------
    # Steps 2 + 2.5 + 3 + 4: chunk synthesis → hash → encrypt → sign
    # ------------------------------------------------------------------
    chunk_hashes: List[str] = []
    chunk_records: List[ChunkRecord] = []

    for chunk_id in range(chunk_count):
        # Step 2: deterministic synthetic chunk bytes.
        chunk_bytes = _synthetic_chunk_bytes(content_id, chunk_id)

        # Step 2.5: SHA-256 hash of plaintext.
        h = crypto_auth.chunk_hash(chunk_bytes)
        chunk_hashes.append(h)

        # Step 3: AES-256-GCM encryption (fresh key + nonce per chunk).
        ciphertext, key, nonce = crypto_auth.encrypt_chunk(chunk_bytes)

        # Step 4: Ed25519 signature over the hex-encoded hash.
        signature = crypto_auth.sign_chunk(private_key, h)

        locator = f"{content_id}:{chunk_id}"
        chunk_records.append(
            ChunkRecord(
                chunk_id=chunk_id,
                chunk_hash=h,
                chunk_locator=locator,
                chunk_key=key,
                nonce=nonce,
                ciphertext=ciphertext,
                chunk_signature=signature,
            )
        )

    # ------------------------------------------------------------------
    # Step 4.5: Merkle tree + ledger registration
    # ------------------------------------------------------------------
    root_hash, tree_levels = crypto_auth.build_merkle_tree(chunk_hashes)
    ledger.register_content_root(content_id, root_hash)
    # Use the proper Ledger API (no duck-typing).
    ledger.store_merkle_tree(content_id, tree_levels)

    # ------------------------------------------------------------------
    # Manifest: plaintext key-distribution list (one entry per chunk)
    # ------------------------------------------------------------------
    manifest = crypto_auth.build_manifest(chunk_records)

    # ------------------------------------------------------------------
    # Step 5: Wrap manifest for consumer (ECIES hybrid encryption)
    # ------------------------------------------------------------------
    wrapped_manifest: Optional[bytes] = None
    if consumer_public_key is not None:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        wrapped_manifest = crypto_auth.wrap_manifest_for_consumer(
            manifest_bytes, consumer_public_key
        )

    return manifest, chunk_records, wrapped_manifest
