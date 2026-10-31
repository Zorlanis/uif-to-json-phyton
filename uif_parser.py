"""Bounded, byte-accounted parser for Knight Online's recursive UIF records.

The implementation is independent Python code based on observed file layouts
and the serialized fields documented by the N3 UI loaders. Opaque extension
bytes and original string bytes are retained; unknown semantics are not guessed.
"""

from __future__ import annotations

import codecs
from collections import Counter
from dataclasses import dataclass
import math
import struct

TYPE_NAMES = {0: "base", 1: "button", 2: "static", 3: "progress", 4: "image",
              5: "scrollbar", 6: "string", 7: "trackbar", 8: "edit", 9: "area",
              10: "tooltip", 11: "icon", 12: "icon_manager", 13: "icon_slot",
              14: "list", 15: "unknown_15", 16: "unknown_16", 17: "unknown_17", 18: "flash"}
SUPPORTED_TYPES = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, 17, 18}
COMMON_STYLES = {1: "always_top", 2: "modal", 4: "focus_unable", 8: "show_alone",
                 16: "hide_unable", 32: "hide_on_user_move", 64: "position_left", 128: "position_right"}
TYPE_STYLES = {
    1: {0x10000: "normal_button", 0x20000: "check_button"},
    4: {0x10000: "animated_image"},
    5: {0x10000: "horizontal", 0x20000: "vertical"},
    6: {0x100000: "single_line", 0x200000: "align_left", 0x400000: "align_right",
        0x800000: "align_center", 0x1000000: "align_top", 0x2000000: "align_bottom", 0x4000000: "align_vertical_center"},
    7: {0x10000: "horizontal", 0x20000: "vertical"},
    8: {0x10000000: "password", 0x20000000: "number_only"},
    3: {0x10000000: "left_to_right", 0x20000000: "right_to_left", 0x40000000: "top_to_bottom", 0x80000000: "bottom_to_top"},
}


class UIFError(ValueError):
    def __init__(self, message: str, offset: int = 0, field: str = ""):
        self.offset = offset
        self.field = field
        super().__init__(f"{message} (offset 0x{offset:X}, field {field or 'record'})")


@dataclass(frozen=True)
class Layout:
    name: str
    sounds: bool
    line_spacing: bool


LAYOUTS = [Layout("sound_and_line_spacing", True, True),
           Layout("sound_without_line_spacing", True, False),
           Layout("legacy_without_sound", False, True),
           Layout("legacy_without_sound_or_spacing", False, False)]


def decode_string(raw: bytes, encoding: str = "auto") -> tuple[str, str]:
    if not raw:
        return "", "empty"
    if encoding != "auto":
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            return raw.decode(encoding, errors="replace"), encoding + ":replacement"
    for candidate in ("ascii", "utf-8", "cp949", "cp950"):
        try:
            return raw.decode(candidate), candidate
        except UnicodeDecodeError:
            pass
    return raw.decode("cp1254", errors="replace"), "cp1254:heuristic"


def rectangle(values: tuple, *, integral: bool = True) -> dict:
    left, top, right, bottom = values
    result = {"left": left, "top": top, "right": right, "bottom": bottom,
              "x": left, "y": top, "width": right - left, "height": bottom - top}
    if not integral and not all(math.isfinite(value) for value in values):
        raise ValueError("non-finite texture coordinates")
    return result


def color_info(value: int) -> dict:
    return {"argb": value, "hex_argb": f"#{value:08X}",
            "rgba": [(value >> 16) & 255, (value >> 8) & 255, value & 255, value >> 24]}


def style_info(value: int, ui_type: int) -> dict:
    mapping = {**COMMON_STYLES, **TYPE_STYLES.get(ui_type, {})}
    known_mask = 0
    for bit in mapping:
        known_mask |= bit
    return {"value": value, "hex": f"0x{value:08X}",
            "flags": [name for bit, name in mapping.items() if value & bit],
            "unknown_bits": f"0x{value & ~known_mask:08X}"}


