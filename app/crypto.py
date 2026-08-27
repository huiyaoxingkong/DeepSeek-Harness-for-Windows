"""DPAPI helpers for encrypting the API key at rest (Windows user scope).

``config.json`` stores the key as ``dpapi:<base64>``; decryption only works for
the same Windows user on the same machine — which matches the app's portable
per-instance model (data never leaves the machine).
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes

_ENTROPY = b"dsh-desktop:api-key-v1"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _read(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def protect(plain: str) -> str:
    if not plain:
        return ""
    inp = _blob(plain.encode("utf-8"))
    ent = _blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    try:
        return "dpapi:" + base64.b64encode(_read(out)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(value: str) -> str:
    if not value:
        return ""
    if not value.startswith("dpapi:"):
        return value  # legacy plaintext value
    raw = base64.b64decode(value[len("dpapi:"):])
    inp = _blob(raw)
    ent = _blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise OSError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
    try:
        return _read(out).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
