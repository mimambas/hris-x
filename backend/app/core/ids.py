"""UUIDv7 generator (time-ordered UUIDs).

PRD 18.4 aturan 7: ID memakai UUIDv7 agar terurut waktu.
Python <3.14 tidak punya uuid.uuid7(), jadi diimplementasikan manual
sesuai RFC 9562: 48-bit unix_ts_ms | ver(0111) | 12-bit rand_a |
var(10) | 62-bit rand_b.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF

    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, "big")
    b[6] = 0x70 | (rand_a >> 8)          # version 7 in high nibble
    b[7] = rand_a & 0xFF
    b[8] = 0x80 | ((rand_b >> 56) & 0x3F)  # variant 10xxxxxx
    b[9:16] = (rand_b & 0x00FFFFFFFFFFFFFF).to_bytes(7, "big")
    return uuid.UUID(bytes=bytes(b))
