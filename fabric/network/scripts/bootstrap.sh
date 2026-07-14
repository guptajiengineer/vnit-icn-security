#!/usr/bin/env bash
# bootstrap.sh — Run inside hyperledger/fabric-tools:2.5
#
# Mounts (set in docker-compose.yml):
#   /network           ← ./fabric/network     (organizations/...)
#   /channel-artifacts ← ./fabric/channel-artifacts  (mychannel.block)
#   /chaincode         ← ./fabric/icn_ledger  (Go chaincode source)
#
# Prerequisite: orderer and peer0.org1 are both healthy before this runs.
# Steps:
#   1. osnadmin  → join orderer to mychannel
#   2. peer      → join peer0.org1 to mychannel
#   3. lifecycle → package / install / approve / commit icnledger chaincode

set -euo pipefail

# ── Path constants ────────────────────────────────────────────────────────
ORDERER_CA=/network/organizations/ordererOrganizations/example.com/tlsca/tlsca.example.com-cert.pem
ORDERER_ADMIN_CERT=/network/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/tls/server.crt
ORDERER_ADMIN_KEY=/network/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/tls/server.key
ORG1_TLSCA=/network/organizations/peerOrganizations/org1.example.com/tlsca/tlsca.org1.example.com-cert.pem
ADMIN_MSP=/network/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp

# ── Peer CLI environment (used by all "peer" commands below) ──────────────
# Commands that talk to the peer  → TLS set here via env vars.
# Commands that talk to the orderer → explicit -o / --tls / --cafile flags.
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID=Org1MSP
export CORE_PEER_TLS_ROOTCERT_FILE=${ORG1_TLSCA}
export CORE_PEER_MSPCONFIGPATH=${ADMIN_MSP}
export CORE_PEER_ADDRESS=peer0.org1.example.com:7051
export FABRIC_CFG_PATH=/etc/hyperledger/fabric   # fabric-tools default

echo "================================================================"
echo " ICN Fabric Network — bootstrap.sh"
echo "================================================================"

# ── Helper: retry a command up to N times ─────────────────────────────────
retry() {
  local n=$1; shift
  local delay=$2; shift
  local rc=1
  for i in $(seq 1 "$n"); do
    if "$@"; then rc=0; break; fi
    echo "[bootstrap] Attempt ${i}/${n} failed — waiting ${delay}s..."
    sleep "$delay"
  done
  return $rc
}

# ── 1. Join orderer to channel ─────────────────────────────────────────────
# osnadmin uses mutual TLS on the orderer admin port (7053).
# We present the orderer's own TLS cert as the client cert (standard pattern).
echo "[bootstrap] Joining orderer to channel mychannel ..."
retry 10 3 osnadmin channel join \
  --channelID mychannel \
  --config-block /channel-artifacts/mychannel.block \
  -o orderer.example.com:7053 \
  --ca-file     "${ORDERER_CA}" \
  --client-cert "${ORDERER_ADMIN_CERT}" \
  --client-key  "${ORDERER_ADMIN_KEY}"
echo "[bootstrap] Orderer joined mychannel."

# ── 2. Join peer to channel ────────────────────────────────────────────────
# 'peer channel join' talks to the peer only.
# TLS is configured via CORE_PEER_TLS_* env vars above — no extra flags needed.
echo "[bootstrap] Joining peer0.org1 to channel mychannel ..."
retry 10 3 peer channel join -b /channel-artifacts/mychannel.block
echo "[bootstrap] peer0.org1 joined mychannel."

# Give the peer a moment to process the join before starting lifecycle ops.
sleep 5

# ── 3. Package the Go chaincode ───────────────────────────────────────────
# This is a local operation — no network connection, no TLS needed.
echo "[bootstrap] Packaging icnledger chaincode ..."
peer lifecycle chaincode package /tmp/icnledger.tar.gz \
  --path /chaincode \
  --lang golang \
  --label icnledger
echo "[bootstrap] Package created: /tmp/icnledger.tar.gz"

# ── 4. Install on peer ────────────────────────────────────────────────────
# Talks to the peer (TLS via env vars).
echo "[bootstrap] Installing chaincode on peer0.org1 ..."
peer lifecycle chaincode install /tmp/icnledger.tar.gz
echo "[bootstrap] Chaincode installed."

# ── 5. Capture package ID ─────────────────────────────────────────────────
# Local computation only — no network.
PACKAGE_ID=$(peer lifecycle chaincode calculatepackageid /tmp/icnledger.tar.gz)
echo "[bootstrap] Package ID: ${PACKAGE_ID}"

# ── 6. Approve for Org1 ───────────────────────────────────────────────────
# Talks to the peer (endorsement via env vars) AND the orderer (ordering).
# Only orderer needs explicit TLS flags; peer TLS comes from env vars.
echo "[bootstrap] Approving chaincode definition for Org1MSP ..."
peer lifecycle chaincode approveformyorg \
  --channelID  mychannel \
  --name       icnledger \
  --version    1.0 \
  --package-id "${PACKAGE_ID}" \
  --sequence   1 \
  -o orderer.example.com:7050 \
  --ordererTLSHostnameOverride orderer.example.com \
  --tls \
  --cafile "${ORDERER_CA}"
echo "[bootstrap] Org1MSP approved."

# ── 7. Check commit readiness ─────────────────────────────────────────────
# Queries the peer only (TLS via env vars). No orderer needed.
echo "[bootstrap] Checking commit readiness ..."
peer lifecycle chaincode checkcommitreadiness \
  --channelID mychannel \
  --name      icnledger \
  --version   1.0 \
  --sequence  1 \
  --output json
echo ""

# ── 8. Commit ─────────────────────────────────────────────────────────────
# Talks to peer (endorsement via env vars) AND orderer (ordering).
echo "[bootstrap] Committing chaincode definition ..."
peer lifecycle chaincode commit \
  --channelID  mychannel \
  --name       icnledger \
  --version    1.0 \
  --sequence   1 \
  -o orderer.example.com:7050 \
  --ordererTLSHostnameOverride orderer.example.com \
  --tls \
  --cafile "${ORDERER_CA}" \
  --peerAddresses peer0.org1.example.com:7051 \
  --tlsRootCertFiles "${ORG1_TLSCA}"
echo "[bootstrap] Chaincode committed."

# ── 9. Verify ─────────────────────────────────────────────────────────────
# Queries the peer only (TLS via env vars).
echo "[bootstrap] Verifying committed chaincode ..."
peer lifecycle chaincode querycommitted \
  --channelID mychannel \
  --name      icnledger

echo "================================================================"
echo " bootstrap.sh complete."
echo " Channel 'mychannel' created and icnledger chaincode deployed."
echo " Fabric Gateway is available at localhost:7051"
echo "================================================================"
