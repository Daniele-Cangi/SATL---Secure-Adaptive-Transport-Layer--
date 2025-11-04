# ================================
# qso_layer.py  (AGGIORNATO)
# Kyber PERSISTENTE (client/server) + FTE
# ================================
import os, json, base64, hashlib, hmac
from typing import Optional, Dict, Any, List
from qkernel.qrand import qstream
from qkernel.qct import ct_compare

# --- PQ KEM opzionale (liboqs) ---
try:
    import oqs
    _HAS_OQS = True
except ImportError:
    _HAS_OQS = False

try:
    from cryptography.hazmat.primitives.asymmetric import x25519
    _HAS_X25519 = True
except Exception:
    _HAS_X25519 = False

def _scrypt(salt: bytes, key_material: bytes, outlen=32)->bytes:
    return hashlib.scrypt(key_material, salt=salt, n=2**14, r=8, p=1, dklen=outlen)
def _hmac(k: bytes, d: bytes)->bytes: return hmac.new(k, d, hashlib.sha256).digest()
def _xor(a: bytes, b: bytes)->bytes:   return bytes(x^y for x,y in zip(a,b))

# -------- Client/Server separati (Kyber persistente) --------
class QSOClient:
    def __init__(self):
        self.rng = qstream(b"/qso/cli")
        self.shared_key: Optional[bytes] = None
        self._kem = None
        self._x25519_sk = None
        self._x25519_pk = None
        self._nonce = base64.urlsafe_b64encode(self.rng.bytes(16)).decode()

    def hello(self)->Dict[str,Any]:
        h={"ver":"1","alg":[],"nonce":self._nonce}
        if _HAS_OQS:
            self._kem = oqs.KeyEncapsulation("Kyber768")
            pk = self._kem.generate_keypair()
            self._pqc_sk = self._kem.export_secret_key()
            h["alg"].append("KYBER768")
            h["pqc_pk"] = base64.urlsafe_b64encode(pk).decode()
        if _HAS_X25519:
            self._x25519_sk = x25519.X25519PrivateKey.generate()
            self._x25519_pk = self._x25519_sk.public_key().public_bytes_raw()
            h["alg"].append("X25519")
            h["x25519_pk"] = base64.urlsafe_b64encode(self._x25519_pk).decode()
        return h

    def finish(self, srv: Dict[str,Any])->bool:
        material=b""
        if _HAS_OQS and "pqc_ct" in srv:
            ct = base64.urlsafe_b64decode(srv["pqc_ct"])
            # ricrea kem da sk salvata
            kem = oqs.KeyEncapsulation("Kyber768", secret_key = self._pqc_sk)
            ss  = kem.decap_secret(ct)
            material += ss
        if _HAS_X25519 and self._x25519_sk and "x25519_pk" in srv:
            srv_pk = base64.urlsafe_b64decode(srv["x25519_pk"])
            ss2 = self._x25519_sk.exchange(x25519.X25519PublicKey.from_public_bytes(srv_pk))
            material += ss2
        salt = hashlib.sha256(self._nonce.encode()).digest()
        self.shared_key = _scrypt(salt, material, 32) if material else None
        tag = base64.urlsafe_b64decode(srv.get("tag","").encode()) if "tag" in srv else None
        return bool(self.shared_key and (not tag or ct_compare(_hmac(self.shared_key,b"QSO-HANDSHAKE"), tag)))

    def fte_pack(self, plaintext: bytes, meta: Dict[str,Any]|None=None)->Dict[str,Any]:
        if self.shared_key is None: raise RuntimeError("QSOClient no key")
        iv  = self.rng.bytes(16)
        mac = _hmac(self.shared_key, iv + plaintext)
        pad = hashlib.sha256(self.shared_key + iv).digest() * ((len(plaintext)//32)+1)
        ct  = _xor(plaintext, pad[:len(plaintext)]) + mac
        out=[]; pos=0
        while pos < len(ct):
            size = 800 + int(self.rng.u01()*1200)
            out.append(base64.urlsafe_b64encode(ct[pos:pos+size]).decode())
            pos += size
        cap={"b":out,"iv":base64.urlsafe_b64encode(iv).decode()}
        if meta: cap["m"]=meta
        return cap

    def fte_unpack(self, capsule: Dict[str,Any])->bytes|None:
        if self.shared_key is None: return None
        iv = base64.urlsafe_b64decode(capsule.get("iv",""))
        raw = b"".join(base64.urlsafe_b64decode(x.encode()) for x in capsule.get("b",[]))
        if len(raw)<32: return None
        ct, mac = raw[:-32], raw[-32:]
        if not ct_compare(_hmac(self.shared_key, iv + ct[:len(ct)]), mac): return None
        pad = hashlib.sha256(self.shared_key + iv).digest() * ((len(ct)//32)+1)
        return _xor(ct, pad[:len(ct)])

class QSOServer:
    def __init__(self):
        self.rng = qstream(b"/qso/srv")
        self.shared_key: Optional[bytes] = None

    def respond(self, hello: Dict[str,Any])->Dict[str,Any]:
        resp={"ver":"1"}; material=b""
        if _HAS_OQS and "pqc_pk" in hello:
            with oqs.KeyEncapsulation("Kyber768") as kem:
                pk = base64.urlsafe_b64decode(hello["pqc_pk"])
                ct, ss = kem.encap_secret(pk)
            resp["pqc_ct"] = base64.urlsafe_b64encode(ct).decode()
            material += ss
        if _HAS_X25519 and "x25519_pk" in hello:
            from cryptography.hazmat.primitives.asymmetric import x25519
            srv_sk = x25519.X25519PrivateKey.generate()
            srv_pk = srv_sk.public_key().public_bytes_raw()
            ss2    = srv_sk.exchange(x25519.X25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(hello["x25519_pk"])))
            resp["x25519_pk"] = base64.urlsafe_b64encode(srv_pk).decode()
            material += ss2
        salt = hashlib.sha256(hello.get("nonce","").encode()).digest()
        self.shared_key = _scrypt(salt, material, 32) if material else None
        resp["tag"] = base64.urlsafe_b64encode(_hmac(self.shared_key or b"\x00"*32, b"QSO-HANDSHAKE")).decode()
        return resp