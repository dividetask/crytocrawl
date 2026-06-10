"""Self-contained Bitcoin key/address primitives (pure Python, no dependencies).

Implements just enough to turn a private key (or brain-wallet passphrase hash)
into the standard address encodings:

    P2PKH  (legacy "1...", compressed and uncompressed public keys)
    P2WPKH (native segwit "bc1q...")
    P2SH-P2WPKH (wrapped segwit "3...")
    P2TR   (taproot "bc1p...", BIP86 single-key)

Correctness is pinned by known test vectors in tests/ (privkey=1 and the famous
"correct horse battery staple" brainwallet address). secp256k1 uses plain affine
arithmetic — fast enough for recovery-scale candidate counts.
"""

from __future__ import annotations

import hashlib
import struct

# --- secp256k1 ---------------------------------------------------------------

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_G = (_GX, _GY)


def _inv(x: int, m: int = _P) -> int:
    return pow(x % m, m - 2, m)


def _point_add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    (x1, y1), (x2, y2) = p, q
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p == q:
        s = (3 * x1 * x1) * _inv(2 * y1) % _P
    else:
        s = (y2 - y1) * _inv(x2 - x1) % _P
    x3 = (s * s - x1 - x2) % _P
    y3 = (s * (x1 - x3) - y1) % _P
    return (x3, y3)


def _jac_double(P):
    """Double a point in Jacobian coordinates (X, Y, Z); a=0 for secp256k1."""
    X1, Y1, Z1 = P
    if Y1 == 0:
        return (0, 0, 0)  # point at infinity
    YY = Y1 * Y1 % _P
    S = 4 * X1 * YY % _P
    M = 3 * X1 * X1 % _P
    X3 = (M * M - 2 * S) % _P
    Y3 = (M * (S - X3) - 8 * YY * YY) % _P
    Z3 = 2 * Y1 * Z1 % _P
    return (X3, Y3, Z3)


def _jac_add_affine(P, q):
    """Add affine point q=(x,y) to Jacobian point P (mixed addition, no inverse)."""
    if P[2] == 0:
        return (q[0], q[1], 1)
    X1, Y1, Z1 = P
    x2, y2 = q
    Z1Z1 = Z1 * Z1 % _P
    U2 = x2 * Z1Z1 % _P
    S2 = y2 * Z1 * Z1Z1 % _P
    H = (U2 - X1) % _P
    r = (S2 - Y1) % _P
    if H == 0:
        return _jac_double(P) if r == 0 else (0, 0, 0)
    HH = H * H % _P
    HHH = H * HH % _P
    V = X1 * HH % _P
    X3 = (r * r - HHH - 2 * V) % _P
    Y3 = (r * (V - X3) - Y1 * HHH) % _P
    Z3 = Z1 * H % _P
    return (X3, Y3, Z3)


# Precomputed affine multiples 2^i * G, so a fixed-base multiply k*G is just a
# sequence of mixed additions (one modular inverse at the very end) instead of
# ~384 inversions. Built once at import via the affine doubling above.
_G_TABLE = []
_acc = _G
for _i in range(256):
    _G_TABLE.append(_acc)
    _acc = _point_add(_acc, _acc)


def _scalar_mul_G(k: int):
    """Fast fixed-base multiply k*G using the precomputed table."""
    k %= _N
    R = (0, 0, 0)  # Jacobian infinity
    i = 0
    while k:
        if k & 1:
            R = _jac_add_affine(R, _G_TABLE[i])
        k >>= 1
        i += 1
    if R[2] == 0:
        return None
    zinv = _inv(R[2])
    zinv2 = zinv * zinv % _P
    return (R[0] * zinv2 % _P, R[1] * zinv2 % _P * zinv % _P)


def _scalar_mul(k: int, point=_G):
    if point is _G or point == _G:
        return _scalar_mul_G(k)
    # General (rare) path for an arbitrary base point: affine double-and-add.
    k %= _N
    result = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _lift_x(x: int):
    """Return the point with the given x and even y (BIP340)."""
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if (y * y) % _P != y_sq:
        raise ValueError("x is not on the curve")
    if y % 2 != 0:
        y = _P - y
    return (x, y)


def privkey_to_point(priv_int: int):
    if not (1 <= priv_int < _N):
        raise ValueError("private key out of range")
    return _scalar_mul(priv_int)


def public_key_bytes(priv_int: int, compressed: bool) -> bytes:
    x, y = privkey_to_point(priv_int)
    if compressed:
        return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


# --- hashes ------------------------------------------------------------------

