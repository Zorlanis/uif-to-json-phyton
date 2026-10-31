"""N3 FX bundle field extraction with explicit opaque bytes and source offsets.

Field order is based on the primary N3 loaders linked in FORMAT.md. Newer
bundle suffixes and loader-skipped fields remain opaque. No effects are run.
"""

import hashlib
import math
from pathlib import Path
import struct

from uif_parser import decode_string

PARTS = {1: "particles", 2: "billboard", 3: "mesh", 4: "ground_board"}


class EffectError(ValueError):
    pass


class Fields:
    def __init__(self, data):
        self.data, self.offset, self.fields = data, 0, []

    def read(self, name, fmt, opaque=False):
        size = struct.calcsize("<" + fmt)
        start = self.offset
        if start + size > len(self.data):
            raise EffectError(f"truncated effect field {name} at 0x{start:X}")
        raw = self.data[start:start + size]
        self.offset += size
        values = struct.unpack("<" + fmt, raw)
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            raise EffectError(f"nonfinite effect value {name}")
        if len(values) == 1:
            value = values[0]
        else:
            value = list(values)
        item = {"name": name, "offset": start, "format": fmt, "value": value}
        if isinstance(value, bytes):
            item["value"] = value.hex()
            item["storage"] = "hex"
        if opaque:
            item["meaning"] = "unknown"
        self.fields.append(item)
        return value

    def flag(self, name):
        value = self.read(name, "B")
        if value not in {0, 1}:
            raise EffectError(f"invalid effect bool {name}")
        return bool(value)

    def path(self, name):
        offset = self.offset
        raw = self.read(name, "260s")
        text, encoding = decode_string(raw.split(b"\0", 1)[0])
        return {"reference": text, "encoding": encoding, "byte_offset": offset}


def rebuild_effect(document):
    data = bytearray()
    for item in document["fields"]:
        if len(data) != item["offset"]:
            raise EffectError("effect field offset mismatch")
        value = item["value"]
        values = ([bytes.fromhex(value)] if item.get("storage") == "hex" else
                  value if isinstance(value, list) else [value])
        data.extend(struct.pack("<" + item["format"], *values))
    return bytes(data)


