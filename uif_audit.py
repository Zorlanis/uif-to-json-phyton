"""Byte reconstruction and explicit coverage of interpreted/opaque UIF fields."""

from collections import Counter
import struct

from uif_parser import LAYOUTS, UIFError, iter_nodes

RUNTIME_ONLY = [
    "current_visibility_and_focus", "current_button_and_animation_state",
    "progress_values_and_scroll_positions", "event_handlers_and_game_actions",
    "server_table_or_code_generated_text", "runtime_layout_changes",
    "font_metrics_glyph_positions_and_actual_line_wrapping",
]


def reconstruct(root: dict, layout_name: str) -> bytes:
    """Rebuild source bytes from parsed fields, independently of source slices.

    This validates the exported data coverage; it is not an editing/writing API.
    Strings use original bytes, including undecodable sequences.
    """
    profile = next(layout for layout in LAYOUTS if layout.name == layout_name)
    data = bytearray()

    def number(value, signed=False):
        data.extend(struct.pack("<i" if signed else "<I", value))

    def rect(value, floating=False):
        data.extend(struct.pack("<4f" if floating else "<4i",
                                *(value[key] for key in ("left", "top", "right", "bottom"))))

    def node_record(node):
        start = len(data)
        if start != node["binary"]["offset"]:
            raise UIFError("reconstruction node offset mismatch", start, node["uid"])

        def string(field):
            metadata = node["binary"]["strings"].get(field)
            raw = bytes.fromhex(metadata["hex"]) if metadata else b""
            if metadata and (metadata["offset"] != len(data) or metadata["length"] != len(raw)):
                raise UIFError("reconstruction string metadata mismatch", len(data), field)
            number(len(raw), True)
            data.extend(raw)

        string("name")
        number(node["binary"]["children_manifest"])
        for child in node["children"]:
            if child["binary"]["type_offset"] != len(data):
                raise UIFError("reconstruction child type offset mismatch", len(data), child["uid"])
            number(child["type_id"])
            node_record(child)
        string("id")
        rect(node["region"])
        rect(node["movable_region"])
        number(node["style"]["value"])
        number(node["reserved"])
        string("tooltip")
        if profile.sounds:
            string("sound_open")
            string("sound_close")
        data.extend(bytes.fromhex(node["binary"]["extension_hex"]))
        kind = node["type_id"]
        if kind == 4:
            string("texture")
            rect(node["image"]["uv"], True)
            data.extend(struct.pack("<f", node["image"]["animation_fps"]))
        elif kind == 1:
            rect(node["button"]["click_region"])
            if profile.sounds:
                string("sound_hover")
                string("sound_click")
        elif kind in {6, 14}:
            string("font_name")
            font = node["font"]
            if "font_name" in node["binary"]["strings"]:
                number(font["height_pixels"])
                if kind == 14:
                    number(font["color"]["argb"])
                    number(font["bold_raw"])
                    number(font["italic_raw"])
                else:
                    number(font["flags"])
            if kind == 6:
                number(node["text_color"]["argb"])
                string("text")
                if profile.line_spacing:
                    number(node["line_spacing"], True)
        elif kind == 9:
            number(node["area_type"], True)
        elif kind in {2, 8} and profile.sounds:
            string("sound_click")
            if kind == 8:
                string("sound_typing")
        elif kind == 18:
            number(node["flash"]["unknown_value"])
            string("flash_file")
            rect(node["flash"]["uv"], True)
        if len(data) - start != node["binary"]["length"]:
            raise UIFError("reconstruction node length mismatch", start, node["uid"])

    node_record(root)
    return bytes(data)


def coverage(root: dict, original: bytes, layout_name: str) -> dict:
    rebuilt = reconstruct(root, layout_name)
    if rebuilt != original:
        offset = next((i for i, (a, b) in enumerate(zip(rebuilt, original)) if a != b),
                      min(len(rebuilt), len(original)))
        raise UIFError("parsed fields do not reconstruct the original bytes", offset)
    groups = {}
    encodings = Counter()
    for node in iter_nodes(root):
        def record(field, value):
            key = (field, node["type_id"], str(value))
            item = groups.setdefault(key, {"field": field, "type_id": node["type_id"],
                                           "value": value, "nodes": []})
            item["nodes"].append(node["uid"])

        if node["type_id"] in {15, 16, 17}:
            record("control_semantics", node["type_id"])
        if int(node["style"]["unknown_bits"], 16):
            record("style.unknown_bits", node["style"]["unknown_bits"])
        if node.get("font", {}).get("unknown_flags"):
            record("font.unknown_flags", f'0x{node["font"]["unknown_flags"]:08X}')
        if node["binary"]["extension_hex"]:
            record("binary.extension_hex", {"header_tag": node["binary"]["header_tag"],
                                             "hex": node["binary"]["extension_hex"]})
        if "flash" in node:
            record("flash.unknown_value", node["flash"]["unknown_value"])
        if node["reserved"] and "usage_role" not in node:
            record("reserved_without_verified_role", node["reserved"])
        if "area_type" in node and node.get("area_type_name") is None:
            record("unknown_area_type", node["area_type"])
        for metadata in node["binary"]["strings"].values():
            encodings[metadata["encoding"]] += 1
    return {"byte_reconstruction": "exact_match", "verified_bytes": len(original),
            "semantic_coverage": "partial" if groups else "known_fields_only",
            "uninterpreted_fields": list(groups.values()),
            "string_encoding_counts": dict(sorted(encodings.items())),
            "runtime_only_not_serialized": RUNTIME_ONLY}
