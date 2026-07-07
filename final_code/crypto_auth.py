"""
crypto_auth.py — Cryptographic primitives for the ICN authentication layer.

Steps covered
-------------
Step 2.5 — Per-chunk hash generation          (chunk_hash)
Step 3   — Per-chunk encryption               (encrypt_chunk / decrypt_chunk)
Step 4   — Merkle tree + proof                (build_merkle_tree / get_merkle_proof /
                                               verify_merkle_proof)
Step 7   — Manifest building                  (build_manifest)
Step 8   — Manifest encryption (ECIES/hybrid) (wrap_manifest_for_consumer)
           Consumer keypair generation         (generate_consumer_keypair)

Dependencies
------------
  cryptography >= 41.0   (pip install cryptography)
      AESGCM, X25519, HKDF, Ed25519 — all from the 'cryptography' package.

This module has NO imports from any simulator module (models, config, chain …).
It is pure cryptographic utility code that can be unit-tested in isolation.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# --------------------------------------------------------------------------
# cryptography package imports (https://cryptography.io)
# --------------------------------------------------------------------------
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidTag  # re-exported for callers

if TYPE_CHECKING:
    # ChunkRecord is defined in models.py; avoid circular import at runtime.
    from models import ChunkRecord


# ==========================================================================
# Step 2.5 — Per-chunk hash
# ==========================================================================

def chunk_hash(chunk_bytes: bytes) -> str:
    """
    Compute the SHA-256 digest of *chunk_bytes* and return it as a lowercase
    hex string (64 characters).

    Parameters
    ----------
    chunk_bytes : bytes
        The raw bytes of a single content chunk.

    Returns
    -------
    str
        64-character lowercase hex SHA-256 digest.
    """
    return hashlib.sha256(chunk_bytes).hexdigest()


# ==========================================================================
# Step 3 — Per-chunk encryption / decryption (AES-256-GCM)
# ==========================================================================

_AES_KEY_LEN   = 32  # bytes — AES-256
_AES_NONCE_LEN = 12  # bytes — 96-bit nonce (GCM standard)


def encrypt_chunk(chunk_bytes: bytes) -> Tuple[bytes, bytes, bytes]:
    """
    Encrypt *chunk_bytes* with AES-256-GCM using a freshly generated random
    key and nonce.

    A new key and nonce are generated for *every* call, so each chunk has
    an independent encryption context — compromise of one chunk key does not
    affect any other chunk.

    Parameters
    ----------
    chunk_bytes : bytes
        Plaintext chunk data.

    Returns
    -------
    (ciphertext, key, nonce) : Tuple[bytes, bytes, bytes]
        ciphertext : authenticated ciphertext (includes GCM auth tag).
        key        : 32-byte AES-256 key.
        nonce      : 12-byte GCM nonce.

    Notes
    -----
    AES-256-GCM provides both confidentiality and integrity. The GCM
    authentication tag (appended to ciphertext by the `cryptography` library)
    means that `decrypt_chunk` will raise `InvalidTag` if the ciphertext or
    key/nonce are tampered with — this is how cache-poisoning is detected.
    """
    key   = os.urandom(_AES_KEY_LEN)
    nonce = os.urandom(_AES_NONCE_LEN)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, chunk_bytes, associated_data=None)
    return ciphertext, key, nonce


def decrypt_chunk(ciphertext: bytes, key: bytes, nonce: bytes) -> bytes:
    """
    Decrypt and verify *ciphertext* produced by :func:`encrypt_chunk`.

    Parameters
    ----------
    ciphertext : bytes
        Authenticated ciphertext (includes the GCM tag appended by encrypt).
    key : bytes
        32-byte AES-256 key used during encryption.
    nonce : bytes
        12-byte GCM nonce used during encryption.

    Returns
    -------
    bytes
        Recovered plaintext.

    Raises
    ------
    cryptography.exceptions.InvalidTag
        If authentication fails — the ciphertext, key, or nonce has been
        tampered with.
    """
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=None)


# ==========================================================================
# Step 4 — Merkle tree, proof generation, and proof verification
# ==========================================================================

def _hash_pair(left: str, right: str) -> str:
    """SHA-256 of the concatenation of two hex-digest strings."""
    combined = (left + right).encode("ascii")
    return hashlib.sha256(combined).hexdigest()


def build_merkle_tree(leaf_hashes: List[str]) -> Tuple[str, List[List[str]]]:
    """
    Build a binary Merkle tree from a list of leaf hashes and return the
    root hash together with the full tree structure (needed for proof generation).

    Parameters
    ----------
    leaf_hashes : List[str]
        Ordered list of hex-encoded SHA-256 chunk hashes (output of
        :func:`chunk_hash`).  Must be non-empty.

    Returns
    -------
    (root_hash, tree_levels) : Tuple[str, List[List[str]]]
        root_hash   : Merkle root hex string (the value stored on-chain).
        tree_levels : List of levels, tree_levels[0] = padded leaf layer,
                      tree_levels[-1] = [root_hash].

    Notes
    -----
    - If the number of leaves is odd the last leaf is duplicated to make an
      even-width level, following the standard Bitcoin Merkle tree convention.
    - A single-leaf tree has root_hash == leaf_hashes[0].
    - The tree_levels list is what you pass to :func:`get_merkle_proof`.

    Raises
    ------
    ValueError
        If *leaf_hashes* is empty.
    """
    if not leaf_hashes:
        raise ValueError("build_merkle_tree: leaf_hashes must be non-empty")

    current_level: List[str] = list(leaf_hashes)
    tree_levels: List[List[str]] = [current_level]

    while len(current_level) > 1:
        # Pad to even length by duplicating the last element.
        if len(current_level) % 2 == 1:
            current_level = current_level + [current_level[-1]]
            # Also update the already-appended level so proofs are consistent.
            tree_levels[-1] = current_level

        next_level: List[str] = []
        for i in range(0, len(current_level), 2):
            next_level.append(_hash_pair(current_level[i], current_level[i + 1]))

        tree_levels.append(next_level)
        current_level = next_level

    root_hash = current_level[0]
    return root_hash, tree_levels


def get_merkle_proof(tree_levels: List[List[str]], leaf_index: int) -> List[str]:
    """
    Extract the sibling-path (Merkle proof) for the leaf at *leaf_index*.

    Parameters
    ----------
    tree_levels : List[List[str]]
        The ``tree_levels`` returned by :func:`build_merkle_tree`.
    leaf_index : int
        Zero-based index of the target leaf in the original (pre-padding)
        leaf list.

    Returns
    -------
    List[str]
        Ordered list of sibling hashes from leaf level up to (but not
        including) the root.  Each entry is the hash of the node that must
        be combined with the current node to move one level up.
        Pass this list to :func:`verify_merkle_proof`.

    Notes
    -----
    The proof list encodes sibling position implicitly: if *leaf_index* is
    even the sibling is to the right (index + 1); if odd it is to the left
    (index - 1).  :func:`verify_merkle_proof` re-derives this from the proof
    index being even/odd at each level.
    """
    proof: List[str] = []
    index = leaf_index

    # Walk up every level except the root level.
    for level in tree_levels[:-1]:
        if index % 2 == 0:
            # Current node is a left child; sibling is to the right.
            sibling_index = index + 1
        else:
            # Current node is a right child; sibling is to the left.
            sibling_index = index - 1

        if sibling_index < len(level):
            proof.append(level[sibling_index])
        else:
            # Padded duplicate: sibling == self.
            proof.append(level[index])

        index //= 2

    return proof


def verify_merkle_proof(
    leaf_hash: str,
    proof: List[str],
    root_hash: str,
) -> bool:
    """
    Verify that *leaf_hash* is a member of the Merkle tree with *root_hash*,
    given the sibling-path *proof*.

    Parameters
    ----------
    leaf_hash : str
        Hex-encoded SHA-256 hash of the chunk being verified.
    proof : List[str]
        Sibling path returned by :func:`get_merkle_proof`.
    root_hash : str
        Hex-encoded Merkle root retrieved from the ledger.

    Returns
    -------
    bool
        True if the proof is valid and the leaf is in the tree; False otherwise.

    Notes
    -----
    An empty proof is valid only if leaf_hash == root_hash (single-leaf tree).
    A tampered leaf_hash, wrong proof element, or mismatched root returns False.
    """
    if not leaf_hash or not root_hash:
        return False

    current = leaf_hash
    for level_index, sibling in enumerate(proof):
        # The position of the current node at this level determines the
        # hash order (left || right vs right || left).
        # We re-derive the position from level_index and the original
        # leaf_index embedded in the proof length — but since the proof only
        # contains siblings we determine left/right by whether we descended
        # from an even or odd index.
        #
        # Simpler approach: store a "is_left_child" bit per level.
        # We encode this implicitly: the proof list produced by
        # get_merkle_proof always stores the sibling, and we track parity here.
        #
        # We need to track the index as we go up. We can't recover the original
        # leaf_index from inside this function, so we rely on the proof ordering
        # convention: level_index 0 corresponds to the leaf level, and we stored
        # the sibling (not the node itself) so ordering must be determined by
        # checking which hash is "smaller" — but that's order-sensitive.
        #
        # CORRECT approach: pass the leaf_index alongside the proof.
        # However, to keep the external signature clean (proof is just a list),
        # we embed parity as a separate companion list in the proof.
        # ---
        # REVISED: get_merkle_proof returns plain hashes; verify_merkle_proof
        # needs the leaf_index to determine left/right at each level.
        # We solve this by making verify_merkle_proof accept an optional
        # leaf_index parameter and defaulting to index-unaware hashing
        # (try both orders and accept either). This is safe for verification
        # because we still require the final result to match root_hash.
        #
        # For robustness, we try left-then-right ordering (even index first).
        combined_lr = _hash_pair(current, sibling)
        combined_rl = _hash_pair(sibling, current)
        # We'll propagate both candidates and match at the end, but that grows
        # exponentially. Instead, store the index: callers pass leaf_index.
        # Since leaf_index is NOT in the signature, we always try the
        # correct order by matching against root_hash at the end, traversing
        # a single path. Pick the order that keeps us on the correct path by
        # noting that at each level the node is left if index is even.
        #
        # We cannot know index here without it being passed. Store it in proof?
        # Decision: accept this limitation — without the original leaf_index
        # we try both orders. This means verify may pass for a proof that
        # happens to hit root_hash regardless of order (negligible probability
        # for real SHA-256). For a production system the index would be passed.
        # For the simulated chain this is acceptable.
        #
        # We pick the order that produces the "lower" hash at each step to be
        # deterministic — but that is wrong for tree verification.
        #
        # FINAL decision: embed leaf_index in each proof item as a tuple.
        # But that would break the List[str] type.
        #
        # Cleanest fix: verify_merkle_proof also takes leaf_index.
        # We DO have the leaf_index in network_scenario.py (it's msg.chunk_id).
        # We can store it in merkle_proof[0] as a string and unpack it here.
        #
        # Implementation: the proof list has format:
        #   [str(leaf_index), sibling_0, sibling_1, ...]
        # Both get_merkle_proof and this function use that convention.
        # This keeps List[str] typing clean.
        #
        # Since this is a design decision made inside the implementation,
        # we restructure both functions below. See _NOTE_ in build_merkle_tree.
        del combined_lr, combined_rl
        break  # This loop body is replaced below; kept as documentation only.

    # -----------------------------------------------------------------------
    # ACTUAL implementation (replacing the loop above):
    # See _verify_merkle_proof_internal below.
    # -----------------------------------------------------------------------
    return _verify_merkle_proof_internal(leaf_hash, proof, root_hash)


def _verify_merkle_proof_internal(
    leaf_hash: str,
    proof: List[str],
    root_hash: str,
) -> bool:
    """
    Internal verifier.  *proof* format: [str(leaf_index), sib_0, sib_1, ...].
    The first element encodes the original leaf_index so we know left/right
    at every level without ambiguity.
    """
    if not leaf_hash or not root_hash:
        return False

    if not proof:
        # Single-leaf tree: root IS the leaf.
        return leaf_hash == root_hash

    try:
        leaf_index = int(proof[0])
    except (ValueError, IndexError):
        # Malformed proof.
        return False

    sibling_hashes = proof[1:]
    current = leaf_hash
    index = leaf_index

    for sibling in sibling_hashes:
        if index % 2 == 0:
            # Current node is a left child.
            current = _hash_pair(current, sibling)
        else:
            # Current node is a right child.
            current = _hash_pair(sibling, current)
        index //= 2

    return current == root_hash


# Override get_merkle_proof to embed the leaf_index in the proof list.

def get_merkle_proof(tree_levels: List[List[str]], leaf_index: int) -> List[str]:  # type: ignore[misc]
    """
    Extract the Merkle proof for the leaf at *leaf_index*.

    Proof format
    ------------
    The returned list has the form::

        [str(leaf_index), sibling_at_level_0, sibling_at_level_1, ...]

    The first element is the original *leaf_index* (as a decimal string).
    This allows :func:`verify_merkle_proof` to determine left/right ordering
    at each level without needing the index separately.

    Parameters
    ----------
    tree_levels : List[List[str]]
        ``tree_levels`` from :func:`build_merkle_tree`.
    leaf_index : int
        Zero-based index into the original leaf list.

    Returns
    -------
    List[str]
        Proof list (first element = leaf_index string, rest = sibling hashes).
    """
    proof: List[str] = [str(leaf_index)]
    index = leaf_index

    for level in tree_levels[:-1]:
        if index % 2 == 0:
            sibling_index = index + 1
        else:
            sibling_index = index - 1

        if sibling_index < len(level):
            proof.append(level[sibling_index])
        else:
            proof.append(level[index])  # Padded duplicate.

        index //= 2

    return proof


# ==========================================================================
# Consumer keypair (X25519 — encryption only, NOT identity/signing)
# ==========================================================================

def generate_consumer_keypair() -> Tuple[X25519PrivateKey, X25519PublicKey]:
    """
    Generate a fresh X25519 Diffie-Hellman keypair for a consumer node.

    This keypair is used exclusively for hybrid manifest encryption
    (ECDH + HKDF + AES-256-GCM).  It is **not** an Ed25519 signing key and
    must not be confused with the producer's identity/signing keypair.

    Returns
    -------
    (private_key, public_key) : Tuple[X25519PrivateKey, X25519PublicKey]
        Both are objects from ``cryptography.hazmat.primitives.asymmetric.x25519``.
    """
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def consumer_public_key_bytes(public_key: X25519PublicKey) -> bytes:
    """
    Serialise an X25519 public key to 32 raw bytes (RFC 7748 format).

    Convenience helper for storing/transmitting the public key.
    """
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def consumer_public_key_from_bytes(raw_bytes: bytes) -> X25519PublicKey:
    """
    Deserialise 32 raw bytes back into an X25519PublicKey object.
    """
    return X25519PublicKey.from_public_bytes(raw_bytes)


# ==========================================================================
# Step 7 — Manifest building
# ==========================================================================

def build_manifest(chunk_records: "List[ChunkRecord]") -> List[Dict[str, Any]]:  # type: ignore[type-arg]
    """
    Build the content manifest: one entry per chunk, containing enough
    information for an authorised consumer to locate, verify, and decrypt
    each chunk.

    Parameters
    ----------
    chunk_records : List[ChunkRecord]
        The records produced by ``publish_content()`` in ``content.py``.
        Each record carries chunk_id, chunk_hash, chunk_locator, chunk_key,
        and ciphertext.

    Returns
    -------
    List[Dict[str, Any]]
        Ordered list (by chunk_id) of dicts with keys:
        - ``chunk_hash``    : str  — hex SHA-256 of the plaintext chunk.
        - ``chunk_locator`` : str  — content-addressed locator
                                     ``"{content_id}:{chunk_id}"``.
                                     Deliberately NOT tied to a physical
                                     network path (multipath is dynamic).
        - ``chunk_key``     : str  — hex-encoded 32-byte AES-256 key.
                                     (hex so the manifest is JSON-serialisable)

    Notes
    -----
    The ciphertext itself is NOT included in the manifest.  The manifest
    tells a consumer *how* to decrypt a chunk once it retrieves it via the
    ICN name resolution layer (which handles path selection).
    The nonce is NOT in the manifest either; it must be stored alongside the
    ciphertext in the ChunkRecord for retrieval (the DataMessage path is the
    retrieval mechanism here — nonce is stored with the encrypted content at
    the producer, outside the manifest).
    """
    manifest: List[Dict[str, Any]] = []
    for record in sorted(chunk_records, key=lambda r: r.chunk_id):
        manifest.append(
            {
                "chunk_hash":    record.chunk_hash,
                "chunk_locator": record.chunk_locator,
                "chunk_key":     record.chunk_key.hex(),
            }
        )
    return manifest


# ==========================================================================
# Step 8 — Manifest encryption (ECIES / hybrid encryption for consumer)
# ==========================================================================

_HKDF_INFO  = b"ICN-manifest-v1"
_HKDF_LEN   = 32  # bytes — derive a 256-bit AES key
_NONCE_SIZE = 12  # bytes — AES-256-GCM nonce


def wrap_manifest_for_consumer(
    manifest_bytes: bytes,
    consumer_public_key: X25519PublicKey,
) -> bytes:
    """
    Encrypt *manifest_bytes* for a specific consumer using ECIES-style hybrid
    encryption: ephemeral X25519 ECDH → HKDF-SHA256 → AES-256-GCM.

    Protocol
    --------
    1. Generate an ephemeral X25519 keypair (used once, discarded after).
    2. Perform ECDH between the ephemeral private key and the consumer's
       long-term X25519 public key to obtain a shared secret.
    3. Derive a 256-bit symmetric key from the shared secret using
       HKDF-SHA256 (info = b"ICN-manifest-v1").
    4. Encrypt *manifest_bytes* with AES-256-GCM using the derived key and
       a fresh random 12-byte nonce.
    5. Return: ephemeral_pub_bytes (32) || nonce (12) || ciphertext.

    Parameters
    ----------
    manifest_bytes : bytes
        JSON-serialised (or otherwise bytes-encoded) manifest.
    consumer_public_key : X25519PublicKey
        The consumer's long-term X25519 public key (from
        :func:`generate_consumer_keypair`).

    Returns
    -------
    bytes
        Concatenation: ephemeral_public_key_bytes (32) + nonce (12) +
        AES-GCM ciphertext (len(manifest_bytes) + 16 tag bytes).

    Notes
    -----
    - RSA is deliberately NOT used (per spec).
    - The ephemeral public key is transmitted in the clear; the shared secret
      is never transmitted.
    - A consumer decrypts by: ECDH(consumer_private, ephemeral_pub) → HKDF →
      AES-256-GCM decrypt.  (Decryption helper: :func:`unwrap_manifest_for_consumer`)
    """
    # Step 1: ephemeral keypair.
    ephemeral_private = X25519PrivateKey.generate()
    ephemeral_public  = ephemeral_private.public_key()

    # Step 2: ECDH shared secret.
    shared_secret: bytes = ephemeral_private.exchange(consumer_public_key)

    # Step 3: HKDF key derivation.
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_HKDF_LEN,
        salt=None,
        info=_HKDF_INFO,
    )
    symmetric_key: bytes = hkdf.derive(shared_secret)

    # Step 4: AES-256-GCM encryption.
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(symmetric_key)
    ciphertext = aesgcm.encrypt(nonce, manifest_bytes, associated_data=None)

    # Step 5: serialise ephemeral public key.
    ephemeral_pub_bytes = ephemeral_public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return ephemeral_pub_bytes + nonce + ciphertext


def unwrap_manifest_for_consumer(
    wrapped: bytes,
    consumer_private_key: X25519PrivateKey,
) -> bytes:
    """
    Decrypt a manifest encrypted with :func:`wrap_manifest_for_consumer`.

    Parameters
    ----------
    wrapped : bytes
        Output of :func:`wrap_manifest_for_consumer`.
    consumer_private_key : X25519PrivateKey
        The consumer's private key corresponding to the public key used
        during wrapping.

    Returns
    -------
    bytes
        Decrypted manifest bytes.

    Raises
    ------
    cryptography.exceptions.InvalidTag
        If authentication fails (wrong key, tampered ciphertext).
    ValueError
        If *wrapped* is too short to contain the header.
    """
    header_size = 32 + _NONCE_SIZE  # ephemeral_pub + nonce
    if len(wrapped) < header_size:
        raise ValueError(
            f"unwrap_manifest_for_consumer: wrapped payload too short "
            f"(got {len(wrapped)} bytes, need at least {header_size})"
        )

    ephemeral_pub_bytes = wrapped[:32]
    nonce               = wrapped[32:32 + _NONCE_SIZE]
    ciphertext          = wrapped[32 + _NONCE_SIZE:]

    ephemeral_public = X25519PublicKey.from_public_bytes(ephemeral_pub_bytes)
    shared_secret    = consumer_private_key.exchange(ephemeral_public)

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_HKDF_LEN,
        salt=None,
        info=_HKDF_INFO,
    )
    symmetric_key = hkdf.derive(shared_secret)

    aesgcm = AESGCM(symmetric_key)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=None)


# ==========================================================================
# Producer identity keypair (Ed25519 — signing / on-chain identity only)
# ==========================================================================

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def generate_producer_keypair() -> Tuple[Ed25519PrivateKey, bytes]:
    """
    Generate an Ed25519 signing keypair for a producer.

    This is the producer's *identity* key — the public key bytes are stored
    on-chain via ``Ledger.register_producer()``.  This is entirely separate
    from the consumer's X25519 encryption key.

    Returns
    -------
    (private_key, public_key_bytes) : Tuple[Ed25519PrivateKey, bytes]
        private_key      : Ed25519PrivateKey object (kept secret at producer).
        public_key_bytes : 32 raw bytes of the Ed25519 public key
                           (stored on-chain).
    """
    private_key = Ed25519PrivateKey.generate()
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, public_key_bytes
