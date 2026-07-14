"""
fabric_client/client.py — Hyperledger Fabric Gateway gRPC client.

Implements the Fabric Gateway protocol directly over gRPC:
  Evaluate  → Endorse  + no commit   (query / read-only)
  Submit    → Endorse  → sign → Submit → CommitStatus  (transaction / write)

No subprocess.  No WSL.  No peer CLI.  No helper scripts.
All configuration comes from environment / .env file via FabricConfig.

Architecture
------------
FabricGatewayClient
  ├─ _build_proposal()     build ChaincodeProposalPayload + Header
  ├─ _sign()               Ed25519 or ECDSA-P256 signing
  ├─ evaluate()            read-only chaincode call (no ledger write)
  └─ submit()              endorsing + ordering + commit-wait

FabricLedger (in chain.py) delegates exclusively to this class.
"""

from __future__ import annotations

import hashlib
import os
import struct
import time
import uuid
from typing import List, Optional

import grpc

from fabric_client.config import FabricConfig
from fabric_client.proto.common import common_pb2
from fabric_client.proto.gateway import gateway_pb2, gateway_pb2_grpc
from fabric_client.proto.msp import identities_pb2
from fabric_client.proto.peer import chaincode_pb2, proposal_pb2


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FabricConnectionError(RuntimeError):
    """Raised when the gRPC channel cannot reach the peer."""


class FabricTransactionError(RuntimeError):
    """Raised when a transaction is rejected by the peer or orderer."""


class FabricTimeoutError(FabricTransactionError):
    """Raised when a transaction does not commit within the timeout."""


class FabricChaincodeError(FabricTransactionError):
    """Raised when the chaincode itself returns an error response."""


class FabricLedgerKeyError(KeyError):
    """Raised when a queried key is not found on the ledger (empty result)."""


# ---------------------------------------------------------------------------
# FabricGatewayClient
# ---------------------------------------------------------------------------

