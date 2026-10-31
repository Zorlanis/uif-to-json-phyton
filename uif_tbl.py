"""Bounded read-only TBL decoding; no guessed column names or ID joins."""

from collections import Counter
import hashlib
import math
from pathlib import Path
import struct

from uif_parser import decode_string
from uif_tbl_crypto import MAGIC, decode_framed, stream_decode

TYPES = {1: ("int8", "b"), 2: ("uint8", "B"), 3: ("int16", "h"), 4: ("uint16", "H"),
         5: ("int32", "i"), 6: ("uint32", "I"), 7: ("string", None),
         8: ("float32", "f"), 9: ("raw64", "8s"), 10: ("int64", "q")}
MAX_SIZE = 128 * 1024 * 1024


class TBLError(ValueError):
    pass


def _string(raw: bytes, encoding: str, modern: bool) -> tuple[str, str]:
    if encoding != "auto":
        return decode_string(raw, encoding)
    # Narrow client strings do not carry a language tag. Preserve non-ASCII
    # bytes and expose the selected codec rather than claim language certainty.
    for candidate in ("ascii", "utf-8"):
        try:
            return raw.decode(candidate), candidate
        except UnicodeDecodeError:
            pass
    try:
        korean = raw.decode("cp949")
        hangul = sum("\uac00" <= char <= "\ud7a3" for char in korean)
        non_ascii = sum(ord(char) > 127 for char in korean)
        if not modern or (hangul and hangul * 2 >= non_ascii):
            return korean, "cp949"
    except UnicodeDecodeError:
        pass
    for candidate in ("cp1254", "cp950", "cp949"):
        try:
            return raw.decode(candidate), candidate
        except UnicodeDecodeError:
            pass
    return raw.decode("cp1254", errors="replace"), "cp1254:replacement"


def _read(data: bytes, profile: str, encoding: str) -> dict:
    position = 5 if profile == "modern" else 0
    header = data[:position]

    def take(size):
        nonlocal position
        if size < 0 or position + size > len(data):
            raise TBLError(f"truncated TBL at 0x{position:X}, requested {size} bytes")
        start = position
        position += size
        return data[start:position]

    def uint():
        return struct.unpack("<I", take(4))[0]

    count = uint()
    if not 0 < count <= 4096:
        raise TBLError("invalid TBL column count")
    types = [uint() for _ in range(count)]
    if any(kind not in TYPES for kind in types):
        raise TBLError("unsupported TBL column type")
    row_count = uint()
    minimum = sum(4 if kind == 7 else struct.calcsize("<" + TYPES[kind][1]) for kind in types)
    if row_count > 1_000_000 or row_count * count > 8_000_000 or row_count * minimum > len(data) - position:
        raise TBLError("invalid TBL row/cell count or truncated records")
    rows, codecs = [], Counter()
    replacements = 0
    for index in range(row_count):
        start = position
        values, originals = [], {}
        for column, kind in enumerate(types):
            if kind == 7:
                offset = position
                length = uint()
                if length > 1_048_576:
                    raise TBLError(f"invalid TBL string length at 0x{offset:X}")
                raw = take(length)
                text, codec = _string(raw, encoding, profile == "modern")
                values.append(text)
                if raw:
                    codecs[codec] += 1
                if not raw.isascii() or not text.isascii() or text.encode("ascii") != raw:
                    originals[str(column)] = {"offset": offset, "encoding": codec, "hex": raw.hex()}
                if codec.endswith(":replacement"):
                    replacements += 1
            else:
                raw = take(struct.calcsize("<" + TYPES[kind][1]))
                value = struct.unpack("<" + TYPES[kind][1], raw)[0]
                if isinstance(value, bytes) or (isinstance(value, float) and not math.isfinite(value)):
                    value = {"raw_hex": raw.hex()}
                values.append(value)
        row = {"index": index, "key": values[0] if types[0] in {1, 2, 3, 4, 5, 6, 10} else None,
               "values": values, "binary": {"offset": start, "length": position - start}}
        if originals:
            row["binary"]["strings"] = originals
        rows.append(row)
    if position != len(data):
        raise TBLError(f"{len(data) - position} unconsumed TBL bytes")
    result = {"content_profile": profile, "content_header_hex": header.hex(), "column_types": types,
              "columns": [{"index": index, "name": f"column_{index:03d}", "type_id": kind,
                           "type": TYPES[kind][0]} for index, kind in enumerate(types)],
              "rows": rows, "bytes_consumed": position, "string_encoding_counts": dict(codecs),
              "replacement_string_count": replacements}
    if rebuild(result) != data:
        raise TBLError("TBL fields do not reconstruct the plaintext bytes exactly")
    return result


