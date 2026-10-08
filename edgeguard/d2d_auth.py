"""Python reference of firmware/common/d2d_auth.h (frame layout of firmware/common/d2d.h).

Used by tests to check the C++ HMAC / layout byte for byte, and by tools that inject or audit
D2D frames on a test bench.
"""
from __future__ import annotations

import hashlib
import hmac
import struct

FMT = "<BB12sHBB4fBBBBf12sI"          # everything before `tag`
TAG_LEN = 8
FRESH_WINDOW = 50


def pack(fr: dict) -> bytes:
    return struct.pack(FMT, fr.get("version", 1), fr.get("type", 1), fr.get("id", "").encode()[:11].ljust(12, b"\0"),
                       fr.get("short", 0), fr.get("kind", 0), fr.get("mecOk", 1),
                       fr.get("x", 0.0), fr.get("y", 0.0), fr.get("vx", 0.0), fr.get("vy", 0.0),
                       fr.get("clear", 0), fr.get("vibrate", 0), fr.get("beacon", 0), fr.get("level", 0),
                       fr.get("limit", -1.0), fr.get("src", "").encode()[:11].ljust(12, b"\0"), fr.get("seq", 0))


def tag(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, body, hashlib.sha256).digest()[:TAG_LEN]


def sign(key: bytes, fr: dict) -> bytes:
    body = pack(fr)
    return body + tag(key, body)


def verify(key: bytes, frame: bytes) -> bool:
    body, t = frame[:-TAG_LEN], frame[-TAG_LEN:]
    return hmac.compare_digest(tag(key, body), t)
