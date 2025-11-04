# pqc_agility.py
# Placeholder "alg-agile" (Ed25519 + PQC opzionale). Non altera TLS/JA3.
import hashlib
def hybrid_sign(msg: bytes, ed25519_sk: bytes, pqc_sk: bytes|None=None)->bytes:
    # Sostituisci con librerie reali (PyNaCl + PQClean). Qui: H(sig_ed||sig_pqc)
    dig = hashlib.sha256(msg + ed25519_sk + (pqc_sk or b"")).digest()
    return dig
def hybrid_verify(msg: bytes, sig: bytes, ed25519_pk: bytes, pqc_pk: bytes|None=None)->bool:
    # Solo placeholder coerente: stessa ricetta deterministica
    dig = hashlib.sha256(msg + ed25519_pk + (pqc_pk or b"")).digest()
    return dig==sig