def cell_bytes(row: dict, column: int, kind: int) -> bytes:
    value = row["values"][column]
    if kind == 7:
        metadata = row["binary"].get("strings", {}).get(str(column))
        raw = bytes.fromhex(metadata["hex"]) if metadata else value.encode("ascii")
        return struct.pack("<I", len(raw)) + raw
    if isinstance(value, dict):
        return bytes.fromhex(value["raw_hex"])
    return struct.pack("<" + TYPES[kind][1], value)


def rebuild(table: dict) -> bytes:
    data = bytearray.fromhex(table["content_header_hex"])
    types = table["column_types"]
    data.extend(struct.pack("<I", len(types)))
    data.extend(struct.pack("<" + "I" * len(types), *types))
    data.extend(struct.pack("<I", len(table["rows"])))
    for row in table["rows"]:
        if len(data) != row["binary"]["offset"]:
            raise TBLError("TBL row offset mismatch")
        for column, kind in enumerate(types):
            data.extend(cell_bytes(row, column, kind))
        if len(data) - row["binary"]["offset"] != row["binary"]["length"]:
            raise TBLError("TBL row length mismatch")
    return bytes(data)


def string_cells(table: dict):
    for row in table["rows"]:
        offset = row["binary"]["offset"]
        for column, kind in enumerate(table["column_types"]):
            raw = cell_bytes(row, column, kind)
            if kind == 7 and row["values"][column]:
                yield {"row_index": row["index"], "row_key": row["key"], "column_index": column,
                       "byte_offset": offset, "text": row["values"][column]}
            offset += len(raw)


def load_table(path: Path, client_root: Path, encoding: str = "auto") -> dict:
    if path.stat().st_size > MAX_SIZE:
        raise TBLError("TBL exceeds the 128 MiB size limit")
    raw = path.read_bytes()
    if raw.startswith(MAGIC):
        data, crypto = decode_framed(raw)
        table = _read(data, "modern", encoding)
    else:
        table = None
        # Require a fully consumed, byte-reconstructable typed table for every
        # candidate; never extract apparent strings from undecoded ciphertext.
        for scheme, decoded in (("plain", raw), ("modern_lcg", stream_decode(raw)),
                                ("legacy_lcg", stream_decode(raw, "legacy"))):
            for profile in ("classic", "modern"):
                try:
                    table = _read(decoded, profile, encoding)
                    crypto = {"scheme": scheme, "plaintext_size": len(decoded)}
                    data = decoded
                    break
                except (TBLError, struct.error):
                    pass
            if table is not None:
                break
        if table is None:
            raise TBLError("unsupported TBL encryption/layout or corrupt data")
    relative = path.resolve().relative_to(client_root.resolve()).as_posix()
    return {"source": {"relative_path": relative, "absolute_path": str(path.resolve()),
                       "byte_size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            "format": {**crypto, "string_encoding": encoding,
                       "column_names": "unknown; indices are authoritative",
                       "type_9_semantics": "opaque 8 bytes; signedness/float meaning not assumed"},
            "integrity": {"plaintext_reconstruction": "exact_match",
                          "plaintext_sha256": hashlib.sha256(data).hexdigest(),
                          "bytes_consumed": len(data)}, **table}
