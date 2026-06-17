"""
chain.py — Ledger abstraction for the ICN blockchain authentication layer.

Design contract
---------------
`Ledger` is an ABC that defines the minimum on-chain API required by the
authentication layer.  All application code (content.py, network_scenario.py,
experiments.py) imports and types against `Ledger` only.

`SimulatedLedger` is the Phase-1 concrete implementation: plain in-memory dicts,
no persistence, no real distributed ledger.  When Hyperledger Fabric or Iroha are
integrated in a later phase, a new class (e.g. `FabricLedger(Ledger)`) implementing
the same four methods replaces `SimulatedLedger` at the call-site in experiments.py
— **no other file needs to change**.

Step covered
------------
Step 1 — Producer registration (simulated on-chain)
Step 4 — Blockchain hash registration (Merkle root storage + retrieval)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class Ledger(ABC):
    """
    Minimal on-chain API required by the cryptographic authentication layer.

    Implementors
    ------------
    - SimulatedLedger   : Phase 1 (this file) — in-memory dict, no I/O.
    - FabricLedger      : Phase 2 (future)     — Hyperledger Fabric gateway.
    - IrohaLedger       : Phase 2 (future)     — Iroha gRPC client.
    """

    @abstractmethod
    def register_producer(self, producer_id: str, public_key: bytes) -> None:
        """
        Register a content producer on the ledger.

        Parameters
        ----------
        producer_id : str
            A unique identifier for the producer (e.g. a node_id from the
            network topology, or a stable UUID assigned at startup).
        public_key : bytes
            The producer's Ed25519 public key (32 bytes) used as an on-chain
            identity anchor.  This is *not* the consumer X25519 encryption key.

        Notes
        -----
        Calling this for an already-registered producer_id is idempotent —
        implementations should overwrite the stored key so that key rotation
        is possible without requiring a separate "update" method.
        """
        ...

    @abstractmethod
    def register_content_root(self, content_id: str, merkle_root: str) -> None:
        """
        Record the Merkle root of a content object's chunk-hash tree.

        Parameters
        ----------
        content_id : str
            The ICN name / content identifier (e.g. "a1", "a2").
        merkle_root : str
            Hex-encoded SHA-256 Merkle root over all chunk hashes for this
            content object.

        Notes
        -----
        Registering the Merkle root rather than per-chunk hashes is a deliberate
        design choice to minimise on-chain footprint.  When real Fabric/Iroha
        transactions are used the root becomes a single transaction per content
        object, regardless of chunk count.
        """
        ...

    @abstractmethod
    def get_content_root(self, content_id: str) -> str:
        """
        Retrieve the previously registered Merkle root for a content object.

        Parameters
        ----------
        content_id : str

        Returns
        -------
        str
            Hex-encoded Merkle root.

        Raises
        ------
        KeyError
            If no root has been registered for ``content_id``.
        """
        ...

    @abstractmethod
    def get_producer_key(self, producer_id: str) -> bytes:
        """
        Retrieve the public key registered for a producer.

        Parameters
        ----------
        producer_id : str

        Returns
        -------
        bytes
            Ed25519 public key bytes (32 bytes).

        Raises
        ------
        KeyError
            If ``producer_id`` has not been registered.
        """
        ...


# ---------------------------------------------------------------------------
# Phase-1 concrete implementation: in-memory simulation
# ---------------------------------------------------------------------------

class SimulatedLedger(Ledger):
    """
    In-memory ledger for Phase-1 simulation.

    Storage
    -------
    _producers    : Dict[str, bytes]  — producer_id -> Ed25519 public key bytes
    _content_roots: Dict[str, str]    — content_id  -> Merkle root hex string

    No persistence, no serialisation, no network I/O.  All operations are O(1).

    Swap-out contract
    -----------------
    To replace this with a real chain, implement `Ledger` in a new class and
    pass that instance wherever `SimulatedLedger()` is currently constructed
    (see `experiments.py`).  Application code imports only `Ledger`; nothing
    else changes.
    """

    def __init__(self) -> None:
        self._producers: Dict[str, bytes] = {}
        self._content_roots: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Ledger interface
    # ------------------------------------------------------------------

    def register_producer(self, producer_id: str, public_key: bytes) -> None:
        """Store or overwrite the producer's public key (idempotent)."""
        self._producers[producer_id] = public_key

    def register_content_root(self, content_id: str, merkle_root: str) -> None:
        """Store or overwrite the Merkle root for a content object."""
        self._content_roots[content_id] = merkle_root

    def get_content_root(self, content_id: str) -> str:
        """
        Return the Merkle root for ``content_id``.

        Raises
        ------
        KeyError
            If content_id has not been registered yet.
        """
        try:
            return self._content_roots[content_id]
        except KeyError:
            raise KeyError(
                f"SimulatedLedger: no Merkle root registered for content_id={content_id!r}"
            ) from None

    def get_producer_key(self, producer_id: str) -> bytes:
        """
        Return the Ed25519 public key for ``producer_id``.

        Raises
        ------
        KeyError
            If producer_id has not been registered yet.
        """
        try:
            return self._producers[producer_id]
        except KeyError:
            raise KeyError(
                f"SimulatedLedger: producer {producer_id!r} is not registered"
            ) from None

    # ------------------------------------------------------------------
    # Convenience helpers (not part of the Ledger contract)
    # ------------------------------------------------------------------

    def is_producer_registered(self, producer_id: str) -> bool:
        """Return True iff the producer has already been registered."""
        return producer_id in self._producers

    def is_content_registered(self, content_id: str) -> bool:
        """Return True iff a Merkle root has been registered for this content."""
        return content_id in self._content_roots

    def __repr__(self) -> str:
        return (
            f"SimulatedLedger("
            f"producers={list(self._producers.keys())}, "
            f"contents={list(self._content_roots.keys())})"
        )
