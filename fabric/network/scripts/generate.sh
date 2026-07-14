#!/usr/bin/env bash
# generate.sh — Run inside hyperledger/fabric-tools:2.5
#
# Mounts (set in docker-compose.yml):
#   /network           ← ./fabric/network     (configtx.yaml + organizations/)
#   /channel-artifacts ← ./fabric/channel-artifacts
#   /creds             ← ./fabric/creds
#
# Idempotent: skips crypto generation if orderer material already exists.
# Re-runs configtxgen every time so the genesis block is always fresh.

set -euo pipefail

CRYPTO_DIR=/network/organizations

echo "================================================================"
echo " ICN Fabric Network — generate.sh"
echo "================================================================"

# ── 1. Crypto material ────────────────────────────────────────────────────
# Check for the actual TLS cert (not just the directory Docker pre-creates for bind mounts)
ORDERER_TLS_CERT="${CRYPTO_DIR}/ordererOrganizations/example.com/orderers/orderer.example.com/tls/server.crt"
if [ -f "${ORDERER_TLS_CERT}" ]; then
  echo "[generate] Crypto material already present — skipping cryptogen."
else
  # Docker Compose pre-creates bind-mount source dirs as empty directories before
  # fabric-generate starts. Cryptogen skips nodes whose directories already exist,
  # so remove those empty shell dirs now so cryptogen generates into them fresh.
  rm -rf "${CRYPTO_DIR}/ordererOrganizations/example.com/orderers"
  rm -rf "${CRYPTO_DIR}/peerOrganizations/org1.example.com/peers"

  echo "[generate] Generating orderer crypto material..."
  cryptogen generate \
    --config=/network/organizations/cryptogen/crypto-config-orderer.yaml \
    --output="${CRYPTO_DIR}"

  echo "[generate] Generating Org1 peer crypto material..."
  cryptogen generate \
    --config=/network/organizations/cryptogen/crypto-config-org1.yaml \
    --output="${CRYPTO_DIR}"

  echo "[generate] Crypto material generated."
fi

# ── 2. Channel genesis block ──────────────────────────────────────────────
mkdir -p /channel-artifacts

echo "[generate] Generating channel genesis block (mychannel)..."
FABRIC_CFG_PATH=/network configtxgen \
  -profile ChannelUsingRaft \
  -outputBlock /channel-artifacts/mychannel.block \
  -channelID mychannel

echo "[generate] Genesis block written to /channel-artifacts/mychannel.block"

# ── 3. Export admin credentials for Python client ────────────────────────
echo "[generate] Copying admin credentials to /creds ..."

ORG1_DIR=${CRYPTO_DIR}/peerOrganizations/org1.example.com

# TLS CA cert — used by Python gRPC client to verify the peer's TLS cert
cp "${ORG1_DIR}/peers/peer0.org1.example.com/tls/ca.crt" /creds/tls-ca.crt

# Admin signing certificate (named Admin@org1.example.com-cert.pem by cryptogen)
SIGNCERT=$(ls "${ORG1_DIR}/users/Admin@org1.example.com/msp/signcerts/"* | head -1)
cp "${SIGNCERT}" /creds/admin-cert.pem

# Admin private key (named 'priv_sk' in Fabric 2.x cryptogen output)
KEYFILE=$(ls "${ORG1_DIR}/users/Admin@org1.example.com/msp/keystore/"* | head -1)
cp "${KEYFILE}" /creds/admin-key.pem
# Ensure the key is readable by non-root container users (e.g. the icn-app container)
chmod 644 /creds/admin-key.pem

echo "[generate] Credentials written:"
echo "           /creds/tls-ca.crt"
echo "           /creds/admin-cert.pem"
echo "           /creds/admin-key.pem"
echo "================================================================"
echo " generate.sh complete."
echo "================================================================"