def _parse(data, slots):
    r = Fields(data)
    version = r.read("bundle.version", "i")
    if not 0 <= version <= 6:
        raise EffectError(f"unverified bundle version {version}")
    header = {"version": version, "lifetime_seconds_raw": r.read("bundle.lifetime", "f"),
              "velocity": r.read("bundle.velocity", "f"), "depends_on_scale": r.flag("bundle.depends_on_scale")}
    parts, references = [], []
    for slot in range(slots):
        prefix = f"parts[{slot}]"
        kind = r.read(prefix + ".type", "i")
        if kind == 0:
            continue
        if kind not in PARTS:
            raise EffectError(f"unknown effect part type {kind} at slot {slot}")
        part = {"slot": slot, "type_id": kind, "type": PARTS[kind], "byte_offset": r.offset - 4,
                "start_seconds": r.read(prefix + ".start_seconds", "f")}
        pv = r.read(prefix + ".version", "B")
        bv = r.read(prefix + ".base_version", "B")
        if bv > 4 or pv > {1: 11, 2: 9, 3: 9, 4: 3}[kind]:
            raise EffectError(f"unverified effect part/base version {pv}/{bv}")
        part.update(version=pv, base_version=bv, lifetime_seconds_raw=r.read(prefix + ".lifetime", "f"))
        if bv >= 3:
            r.read(prefix + ".unknown_base_values", "2i", True)
        serialized_kind = r.read(prefix + ".base_type", "B")
        if serialized_kind != kind:
            raise EffectError("effect part type mismatch")
        for name in ("velocity", "acceleration", "angular_velocity"):
            part[name] = r.read(prefix + "." + name, "3f")
        part["on_ground"] = r.flag(prefix + ".on_ground")
        part["local_position"] = r.read(prefix + ".position", "3f")
        count = r.read(prefix + ".texture_count", "i")
        if not 0 <= count <= 4096:
            raise EffectError("effect texture count out of bounds")
        part["texture_count"] = count
        part["texture_fps"] = r.read(prefix + ".texture_fps", "f")
        base = r.path(prefix + ".texture_prefix")
        part["texture_prefix"] = base
        if base["reference"]:
            for frame in range(count):
                references.append({**base, "reference": f'{base["reference"]}{frame:04d}.dxt',
                                   "role": "texture_frame", "part_slot": slot, "frame": frame,
                                   "kind": "texture", "evidence": "N3_texture_prefix_plus_frame_number"})
        if bv < 2:
            r.read(prefix + ".alpha_raw", "I")
        part["source_blend"] = r.read(prefix + ".source_blend", "I")
        part["destination_blend"] = r.read(prefix + ".destination_blend", "I")
        part["fade_out_seconds"] = r.read(prefix + ".fade_out", "f")
        part["fade_in_seconds"] = r.read(prefix + ".fade_in", "f")
        if bv >= 2:
            part["render_flags"] = r.read(prefix + ".render_flags", "I")
        if bv >= 4:
            path = r.path(prefix + ".opaque_shape_header")
            r.fields[-1]["meaning"] = "unknown"
            part["uninterpreted_shape_header"] = path

        def read(name, fmt):
            value = r.read(prefix + "." + name, fmt)
            part[name] = value
            return value

        def flag(name):
            value = r.flag(prefix + "." + name)
            part[name] = value
            return value

        def shape(name):
            path = r.path(prefix + "." + name)
            part[name] = path
            if path["reference"]:
                references.append({**path, "role": name, "part_slot": slot, "kind": "model",
                                   "evidence": "fixed_path_field_in_effect_part"})

        if kind == 1:
            if pv < 3:
                raise EffectError("particle versions below 3 are unverified")
            read("particle_count", "i")
            read("particle_size_range" if pv >= 4 else "particle_size", "2f" if pv >= 4 else "f")
            read("particle_life_range", "2f")
            read("create_range_min", "3f"); read("create_range_max", "3f")
            read("create_delay", "f"); read("create_count", "i")
            emit = read("emit_type", "I")
            if emit == 1:
                read("emit_angle", "f")
            elif emit == 2:
                read("gather_point", "3f")
            elif emit != 0:
                raise EffectError("unverified particle emission type")
            read("emit_direction", "3f")
            for name in ("particle_velocity", "particle_acceleration", "particle_rotation_velocity", "gravity"):
                read(name, "f")
            if flag("change_color"):
                colors = read("color_key_count", "i")
                if not 0 <= colors <= 1024:
                    raise EffectError("invalid effect color key count")
                if colors:
                    read("color_keys_argb", f"{colors}I")
            if flag("animation_keys"):
                read("mesh_fps", "f"); shape("animation_shape")
            if pv >= 5:
                for name in ("texture_rotation_velocity", "scale_velocity_x", "scale_velocity_y"):
                    read(name, "f")
            if pv >= 6: flag("distance_count_fix")
            if pv >= 7: flag("particle_y_axis_fix")
            if pv >= 8:
                flag("particle_no_rotation"); read("particle_no_rotation_axis", "3f")
            if pv >= 9:
                read("particle_range_min", "f"); read("particle_range_max", "f")
            if pv >= 10: r.read(prefix + ".unknown_v10", "5s", True)
            if pv >= 11: r.read(prefix + ".unknown_v11", "12s", True)
        elif kind == 2:
            read("billboard_count", "i"); read("size_x", "f"); read("size_y", "f")
            flag("texture_loop"); read("radius", "f")
            if pv >= 3: flag("rotate_only_y")
            if pv >= 4:
                for name in ("scale_velocity_x", "scale_velocity_y", "scale_acceleration_x", "scale_acceleration_y"):
                    read(name, "f")
            if pv >= 5: read("rotation_matrix", "16f")
            if pv >= 6: flag("on_screen")
            if pv >= 7: flag("rotation_rate")
            if pv >= 8: r.read(prefix + ".unknown_v8", "13s", True)
            if pv >= 9: r.read(prefix + ".unknown_v9", "12s", True)
        elif kind == 3:
            shape("mesh_shape")
            read("texture_move_direction_raw", "b"); read("texture_u_velocity", "f"); read("texture_v_velocity", "f")
            read("scale_velocity", "3f")
            if pv >= 2: flag("texture_loop")
            if pv >= 3: read("scale_acceleration", "3f")
            if pv >= 4: read("mesh_fps", "f")
            if pv >= 5: read("unit_scale", "3f")
            if pv >= 6: flag("shape_loop")
            if pv >= 7: flag("view_fix")
            if pv >= 8: flag("use_fade_show_life")
            if pv >= 9: r.read(prefix + ".unknown_v9", "260s", True)
        else:
            for name in ("size_x", "size_z", "scale_velocity_x", "scale_velocity_z"):
                read(name, "f")
            flag("texture_loop")
            if pv >= 1: read("gap", "f")
            if pv >= 2: flag("new_uv")
            if pv >= 3: flag("hdr_uv")
        part["byte_length"] = r.offset - part["byte_offset"]
        parts.append(part)
    if version >= 2:
        header["static"] = r.flag("bundle.static")
    remaining = len(data) - r.offset
    if remaining:
        r.read("bundle.uninterpreted_suffix", f"{remaining}s", True)
    return {"header": header, "part_slots": slots, "parts": parts, "references": references,
            "fields": r.fields, "opaque_suffix_bytes": remaining}


def inspect_effect(path: Path, catalog) -> dict:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise EffectError("effect exceeds 16 MiB limit")
    data = path.read_bytes()
    version = struct.unpack_from("<i", data)[0] if len(data) >= 4 else -1
    results = []
    for slots in ([8] if version == 0 else [26, 16]):
        try:
            results.append(_parse(data, slots))
        except (ValueError, struct.error):
            pass
    if not results:
        raise EffectError("no verified effect part layout matched; original file remains in inventory")
    result = min(results, key=lambda item: item["opaque_suffix_bytes"])
    if rebuild_effect(result) != data:
        raise EffectError("effect fields fail exact byte reconstruction")
    for reference in result["references"]:
        reference["resource"] = catalog.resolve(reference["reference"], reference["kind"])
    unknown = [{"field": item["name"], "offset": item["offset"], "byte_size": struct.calcsize("<" + item["format"])}
               for item in result["fields"] if item.get("meaning") == "unknown"]
    result.update(source={"relative_path": path.relative_to(catalog.root).as_posix(),
                          "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                  integrity={"byte_reconstruction": "exact_match", "verified_bytes": len(data)},
                  interpretation={"reference": "Open-KO N3 FX loaders", "target_runtime_verified": False,
                                  "uninterpreted_fields": unknown, "world_to_screen_binding": "not_serialized_here"})
    return result
