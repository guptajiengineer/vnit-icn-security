package main

// icn_ledger.go — Hyperledger Fabric chaincode for the ICN authentication layer.
//
// Exposes exactly the six methods of the Python Ledger ABC:
//   RegisterProducer     → PutState("producer:<id>", hex_public_key)
//   RegisterContentRoot  → PutState("root:<id>",     merkle_root_hex)
//   GetContentRoot       → GetState("root:<id>")     → hex string or ""
//   GetProducerKey       → GetState("producer:<id>") → hex string or ""
//   StoreMerkleTree      → PutState("tree:<id>",     tree_levels_json)
//   GetMerkleTree        → GetState("tree:<id>")     → JSON string or ""
//
// Not-found is signalled by returning "" with nil error; callers (FabricLedger)
// convert the empty response into a Python KeyError.  Actual ledger-read errors
// return a non-nil error and are surfaced as RuntimeError on the Python side.

import (
	"encoding/json"
	"fmt"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

// ICNLedgerContract implements the six on-chain operations required by the
// Python Ledger interface.
type ICNLedgerContract struct {
	contractapi.Contract
}

// RegisterProducer stores the Ed25519 public key (hex-encoded) for a producer.
// Idempotent: a second call with the same producer_id overwrites the stored key.
func (c *ICNLedgerContract) RegisterProducer(
	ctx contractapi.TransactionContextInterface,
	producerID string,
	publicKeyHex string,
) error {
	return ctx.GetStub().PutState("producer:"+producerID, []byte(publicKeyHex))
}

// RegisterContentRoot stores the hex-encoded SHA-256 Merkle root for a content object.
// Idempotent: overwrites any previously stored root.
func (c *ICNLedgerContract) RegisterContentRoot(
	ctx contractapi.TransactionContextInterface,
	contentID string,
	merkleRoot string,
) error {
	return ctx.GetStub().PutState("root:"+contentID, []byte(merkleRoot))
}

// GetContentRoot returns the Merkle root for contentID, or "" if not registered.
func (c *ICNLedgerContract) GetContentRoot(
	ctx contractapi.TransactionContextInterface,
	contentID string,
) (string, error) {
	val, err := ctx.GetStub().GetState("root:" + contentID)
	if err != nil {
		return "", fmt.Errorf("GetContentRoot: ledger read error: %w", err)
	}
	return string(val), nil // nil val → "" (caller interprets as KeyError)
}

// GetProducerKey returns the hex-encoded Ed25519 public key for producerID,
// or "" if the producer has not been registered.
func (c *ICNLedgerContract) GetProducerKey(
	ctx contractapi.TransactionContextInterface,
	producerID string,
) (string, error) {
	val, err := ctx.GetStub().GetState("producer:" + producerID)
	if err != nil {
		return "", fmt.Errorf("GetProducerKey: ledger read error: %w", err)
	}
	return string(val), nil // nil val → ""
}

// StoreMerkleTree persists the full Merkle tree structure for a content object
// as a JSON-encoded [][]string (tree_levels from crypto_auth.build_merkle_tree).
func (c *ICNLedgerContract) StoreMerkleTree(
	ctx contractapi.TransactionContextInterface,
	contentID string,
	treeLevelsJSON string,
) error {
	// Validate the JSON before storing.
	var check [][]string
	if err := json.Unmarshal([]byte(treeLevelsJSON), &check); err != nil {
		return fmt.Errorf("StoreMerkleTree: invalid tree_levels JSON: %w", err)
	}
	return ctx.GetStub().PutState("tree:"+contentID, []byte(treeLevelsJSON))
}

// GetMerkleTree returns the JSON-encoded tree_levels for contentID, or "".
func (c *ICNLedgerContract) GetMerkleTree(
	ctx contractapi.TransactionContextInterface,
	contentID string,
) (string, error) {
	val, err := ctx.GetStub().GetState("tree:" + contentID)
	if err != nil {
		return "", fmt.Errorf("GetMerkleTree: ledger read error: %w", err)
	}
	return string(val), nil // nil val → ""
}

func main() {
	cc, err := contractapi.NewChaincode(&ICNLedgerContract{})
	if err != nil {
		panic(fmt.Sprintf("Error creating ICNLedger chaincode: %v", err))
	}
	if err := cc.Start(); err != nil {
		panic(fmt.Sprintf("Error starting ICNLedger chaincode: %v", err))
	}
}