class Reader:
    def __init__(self, data: bytes, layout: Layout, encoding: str):
        self.data, self.layout, self.encoding = data, layout, encoding
        self.offset = 0
        self.count = 0
        self.warnings: list[dict] = []
        self.type_counts: Counter = Counter()

    def take(self, size: int, field: str) -> bytes:
        start = self.offset
        if size < 0 or start + size > len(self.data):
            raise UIFError(f"truncated data: need {size} bytes", start, field)
        self.offset += size
        return self.data[start:self.offset]

    def number(self, field: str, signed: bool = False) -> int:
        return struct.unpack("<i" if signed else "<I", self.take(4, field))[0]

    def floats(self, field: str, count: int) -> tuple:
        offset = self.offset
        values = struct.unpack("<" + "f" * count, self.take(count * 4, field))
        if not all(math.isfinite(value) for value in values):
            raise UIFError("non-finite float", offset, field)
        return values

    def rect(self, field: str) -> dict:
        return rectangle(struct.unpack("<4i", self.take(16, field)))

    def string(self, node: dict, field: str) -> str:
        offset = self.offset
        length = self.number(field + ".length", signed=True)
        if not 0 <= length <= 1_048_576:
            raise UIFError(f"invalid string length {length}", offset, field)
        raw = self.take(length, field)
        decoded, codec = decode_string(raw, self.encoding)
        # Empty strings are already represented by their decoded fields and
        # layout; omitting their redundant raw metadata keeps exports smaller.
        if raw:
            node["binary"]["strings"][field] = {"offset": offset, "length": length,
                                                 "encoding": codec, "hex": raw.hex()}
        if codec.endswith((":heuristic", ":replacement")):
            self.warnings.append({"code": "string_encoding_uncertain", "node": node["uid"],
                                  "field": field, "encoding": codec, "offset": offset})
        return decoded

    def font(self, node: dict, *, is_list: bool = False) -> dict:
        name = self.string(node, "font_name")
        font = {"name": name, "height_pixels": None, "bold": None, "italic": None}
        if name:
            font["height_pixels"] = self.number("font_height")
            if is_list:
                font["color"] = color_info(self.number("list_font_color"))
                bold, italic = self.number("list_bold"), self.number("list_italic")
                font.update(bold=bool(bold), italic=bool(italic), bold_raw=bold, italic_raw=italic)
            else:
                flags = self.number("font_flags")
                font.update(flags=flags, bold=bool(flags & 1), italic=bool(flags & 2), unknown_flags=flags & ~3)
        return font

    def node(self, ui_type: int = 0, depth: int = 0, type_offset: int | None = None) -> dict:
        if depth > 96 or self.count >= 100_000:
            raise UIFError("node/depth limit exceeded", self.offset)
        if ui_type not in SUPPORTED_TYPES:
            raise UIFError(f"unsupported UI type {ui_type}", type_offset or self.offset)
        start = self.offset
        uid = f"n{self.count:06d}"
        self.count += 1
        self.type_counts[TYPE_NAMES[ui_type]] += 1
        node = {"uid": uid, "type": TYPE_NAMES[ui_type], "type_id": ui_type,
                "binary": {"offset": start, "type_offset": type_offset, "strings": {}}}
        node["name"] = self.string(node, "name")
        manifest = self.number("children_manifest")
        count, tag = manifest & 0xffff, manifest >> 16
        if count > 4096 or tag not in {0, 1, 2, 3}:
            raise UIFError(f"invalid children/header tag {count}/{tag}", self.offset - 4)
        node["binary"].update(children_manifest=manifest, header_tag=tag)
        children = []
        for _ in range(count):
            offset = self.offset
            children.append(self.node(self.number("child_type"), depth + 1, offset))
        node["children"] = children
        node["id"] = self.string(node, "id")
        node["region"] = self.rect("region")
        node["movable_region"] = self.rect("movable_region")
        node["style"] = style_info(self.number("style"), ui_type)
        node["reserved"] = self.number("reserved")
        node["tooltip"] = self.string(node, "tooltip")
        node["sounds"] = {}
        if self.layout.sounds:
            node["sounds"]["open"] = self.string(node, "sound_open")
            node["sounds"]["close"] = self.string(node, "sound_close")
        # Header tags 0/1 have no extension. Client tags 2/3 append 2/3
        # bytes respectively; preserve them instead of inventing a meaning.
        extra = tag if tag >= 2 else 0
        node["binary"]["extension_hex"] = self.take(extra, "base_extension").hex()
        if ui_type == 4:
            reference = self.string(node, "texture")
            uv = rectangle(self.floats("uv", 4), integral=False)
            fps = self.floats("animation_fps", 1)[0]
            node["image"] = {"texture_reference": reference, "uv": uv, "animation_fps": fps,
                             "animated": bool(node["style"]["value"] & 0x10000)}
        elif ui_type == 1:
            node["button"] = {"click_region": self.rect("click_region")}
            if self.layout.sounds:
                node["sounds"]["hover"] = self.string(node, "sound_hover")
                node["sounds"]["click"] = self.string(node, "sound_click")
        elif ui_type == 6:
            node["font"] = self.font(node)
            node["text_color"] = color_info(self.number("text_color"))
            node["text"] = self.string(node, "text")
            node["line_spacing"] = self.number("line_spacing", signed=True) if self.layout.line_spacing else None
            node["text_origin"] = "serialized_default"
        elif ui_type == 9:
            node["area_type"] = self.number("area_type", signed=True)
        elif ui_type == 14:
            node["font"] = self.font(node, is_list=True)
        elif ui_type in (2, 8):
            if self.layout.sounds:
                node["sounds"]["click"] = self.string(node, "sound_click")
                if ui_type == 8:
                    node["sounds"]["typing"] = self.string(node, "sound_typing")
        elif ui_type == 18:
            node["flash"] = {"unknown_value": self.number("flash_unknown"),
                             "file_reference": self.string(node, "flash_file"),
                             "uv": rectangle(self.floats("flash_uv", 4), integral=False)}
        if ui_type in (15, 16, 17):
            self.warnings.append({"code": "unknown_control_semantics", "node": uid, "type_id": ui_type})
        node["binary"]["length"] = self.offset - start
        return node


def iter_nodes(node: dict):
    yield node
    for child in node["children"]:
        yield from iter_nodes(child)


def parse_uif(data: bytes, encoding: str = "auto") -> dict:
    if encoding != "auto":
        codecs.lookup(encoding)
        b"".decode(encoding)
    errors = []
    for layout in LAYOUTS:
        reader = Reader(data, layout, encoding)
        try:
            root = reader.node()
            if reader.offset != len(data):
                raise UIFError(f"{len(data) - reader.offset} trailing bytes", reader.offset)
            return {"root": root, "layout": layout.name, "bytes_consumed": reader.offset,
                    "node_count": reader.count, "type_counts": dict(sorted(reader.type_counts.items())),
                    "warnings": reader.warnings}
        except UIFError as error:
            errors.append((layout.name, error))
    layout, best = max(errors, key=lambda item: item[1].offset)
    raise UIFError(f"no complete layout matched; furthest profile {layout}: {best}", best.offset, best.field)
