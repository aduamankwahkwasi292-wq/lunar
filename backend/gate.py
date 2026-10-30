"""
The backend's own licence check (hardening, 2026-10-29).

The desktop shell already refuses to open MrSOLIS without a licence (desktop/licence.js). But the backend is a
program of its own (resources/backend/lunar-backend.exe): started by hand, it would serve the whole of MrSOLIS to
a browser with no licence at all. So the installed (frozen) backend checks the same licence.json itself before it
starts: signed by Behemoth Group's key (Ed25519) and made for THIS computer (the same one-way hash of Windows'
MachineGuid that licence.js sends). Dev runs from the repo skip it, unless LUNAR_BACKEND_LICENCE=1 (tests).

Pure Python (RFC 8032's verification), so nothing new is bundled; one check takes a few milliseconds.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys

# Behemoth Group's public key: the same as licence.js's PUBLIC_KEY (SPKI DER; the last 32 bytes are the key).
_SPKI = "MCowBQYDK2VwAyEABR/9J2efNOtycKskf0HGCYTx1j3WbRauXV8Q7IBh8Bo="
PUBLIC_KEY = base64.b64decode(_SPKI)[-32:]

# ── Ed25519 verification (RFC 8032, section 6) ─────────────────────────────────────────────────────────────────
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    k = (y1 - x1) * (y2 - x2) % _P
    m = (y1 + x1) * (y2 + x2) % _P
    c = 2 * t1 * t2 * _D % _P
    d = 2 * z1 * z2 % _P
    e, f, g, h = m - k, d - c, d + c, m + k
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


def _point(b: bytes):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_x(_GY, 0), _GY, 1, _x(_GY, 0) * _GY % _P)


def ed25519_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = _point(public), _point(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))


# ── this computer, and its licence ─────────────────────────────────────────────────────────────────────────────
def _machine_guid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0] or "")
    except OSError:
        return ""


def device_id() -> str:
    """licence.js's deviceId(): sha256("mrsolis-device:" + MachineGuid), first 40 hex digits. '' if unknown."""
    guid = _machine_guid()
    return hashlib.sha256(f"mrsolis-device:{guid}".encode()).hexdigest()[:40] if guid else ""


def _unb64url(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def check(licence: str, device: str, public: bytes = PUBLIC_KEY):
    """The licence's payload if it is genuine and for `device` ('' = this computer can't be told: signature only),
    else None."""
    try:
        body, sig = str(licence or "").split(".")
        if not ed25519_verify(public, body.encode("ascii"), _unb64url(sig)):
            return None
        payload = json.loads(_unb64url(body).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != 1 or (device and payload.get("device") != device):
        return None
    return payload


def required() -> bool:
    return bool(getattr(sys, "frozen", False)) or os.environ.get("LUNAR_BACKEND_LICENCE") == "1"


def licensed(data_dir: str) -> bool:
    try:
        with open(os.path.join(data_dir, "licence.json"), encoding="utf-8") as f:
            state = json.load(f) or {}
    except (OSError, ValueError):
        return False
    return check(state.get("licence"), device_id()) is not None
