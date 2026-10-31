"""Enrich the lossless record tree with layout, resource usage and UI roles."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
from pathlib import Path

from uif_assets import AssetCatalog
from uif_audit import coverage
from uif_parser import iter_nodes, parse_uif, rectangle

SCHEMA_VERSION = 1
ANALYSIS_VERSION = "0.5.0"
BUTTON_STATES = {0: "normal", 1: "pressed", 2: "hover_or_checked", 3: "disabled"}
AREA_TYPES = dict(enumerate(("none", "slot", "inventory", "trade_npc", "personal_trade_my",
                            "personal_trade_other", "drop_item", "skill_tree", "skill_hotkey",
                            "repair_inventory", "repair_npc", "trade_my", "personal_trade_inventory")))


def _relative(region: dict, parent: dict) -> dict:
    return rectangle((region["left"] - parent["left"], region["top"] - parent["top"],
                      region["right"] - parent["left"], region["bottom"] - parent["top"]))


def _roles(node: dict, warnings: list) -> None:
    children = node["children"]
    if node["type"] == "button":
        images = [child for child in children if child["type"] == "image"]
        states = defaultdict(list)
        for child in images:
            role = BUTTON_STATES.get(child["reserved"], "unknown_button_state")
            child["usage_role"] = "button_" + role
            states[role].append(child["uid"])
        node["button"]["state_images"] = dict(states)
        effective = {role: uids[0] for role, uids in states.items() if role != "unknown_button_state"}
        node["button"]["effective_state_images"] = effective
        node["button"]["always_render_children"] = [child["uid"] for child in children
                                                       if child["uid"] not in effective.values()]
        for role, uids in states.items():
            if len(uids) > 1 and role != "unknown_button_state":
                warnings.append({"code": "duplicate_button_state", "node": node["uid"],
                                 "state": role, "candidates": uids, "effective_node": uids[0]})
        node["button"]["mode"] = "check" if node["style"]["value"] & 0x20000 else "normal"
    elif node["type"] in {"progress", "trackbar"}:
        slots = {0: "background", 1: "foreground" if node["type"] == "progress" else "thumb"}
        mapping = defaultdict(list)
        for child in children:
            if child["type"] == "image":
                role = slots.get(child["reserved"], "unknown_image_slot")
                child["usage_role"] = node["type"] + "_" + role
                mapping[role].append(child["uid"])
        node["control_parts"] = dict(mapping)
        node["effective_control_parts"] = {role: uids[0] for role, uids in mapping.items()
                                            if role != "unknown_image_slot"}
    elif node["type"] == "scrollbar":
        effective = {}
        for child in children:
            if child["type"] == "button":
                child["usage_role"] = {0: "scroll_left_or_up", 1: "scroll_right_or_down"}.get(child["reserved"], "scroll_button_unknown")
            elif child["type"] == "trackbar":
                child["usage_role"] = "scroll_trackbar"
            if child.get("usage_role") not in {None, "scroll_button_unknown"}:
                effective.setdefault(child["usage_role"], child["uid"])
        node["effective_control_parts"] = effective
    elif node["type"] in {"static", "edit"}:
        effective = {}
        for child in children:
            if child["type"] == "image":
                child["usage_role"] = node["type"] + "_background"
            elif child["type"] == "string":
                child["usage_role"] = node["type"] + "_text"
            if child.get("usage_role"):
                effective.setdefault(child["usage_role"], child["uid"])
        node["effective_control_parts"] = effective
    elif node["type"] == "image" and node["image"]["animated"]:
        frames = [child for child in children if child["type"] == "image"]
        frames.reverse()  # AddChild pushes to the front; the loader walks that order.
        node["image"]["frames"] = [child["uid"] for child in frames]
        node["image"]["frame_count"] = len(frames)
        fps = node["image"]["animation_fps"]
        node["image"]["cycle_seconds"] = len(frames) / fps if fps > 0 and frames else None
        node["image"]["frame_order_matches_reserved"] = all(child["reserved"] == i for i, child in enumerate(frames))
        if not node["image"]["frame_order_matches_reserved"]:
            warnings.append({"code": "animation_frame_order_mismatch", "node": node["uid"]})
        if len(frames) != len(children):
            warnings.append({"code": "animation_non_image_child", "node": node["uid"]})
        if not frames or fps <= 0:
            warnings.append({"code": "animation_missing_frames_or_invalid_fps", "node": node["uid"]})
        for index, child in enumerate(frames):
            child["usage_role"] = "animation_frame"
            child["animation_frame_index"] = index


def analyze(source: Path, catalog: AssetCatalog, encoding: str = "auto") -> dict:
    data = source.read_bytes()
    parsed = parse_uif(data, encoding)
    root = parsed["root"]
    warnings = parsed["warnings"]
    assets: dict[str, dict] = {}
    text_entries = []
    tooltips = []
    resources = []
    node_index = []
    root_region = root["region"]

    def visit(node: dict, parent: dict | None, order: int, tree_path: str) -> None:
        region = node["region"]
        node["parent_uid"] = parent["uid"] if parent else None
        node["file_order"] = order
        node["layout"] = {"coordinate_space": "stored_canvas_pixels",
                          "relative_to_parent": _relative(region, parent["region"]) if parent else None,
                          "relative_to_root": _relative(region, root_region)}
        node_index.append({"uid": node["uid"], "id": node["id"], "type": node["type"],
                           "parent_uid": node["parent_uid"], "tree_path": tree_path})
        _roles(node, warnings)
        if "area_type" in node:
            node["area_type_name"] = AREA_TYPES.get(node["area_type"])
        if region["width"] < 0 or region["height"] < 0:
            warnings.append({"code": "inverted_region", "node": node["uid"]})
        for field, rect in (("movable_region", node["movable_region"]),
                            ("click_region", node.get("button", {}).get("click_region"))):
            if rect is not None and (field == "click_region" or any(rect[key] for key in ("left", "top", "right", "bottom"))):
                node["layout"].setdefault("interaction_regions", {})[field] = {
                    "relative_to_node": _relative(rect, region),
                    "relative_to_root": _relative(rect, root_region)}
        if node["tooltip"]:
            tooltips.append({"node_uid": node["uid"], "id": node["id"], "text": node["tooltip"], "region": region})
        if "text" in node:
            flags = node["style"]["value"]
            node["text_layout"] = {
                "single_line": bool(flags & 0x100000),
                "horizontal_alignment": "right" if flags & 0x400000 else "center" if flags & 0x800000 else "left",
                "vertical_alignment": "bottom" if flags & 0x2000000 else "center" if flags & 0x4000000 else "top",
                "alignment_is_requested": True,
            }
            text_entries.append({"node_uid": node["uid"], "id": node["id"], "text": node["text"],
                                 "tooltip": node["tooltip"], "region": region, "font": node["font"],
                                 "color": node["text_color"], "alignment": node["text_layout"],
                                 "line_spacing": node["line_spacing"]})
        if "image" in node:
            image = node["image"]
            resource = catalog.resolve(image["texture_reference"])
            image["asset_id"] = resource["asset_id"]
            image["resolution_status"] = resource["status"]
            if resource.get("editor_load_error"):
                image["editor_load_error"] = True
                warnings.append({"code": "serialized_texture_load_failure", "node": node["uid"],
                                 "reference": image["texture_reference"], "lookup_reference": resource.get("lookup_reference")})
            uv = image["uv"]
            if any(not 0 <= uv[key] <= 1 for key in ("left", "top", "right", "bottom")):
                warnings.append({"code": "uv_outside_unit_range", "node": node["uid"]})
            image["flip_x"], image["flip_y"] = uv["right"] < uv["left"], uv["bottom"] < uv["top"]
            metadata = resource.get("texture", {})
            if "width" in metadata:
                width, height = metadata["width"], metadata["height"]
                image["source_rect_pixels"] = rectangle((uv["left"] * width, uv["top"] * height,
                                                          uv["right"] * width, uv["bottom"] * height), integral=False)
                crop = image["source_rect_pixels"]
                image["scale"] = {"x": region["width"] / crop["width"] if crop["width"] else None,
                                  "y": region["height"] / crop["height"] if crop["height"] else None}
            image["destination_rect"] = dict(region)
            image["quad"] = [
                {"x": region["left"], "y": region["top"], "u": uv["left"], "v": uv["top"]},
                {"x": region["right"], "y": region["top"], "u": uv["right"], "v": uv["top"]},
                {"x": region["right"], "y": region["bottom"], "u": uv["right"], "v": uv["bottom"]},
                {"x": region["left"], "y": region["bottom"], "u": uv["left"], "v": uv["bottom"]},
            ]
            if resource["asset_id"]:
                asset = assets.setdefault(resource["asset_id"], {**resource, "references": [], "used_by_nodes": []})
                if image["texture_reference"] not in asset["references"]:
                    asset["references"].append(image["texture_reference"])
                asset["used_by_nodes"].append(node["uid"])
            if resource["status"] in {"missing", "ambiguous"}:
                warnings.append({"code": "texture_" + resource["status"], "node": node["uid"],
                                 "reference": image["texture_reference"], "candidates": resource.get("candidates", [])})
            elif resource["status"] == "found" and "metadata_error" in metadata:
                warnings.append({"code": "texture_metadata_unavailable", "node": node["uid"],
                                 "reference": image["texture_reference"], "reason": metadata["metadata_error"]})
        sound_resources = {key: catalog.resolve(value, "sound") for key, value in node["sounds"].items() if value}
        if sound_resources:
            node["sound_resources"] = sound_resources
            for role, resource in sound_resources.items():
                resources.append({"kind": "sound", "role": role, "node_uid": node["uid"], **resource})
                if resource["status"] != "found":
                    warnings.append({"code": "sound_" + resource["status"], "node": node["uid"], "role": role})
        if "flash" in node:
            node["flash"]["resource"] = catalog.resolve(node["flash"]["file_reference"], "flash")
            resource = node["flash"]["resource"]
            resources.append({"kind": "flash", "role": "movie", "node_uid": node["uid"], **resource})
            if resource["status"] in {"missing", "ambiguous"}:
                warnings.append({"code": "flash_" + resource["status"], "node": node["uid"]})
        for index, child in enumerate(node["children"]):
            visit(child, node, index, f"{tree_path}.children[{index}]")

    visit(root, None, 0, "root")
    audit = coverage(root, data, parsed["layout"])
    duplicate_ids = []
    id_nodes = defaultdict(list)
    for item in node_index:
        if item["id"]:
            id_nodes[item["id"]].append(item["uid"])
    for key, values in id_nodes.items():
        if len(values) > 1:
            duplicate_ids.append({"id": key, "nodes": values})
    try:
        source_relative = source.resolve().relative_to(catalog.root).as_posix()
    except ValueError:
        source_relative = source.name
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "source": {"relative_path": source_relative, "absolute_path": str(source.resolve()),
                   "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "format": {"name": "knight_online_uif", "layout": parsed["layout"],
                   "bytes_consumed": parsed["bytes_consumed"], "complete": True,
                   "string_encoding": encoding, "children_order": "file_order_back_to_front",
                   "base_mouse_dispatch_order": "reverse_file_order_subject_to_runtime_state",
                   "derived_behavior_reference": "Open-KO N3 UI; target client behavior may differ",
                   "coordinates": "Stored coordinates are canvas pixels; parent-relative positions are derived, not added."},
        "summary": {"nodes": parsed["node_count"], "types": parsed["type_counts"],
                    "text_elements": len(text_entries), "tooltip_elements": len(tooltips), "textures": len(assets),
                    "unresolved_textures": sum(asset["status"] != "found" for asset in assets.values()),
                    "warning_counts": dict(sorted(Counter(warning["code"] for warning in warnings).items()))},
        "root": root, "node_index": {item["uid"]: item["tree_path"] for item in node_index},
        "coverage": audit, "resources": resources,
        "textures": sorted(assets.values(), key=lambda asset: asset["asset_id"]),
        "texts": text_entries, "tooltips": tooltips, "duplicate_element_ids": duplicate_ids, "warnings": warnings,
    }
