"""
fabric_client/config.py — Fabric connection configuration.

All values come from environment variables (loaded from .env by python-dotenv).
No absolute paths, no hardcoded values inside source files.

Required environment variables
-------------------------------
FABRIC_PEER_ENDPOINT          e.g. peer0-org1:7051  (Docker service name) or
                              localhost:7051 (bare metal)
FABRIC_PEER_HOSTNAME_OVERRIDE e.g. peer0.org1.example.com
FABRIC_CHANNEL                e.g. mychannel
FABRIC_CHAINCODE              e.g. icnledger
FABRIC_MSP_ID                 e.g. Org1MSP
FABRIC_TLS_CERT_PATH          path to peer's TLS CA cert (PEM)
FABRIC_CERT_PATH              path to Admin user's signing certificate (PEM)
FABRIC_PRIVATE_KEY_PATH       path to Admin user's private key (PEM)

Optional
--------
FABRIC_EVALUATE_TIMEOUT       seconds, default 30
FABRIC_ENDORSE_TIMEOUT        seconds, default 30
FABRIC_SUBMIT_TIMEOUT         seconds, default 30
FABRIC_COMMIT_TIMEOUT         seconds, default 60
FABRIC_MAX_RETRIES            default 3
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass


@dataclass
class FabricConfig:
    peer_endpoint: str
    peer_hostname_override: str
    channel: str
    chaincode: str
    msp_id: str
    tls_cert_path: str
    cert_path: str
    private_key_path: str

    evaluate_timeout: float = 30.0
    endorse_timeout: float = 30.0
    submit_timeout: float = 30.0
    commit_timeout: float = 60.0
    max_retries: int = 3

    @classmethod
    def load(cls) -> "FabricConfig":
        _load_dotenv()

        def _require(name: str) -> str:
            val = os.environ.get(name, "").strip()
            if not val:
                raise EnvironmentError(
                    f"Required environment variable {name!r} is not set. "
                    f"Check your .env file or environment."
                )
            return val

        def _optional_float(name: str, default: float) -> float:
            val = os.environ.get(name, "").strip()
            return float(val) if val else default

        def _optional_int(name: str, default: int) -> int:
            val = os.environ.get(name, "").strip()
            return int(val) if val else default

        return cls(
            peer_endpoint=_require("FABRIC_PEER_ENDPOINT"),
            peer_hostname_override=_require("FABRIC_PEER_HOSTNAME_OVERRIDE"),
            channel=_require("FABRIC_CHANNEL"),
            chaincode=_require("FABRIC_CHAINCODE"),
            msp_id=_require("FABRIC_MSP_ID"),
            tls_cert_path=_require("FABRIC_TLS_CERT_PATH"),
            cert_path=_require("FABRIC_CERT_PATH"),
            private_key_path=_require("FABRIC_PRIVATE_KEY_PATH"),
            evaluate_timeout=_optional_float("FABRIC_EVALUATE_TIMEOUT", 30.0),
            endorse_timeout=_optional_float("FABRIC_ENDORSE_TIMEOUT", 30.0),
            submit_timeout=_optional_float("FABRIC_SUBMIT_TIMEOUT", 30.0),
            commit_timeout=_optional_float("FABRIC_COMMIT_TIMEOUT", 60.0),
            max_retries=_optional_int("FABRIC_MAX_RETRIES", 3),
        )