def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _ripemd160_py(msg: bytes) -> bytes:
    rl = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,7,4,13,1,10,6,15,3,12,0,9,5,2,14,11,8,
          3,10,14,4,9,15,8,1,2,7,0,6,13,11,5,12,1,9,11,10,0,8,12,4,13,3,7,15,14,5,6,2,
          4,0,5,9,7,12,2,10,14,1,3,8,11,6,15,13]
    rr = [5,14,7,0,9,2,11,4,13,6,15,8,1,10,3,12,6,11,3,7,0,13,5,10,14,15,8,12,4,9,1,2,
          15,5,1,3,7,14,6,9,11,8,12,2,10,0,4,13,8,6,4,1,3,11,15,0,5,12,2,13,9,7,10,14,
          12,15,10,4,1,5,8,7,6,2,13,14,0,3,9,11]
    sl = [11,14,15,12,5,8,7,9,11,13,14,15,6,7,9,8,7,6,8,13,11,9,7,15,7,12,15,9,11,7,13,12,
          11,13,6,7,14,9,13,15,14,8,13,6,5,12,7,5,11,12,14,15,14,15,9,8,9,14,5,6,8,6,5,12,
          9,15,5,11,6,8,13,12,5,12,13,14,11,8,5,6]
    sr = [8,9,9,11,13,15,15,5,7,7,8,11,14,14,12,6,9,13,15,7,12,8,9,11,7,7,12,7,6,15,13,11,
          9,7,15,11,8,6,6,14,12,13,5,14,13,13,7,5,15,5,8,11,14,14,6,14,6,9,12,9,12,5,15,8,
          8,5,12,9,12,5,14,6,8,13,6,5,15,13,11,11]
    kl = [0x00000000,0x5a827999,0x6ed9eba1,0x8f1bbcdc,0xa953fd4e]
    kr = [0x50a28be6,0x5c4dd124,0x6d703ef3,0x7a6d76e9,0x00000000]

    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & 0xffffffff

    def f(j, x, y, z):
        if j < 16: return x ^ y ^ z
        if j < 32: return (x & y) | (~x & z) & 0xffffffff
        if j < 48: return (x | (~y & 0xffffffff)) ^ z
        if j < 64: return (x & z) | (y & (~z & 0xffffffff))
        return x ^ (y | (~z & 0xffffffff))

    h0,h1,h2,h3,h4 = 0x67452301,0xefcdab89,0x98badcfe,0x10325476,0xc3d2e1f0
    ml = len(msg)
    msg = msg + b"\x80"
    while len(msg) % 64 != 56:
        msg += b"\x00"
    msg += struct.pack("<Q", (ml * 8) & 0xffffffffffffffff)
    for off in range(0, len(msg), 64):
        X = list(struct.unpack("<16I", msg[off:off + 64]))
        al,bl,cl,dl,el = h0,h1,h2,h3,h4
        ar,br,cr,dr,er = h0,h1,h2,h3,h4
        for j in range(80):
            t = (rol((al + f(j,bl,cl,dl) + X[rl[j]] + kl[j//16]) & 0xffffffff, sl[j]) + el) & 0xffffffff
            al = el; el = dl; dl = rol(cl,10); cl = bl; bl = t
            t = (rol((ar + f(79-j,br,cr,dr) + X[rr[j]] + kr[j//16]) & 0xffffffff, sr[j]) + er) & 0xffffffff
            ar = er; er = dr; dr = rol(cr,10); cr = br; br = t
        t = (h1 + cl + dr) & 0xffffffff
        h1 = (h2 + dl + er) & 0xffffffff
        h2 = (h3 + el + ar) & 0xffffffff
        h3 = (h4 + al + br) & 0xffffffff
        h4 = (h0 + bl + cr) & 0xffffffff
        h0 = t
    return struct.pack("<5I", h0,h1,h2,h3,h4)


def ripemd160(b: bytes) -> bytes:
    try:
        h = hashlib.new("ripemd160")
        h.update(b)
        return h.digest()
    except (ValueError, TypeError):
        return _ripemd160_py(b)


def hash160(b: bytes) -> bytes:
    return ripemd160(sha256(b))


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    t = sha256(tag.encode())
    return sha256(t + t + msg)


# --- base58check -------------------------------------------------------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return _B58[0] * pad + out


def b58check(payload: bytes) -> str:
    return b58encode(payload + sha256(sha256(payload))[:4])


# --- bech32 / bech32m (BIP173 / BIP350) --------------------------------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    gen = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_create_checksum(hrp, data, const):
    values = _hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ const
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def segwit_encode(hrp: str, witver: int, witprog: bytes) -> str:
    const = 1 if witver == 0 else 0x2bc830a3  # bech32 vs bech32m
    data = [witver] + _convertbits(list(witprog), 8, 5)
    checksum = _bech32_create_checksum(hrp, data, const)
    return hrp + "1" + "".join(_CHARSET[d] for d in data + checksum)


# --- address builders --------------------------------------------------------

def p2pkh(pubkey: bytes) -> str:
    return b58check(b"\x00" + hash160(pubkey))


def p2wpkh(pubkey33: bytes) -> str:
    return segwit_encode("bc", 0, hash160(pubkey33))


def p2sh_p2wpkh(pubkey33: bytes) -> str:
    redeem = b"\x00\x14" + hash160(pubkey33)  # OP_0 <20-byte keyhash>
    return b58check(b"\x05" + hash160(redeem))


def p2tr(pubkey33: bytes) -> str:
    x = int.from_bytes(pubkey33[1:33], "big")
    px, py = _lift_x(x)
    t = int.from_bytes(_tagged_hash("TapTweak", px.to_bytes(32, "big")), "big") % _N
    q = _point_add((px, py), _scalar_mul(t))
    return segwit_encode("bc", 1, q[0].to_bytes(32, "big"))