class FabricGatewayClient:
    """
    Persistent gRPC connection to the Fabric Gateway service running inside
    the peer.  Provides evaluate() (query) and submit() (transaction) methods.

    Parameters
    ----------
    config : FabricConfig
        Loaded from .env / environment.  Contains endpoint URLs, TLS certs,
        MSP identity, channel name, chaincode name.

    Usage
    -----
    client = FabricGatewayClient(FabricConfig.load())
    result = client.evaluate("GetProducerKey", ["producer-001"])
    client.submit("RegisterProducer", ["producer-001", "aabb..."])
    """

    def __init__(self, config: FabricConfig) -> None:
        self._cfg = config
        self._identity_bytes = self._build_serialized_identity()
        self._private_key = self._load_private_key()
        self._channel: Optional[grpc.Channel] = None
        self._stub: Optional[gateway_pb2_grpc.GatewayStub] = None
        self._connect()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        tls_cert = self._load_file(self._cfg.tls_cert_path)
        credentials = grpc.ssl_channel_credentials(root_certificates=tls_cert)
        options = [
            ("grpc.ssl_target_name_override", self._cfg.peer_hostname_override),
            ("grpc.keepalive_time_ms", 30_000),
            ("grpc.keepalive_timeout_ms", 10_000),
            ("grpc.keepalive_permit_without_calls", 1),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ]
        self._channel = grpc.secure_channel(
            self._cfg.peer_endpoint, credentials, options=options
        )
        self._stub = gateway_pb2_grpc.GatewayStub(self._channel)

    def _ensure_connected(self) -> None:
        if self._stub is None:
            self._connect()

    def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None
            self._stub = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, func: str, args: List[str]) -> bytes:
        """
        Evaluate a chaincode function (read-only, no ledger write).

        Parameters
        ----------
        func : str
            Chaincode function name, e.g. "GetProducerKey".
        args : List[str]
            String arguments for the function.

        Returns
        -------
        bytes
            Raw payload bytes returned by the chaincode.

        Raises
        ------
        FabricConnectionError   — peer unreachable
        FabricChaincodeError    — chaincode returned an error
        """
        self._ensure_connected()
        tx_id, proposal_bytes, signed_proposal = self._build_signed_proposal(func, args)
        request = gateway_pb2.EvaluateRequest(
            transaction_id=tx_id,
            channel_id=self._cfg.channel,
            proposed_transaction=signed_proposal,
        )
        try:
            response = self._stub.Evaluate(
                request,
                timeout=self._cfg.evaluate_timeout,
            )
        except grpc.RpcError as exc:
            raise self._wrap_grpc_error(exc, "Evaluate", func) from exc
        return response.result.payload

    def submit(self, func: str, args: List[str]) -> None:
        """
        Submit a chaincode transaction (endorses, orders, waits for commit).

        Parameters
        ----------
        func : str
            Chaincode function name, e.g. "RegisterProducer".
        args : List[str]
            String arguments for the function.

        Raises
        ------
        FabricConnectionError   — peer unreachable
        FabricTransactionError  — endorsement or ordering failure
        FabricTimeoutError      — commit did not confirm in time
        FabricChaincodeError    — chaincode returned an error
        """
        self._ensure_connected()
        tx_id, proposal_bytes, signed_proposal = self._build_signed_proposal(func, args)

        # Step 1: Endorse
        endorse_req = gateway_pb2.EndorseRequest(
            transaction_id=tx_id,
            channel_id=self._cfg.channel,
            proposed_transaction=signed_proposal,
        )
        try:
            endorse_resp = self._stub.Endorse(
                endorse_req,
                timeout=self._cfg.endorse_timeout,
            )
        except grpc.RpcError as exc:
            raise self._wrap_grpc_error(exc, "Endorse", func) from exc

        # Step 2: Sign the prepared transaction envelope
        prepared_envelope = endorse_resp.prepared_transaction
        envelope_sig = self._sign(prepared_envelope.payload)
        prepared_envelope.signature = envelope_sig

        # Step 3: Submit to ordering service
        submit_req = gateway_pb2.SubmitRequest(
            transaction_id=tx_id,
            channel_id=self._cfg.channel,
            prepared_transaction=prepared_envelope,
        )
        try:
            self._stub.Submit(
                submit_req,
                timeout=self._cfg.submit_timeout,
            )
        except grpc.RpcError as exc:
            raise self._wrap_grpc_error(exc, "Submit", func) from exc

        # Step 4: Wait for commit
        self._wait_for_commit(tx_id)

    # ------------------------------------------------------------------
    # Proposal construction
    # ------------------------------------------------------------------

    def _build_signed_proposal(
        self, func: str, args: List[str]
    ):
        nonce = os.urandom(24)
        tx_id = self._compute_tx_id(nonce)
        proposal_bytes = self._build_proposal(func, args, tx_id, nonce)
        sig = self._sign(proposal_bytes)
        signed_proposal = proposal_pb2.SignedProposal(
            proposal_bytes=proposal_bytes,
            signature=sig,
        )
        return tx_id, proposal_bytes, signed_proposal

    def _compute_tx_id(self, nonce: bytes) -> str:
        return hashlib.sha256(nonce + self._identity_bytes).hexdigest()

    def _build_proposal(self, func: str, args: List[str], tx_id: str, nonce: bytes) -> bytes:

        # ChaincodeInput
        chaincode_input = chaincode_pb2.ChaincodeInput(
            args=[func.encode()] + [a.encode() for a in args]
        )
        chaincode_spec = chaincode_pb2.ChaincodeSpec(
            type=chaincode_pb2.ChaincodeSpec.GOLANG,
            chaincode_id=chaincode_pb2.ChaincodeID(name=self._cfg.chaincode),
            input=chaincode_input,
        )
        chaincode_invocation_spec = chaincode_pb2.ChaincodeInvocationSpec(
            chaincode_spec=chaincode_spec,
        )

        # Creator (serialized identity)
        creator = self._identity_bytes

        # Header extensions
        chaincode_header_ext = proposal_pb2.ChaincodeHeaderExtension(
            chaincode_id=chaincode_pb2.ChaincodeID(name=self._cfg.chaincode)
        )
        chaincode_header_ext_bytes = chaincode_header_ext.SerializeToString()

        # ChannelHeader
        channel_header = common_pb2.ChannelHeader(
            type=common_pb2.HeaderType.Value("ENDORSER_TRANSACTION"),
            version=1,
            timestamp=self._now_timestamp(),
            channel_id=self._cfg.channel,
            tx_id=tx_id,
            epoch=0,
            extension=chaincode_header_ext_bytes,
        )
        channel_header_bytes = channel_header.SerializeToString()

        # SignatureHeader
        sig_header = common_pb2.SignatureHeader(
            creator=creator,
            nonce=nonce,
        )
        sig_header_bytes = sig_header.SerializeToString()

        # Header
        header = common_pb2.Header(
            channel_header=channel_header_bytes,
            signature_header=sig_header_bytes,
        )

        # ChaincodeProposalPayload
        cpp = proposal_pb2.ChaincodeProposalPayload(
            input=chaincode_invocation_spec.SerializeToString(),
        )

        # Proposal
        proposal = proposal_pb2.Proposal(
            header=header.SerializeToString(),
            payload=cpp.SerializeToString(),
        )
        return proposal.SerializeToString()

    # ------------------------------------------------------------------
    # Commit status
    # ------------------------------------------------------------------

    def _wait_for_commit(self, tx_id: str) -> None:
        from fabric_client.proto.common import common_pb2 as cpb2
        from fabric_client.proto.gateway import gateway_pb2 as gpb2

        commit_req = gateway_pb2.CommitStatusRequest(
            transaction_id=tx_id,
            channel_id=self._cfg.channel,
            identity=self._identity_bytes,
        )
        req_bytes = commit_req.SerializeToString()
        sig = self._sign(req_bytes)
        signed_commit = gateway_pb2.SignedCommitStatusRequest(
            request=req_bytes,
            signature=sig,
        )
        try:
            resp = self._stub.CommitStatus(
                signed_commit,
                timeout=self._cfg.commit_timeout,
            )
        except grpc.RpcError as exc:
            raise self._wrap_grpc_error(exc, "CommitStatus", tx_id) from exc

        # TxValidationCode 0 = VALID
        if resp.result != 0:
            raise FabricTransactionError(
                f"Transaction {tx_id} committed with invalid status: {resp.result}"
            )

    # ------------------------------------------------------------------
    # Identity and signing
    # ------------------------------------------------------------------

    def _build_serialized_identity(self) -> bytes:
        cert_pem = self._load_file(self._cfg.cert_path)
        identity = identities_pb2.SerializedIdentity(
            mspid=self._cfg.msp_id,
            id_bytes=cert_pem,
        )
        return identity.SerializeToString()

    def _load_private_key(self):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key_pem = self._load_file(self._cfg.private_key_path)
        return load_pem_private_key(key_pem, password=None)

    def _sign(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives.asymmetric.ec import (
            ECDSA, EllipticCurvePrivateKey,
        )
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import hashes

        if isinstance(self._private_key, Ed25519PrivateKey):
            return self._private_key.sign(data)
        elif isinstance(self._private_key, EllipticCurvePrivateKey):
            der_sig = self._private_key.sign(data, ECDSA(hashes.SHA256()))
            return self._low_s_signature(der_sig, self._private_key.curve)
        else:
            raise TypeError(f"Unsupported key type: {type(self._private_key)}")

    @staticmethod
    def _low_s_signature(der_sig: bytes, curve) -> bytes:
        """
        Fabric's BCCSP enforces low-S ECDSA signatures (S <= order/2).
        Normalise a DER-encoded signature so that S is always in the lower half.
        """
        from cryptography.hazmat.primitives.asymmetric.utils import (
            decode_dss_signature, encode_dss_signature,
        )
        from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, SECP256K1
        r, s = decode_dss_signature(der_sig)
        if isinstance(curve, SECP256R1):
            order = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
        elif isinstance(curve, SECP256K1):
            order = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        else:
            return der_sig
        half_order = order >> 1
        if s > half_order:
            s = order - s
        return encode_dss_signature(r, s)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_file(path: str) -> bytes:
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as exc:
            raise FabricConnectionError(
                f"Cannot read Fabric credential file {path!r}: {exc}"
            ) from exc

    @staticmethod
    def _now_timestamp():
        from google.protobuf.timestamp_pb2 import Timestamp
        ts = Timestamp()
        ts.GetCurrentTime()
        return ts

    @staticmethod
    def _wrap_grpc_error(
        exc: grpc.RpcError, operation: str, target: str
    ) -> FabricTransactionError:
        code = exc.code() if hasattr(exc, "code") else "?"
        details = exc.details() if hasattr(exc, "details") else str(exc)
        if code == grpc.StatusCode.UNAVAILABLE:
            return FabricConnectionError(
                f"Fabric peer unavailable during {operation}({target}): {details}"
            )
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            return FabricTimeoutError(
                f"Fabric {operation}({target}) timed out: {details}"
            )
        if "chaincode" in details.lower() and "error" in details.lower():
            return FabricChaincodeError(
                f"Chaincode error in {operation}({target}): {details}"
            )
        return FabricTransactionError(
            f"Fabric {operation}({target}) failed [{code}]: {details}"
        )
