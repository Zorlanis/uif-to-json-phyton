"""Column coverage and diagnostics; profiles do not assign gameplay semantics."""

from collections import Counter, defaultdict
import json
import math
import re


def _preview(value):
    if isinstance(value, str) and len(value) > 160:
        return {"preview": value[:160], "characters": len(value), "full_value_in_table": True}
    return value


def audit_table(table):
    columns = []
    encoding_samples = []
    encoding_ambiguous = 0
    selected_counts = Counter()
    keys = defaultdict(list)
    for row in table["rows"]:
        if row["key"] is not None:
            keys[row["key"]].append(row["index"])
    for column in table["columns"]:
        index = column["index"]
        distinct, numeric, samples = {}, [], []
        empty, zero, negative, opaque = 0, 0, 0, 0
        for row in table["rows"]:
            value = row["values"][index]
            token = json.dumps(value, ensure_ascii=False, sort_keys=True)
            distinct.setdefault(token, value)
            if value is None or value == "":
                empty += 1
            if isinstance(value, dict):
                opaque += 1
            elif isinstance(value, (int, float)) and math.isfinite(value):
                numeric.append(value)
                zero += value == 0
                negative += value < 0
            if len(samples) < 3 and value not in (None, ""):
                samples.append({"row_index": row["index"], "row_key": row["key"], "value": _preview(value)})
            metadata = row["binary"].get("strings", {}).get(str(index))
            if metadata:
                selected_counts[metadata["encoding"]] += 1
                raw = bytes.fromhex(metadata["hex"])
                alternatives = []
                selected_codec = metadata["encoding"].split(":", 1)[0]
                for codec in ("cp949", "cp950", "cp1254", "utf-8"):
                    if codec == selected_codec:
                        continue
                    try:
                        decoded = raw.decode(codec)
                    except UnicodeDecodeError:
                        continue
                    if decoded != value:
                        alternatives.append({"encoding": codec, "value": _preview(decoded)})
                if alternatives:
                    encoding_ambiguous += 1
                    if len(encoding_samples) < 12:
                        encoding_samples.append({"row_index": row["index"], "row_key": row["key"],
                                                 "column_index": index, "byte_offset": metadata["offset"],
                                                 "selected_encoding": metadata["encoding"],
                                                 "selected_value": _preview(value), "alternatives": alternatives})
        profile = {**column, "semantics": "unknown", "units": "unknown", "rows": len(table["rows"]),
                   "distinct_values": len(distinct), "empty_cells": empty, "zero_values": zero,
                   "negative_values": negative, "opaque_numeric_cells": opaque, "samples": samples}
        if numeric:
            profile.update(minimum=min(numeric), maximum=max(numeric))
        if len(distinct) <= 16:
            profile["observed_small_domain"] = [_preview(v) for v in distinct.values()]
            profile["domain_is_verified_enum"] = False
        columns.append(profile)
    return {"table": table["source"]["relative_path"], "table_json": None,
            "columns": columns, "row_key": {"unique": len(keys) == len(table["rows"]),
                "null_keys": sum(row["key"] is None for row in table["rows"]),
                "duplicates": [{"key": key, "row_indices": rows} for key, rows in keys.items() if len(rows) > 1]},
            "opaque_content_header_hex": table["content_header_hex"],
            "replacement_strings": table["replacement_string_count"],
            "non_ascii_encoding_counts": dict(selected_counts), "ambiguous_encoding_cells": encoding_ambiguous,
            "encoding_review_samples": encoding_samples,
            "encoding_note": "Automatic codec selection is heuristic; alternatives are not proof of language."}


def unclassified_cell(cell, catalog, table, table_json, known_reference):
    text = cell["text"].rstrip("\0").strip()
    source = {"table": table, "table_json": table_json,
              **{key: value for key, value in cell.items() if key != "text"}}
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        return {**source, "kind": "external_uri", "value": text, "fetched": False}
    if known_reference:
        return None
    if "\\" in text or "/" in text or re.search(r"\.[a-z][a-z0-9_]{1,15}$", text, re.IGNORECASE):
        if len(text) <= 1024:
            controls = [f"U+{ord(c):04X}" for c in text if ord(c) < 32]
            return {**source, "kind": "unclassified_path_shaped_string", "value": text,
                    "control_characters": controls,
                    "is_confirmed_dependency": False, "interpretation": "consumer_review_required"}
    return None
