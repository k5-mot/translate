"""追加DependencyなしでRun用UUIDv7を生成する。"""

from __future__ import annotations

import secrets
import time
from uuid import UUID

_TIMESTAMP_BITS = 48
_RANDOM_BITS = 74
_RAND_B_BITS = 62
_MAX_TIMESTAMP_MS = (1 << _TIMESTAMP_BITS) - 1


def uuid7() -> UUID:
    """RFC 9562のUUIDv7を現在時刻と暗号学的乱数から生成する。"""

    timestamp_ms = time.time_ns() // 1_000_000
    if not 0 <= timestamp_ms <= _MAX_TIMESTAMP_MS:
        msg = "current Unix timestamp does not fit UUIDv7"
        raise OverflowError(msg)
    random_bits = secrets.randbits(_RANDOM_BITS)
    rand_a = random_bits >> _RAND_B_BITS
    rand_b = random_bits & ((1 << _RAND_B_BITS) - 1)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return UUID(int=value)
