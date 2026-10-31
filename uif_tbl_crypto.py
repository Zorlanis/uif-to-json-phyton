"""Read-only KO table crypto, with constants adapted from ko-tbl-editor.

Copyright (c) 2026 ThiagQPie. MIT license: see THIRD_PARTY_NOTICES.md.
Integer Feistel implementation and strict framing integration by Zorlanis.
"""

from functools import lru_cache
import struct


def _permute(value: int, positions: tuple, width: int) -> int:
    result = 0
    for position in positions:
        result = (result << 1) | ((value >> (width - position)) & 1)
    return result


def _schedule(state: int) -> tuple:
    left, right = state >> 28, state & 0xfffffff
    keys = []
    for shift in ROTATIONS:
        left = ((left << shift) | (left >> (28 - shift))) & 0xfffffff
        right = ((right << shift) | (right >> (28 - shift))) & 0xfffffff
        key = _permute((left << 28) | right, KEY_PERMUTATION, 56)
        keys.append(tuple((key >> (42 - 6 * i)) & 63 for i in range(8)))
    return tuple(keys)


@lru_cache(maxsize=1)
def _substitutions() -> tuple:
    tables = []
    for group in range(8):
        table = []
        for six_bits in range(64):
            row = ((six_bits >> 4) & 2) | (six_bits & 1)
            column = (six_bits >> 1) & 15
            nibble = SBOXES[group][row * 16 + column]
            table.append(_permute(nibble << (28 - group * 4), PERMUTATION, 32))
        tables.append(tuple(table))
    return tuple(tables)


def _block(value: int, keys: tuple) -> int:
    left, right = value >> 32, value & 0xffffffff
    a, b, c, d, e, f, g, h = _substitutions()
    for key in keys:
        mixed = (a[(((right & 1) << 5) | (right >> 27)) ^ key[0]]
                 | b[((right >> 23) & 63) ^ key[1]]
                 | c[((right >> 19) & 63) ^ key[2]]
                 | d[((right >> 15) & 63) ^ key[3]]
                 | e[((right >> 11) & 63) ^ key[4]]
                 | f[((right >> 7) & 63) ^ key[5]]
                 | g[((right >> 3) & 63) ^ key[6]]
                 | h[(((right & 31) << 1) | (right >> 31)) ^ key[7]])
        left, right = right, left ^ mixed
    return (right << 32) | left


@lru_cache(maxsize=1)
def _keys() -> tuple:
    state = 0
    password = b"8sgpV&22dsdLg3k"
    for index, strength in enumerate(STRENGTH):
        chunk = password[index * 8:index * 8 + 8].ljust(8, b"\0")
        state = _block(state ^ int.from_bytes(chunk, "big"), _schedule(strength))
    return _schedule(state >> 8)


def stream_decode(data: bytes, profile: str = "modern") -> bytes:
    key, multiplier, increment = ((0x418, 0x8041, 0x1804) if profile == "modern"
                                  else (0x816, 0x6081, 0x1608))
    result = bytearray(len(data))
    for index, cipher in enumerate(data):
        result[index] = cipher ^ (key >> 8)
        key = ((cipher + key) * multiplier + increment) & 65535
    return bytes(result)


def decode_framed(raw: bytes) -> tuple[bytes, dict]:
    if len(raw) < 28 or not raw.startswith(MAGIC):
        raise ValueError("invalid framed TBL magic or header")
    size = struct.unpack_from(">I", raw, 16)[0]
    payload = raw[20:]
    if len(payload) % 8 or not 0 < size <= len(payload) or len(payload) - size > 7:
        raise ValueError("invalid framed TBL size or block alignment")
    keys = tuple(reversed(_keys()))
    decrypted = bytearray(len(payload))
    for offset in range(0, len(payload), 8):
        block = int.from_bytes(payload[offset:offset + 8], "big")
        decrypted[offset:offset + 8] = _block(block, keys).to_bytes(8, "big")
    return stream_decode(decrypted[:size]), {
        "scheme": "modified_des_then_modern_lcg", "header_hex": raw[:20].hex(),
        "padding_hex_before_lcg": decrypted[size:].hex(), "plaintext_size": size}

MAGIC = bytes.fromhex("4c26437f80f1579879fcaf2686d6208e")
PERMUTATION = (16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10, 2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25)
KEY_PERMUTATION = (14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10, 23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2, 41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48, 44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32)
ROTATIONS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
SBOXES = ((14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7, 0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8, 4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0, 15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13), (15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10, 3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5, 0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15, 13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9), (10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8, 13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1, 13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7, 1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12), (7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15, 13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9, 10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4, 3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14), (2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9, 14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6, 4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14, 11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3), (12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11, 10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8, 9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6, 4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13), (4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1, 13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6, 1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2, 6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12), (13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7, 1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2, 7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8, 2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11))
STRENGTH = (45127590077645718, 48447362123219712, 40430303141071100, 29363101273815196)
