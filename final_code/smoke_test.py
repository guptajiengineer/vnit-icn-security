import sys
sys.path.insert(0, '.')

# --- chain.py smoke test ---
from chain import SimulatedLedger
l = SimulatedLedger()
l.register_producer('p1', b'x' * 32)
assert l.get_producer_key('p1') == b'x' * 32
assert l.is_producer_registered('p1')
assert not l.is_producer_registered('p2')
try:
    l.get_content_root('a1')
    assert False, 'Should raise KeyError'
except KeyError:
    pass
l.register_content_root('a1', 'deadbeef')
assert l.get_content_root('a1') == 'deadbeef'
print('PASS: chain.py')

# --- AES-GCM ---
from crypto_auth import chunk_hash, encrypt_chunk, decrypt_chunk
data = b'hello ICN world'
h = chunk_hash(data)
assert len(h) == 64
ct, k, n = encrypt_chunk(data)
pt = decrypt_chunk(ct, k, n)
assert pt == data
print('PASS: AES-GCM encrypt/decrypt')

# --- Merkle tree ---
from crypto_auth import build_merkle_tree, get_merkle_proof, verify_merkle_proof
hashes = [chunk_hash(bytes([i])) for i in range(5)]
root, levels = build_merkle_tree(hashes)
for idx in range(5):
    proof = get_merkle_proof(levels, idx)
    ok = verify_merkle_proof(hashes[idx], proof, root)
    assert ok, 'Proof failed for idx=%d' % idx
print('PASS: Merkle tree + proof (5 leaves)')

root1, levels1 = build_merkle_tree([hashes[0]])
proof1 = get_merkle_proof(levels1, 0)
assert verify_merkle_proof(hashes[0], proof1, root1)
print('PASS: Merkle tree single-leaf')

assert not verify_merkle_proof('00' * 32, proof1, root1)
print('PASS: Tampered hash correctly rejected')

# --- X25519 + manifest wrap ---
from crypto_auth import (generate_consumer_keypair, wrap_manifest_for_consumer,
                         unwrap_manifest_for_consumer, generate_producer_keypair)
priv, pub = generate_consumer_keypair()
msg = b'manifest test data'
wrapped = wrap_manifest_for_consumer(msg, pub)
recovered = unwrap_manifest_for_consumer(wrapped, priv)
assert recovered == msg
print('PASS: X25519 + HKDF + AES-GCM manifest wrap/unwrap')

_, pk_bytes = generate_producer_keypair()
assert len(pk_bytes) == 32
print('PASS: Ed25519 producer keypair')

# --- content.py publish_content ---
from content import publish_content, build_default_content_specs
from chain import SimulatedLedger
ledger = SimulatedLedger()
specs = build_default_content_specs(2)
manifest, records = publish_content(specs[0], chunk_count=3, ledger=ledger, producer_id='p1')
assert len(manifest) == 3
assert len(records) == 3
assert ledger.is_content_registered('a1')
root = ledger.get_content_root('a1')
# verify each chunk proof
for rec in records:
    proof = get_merkle_proof(ledger._merkle_trees['a1'], rec.chunk_id)
    assert verify_merkle_proof(rec.chunk_hash, proof, root), 'Chunk %d proof failed' % rec.chunk_id
print('PASS: publish_content + Merkle proof round-trip')

print()
print('ALL SMOKE TESTS PASSED')
