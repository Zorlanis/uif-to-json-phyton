"""Resolve serialized resource names against a client tree and read image headers."""

from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path, PurePosixPath
import posixpath
import struct

from uif_parser import decode_string

DXT_FORMATS = {int.from_bytes(f"DXT{i}".encode(), "little"): f"dxt{i}" for i in range(1, 6)}
DXT_FORMATS.update({20: "r8g8b8", 21: "a8r8g8b8", 22: "x8r8g8b8", 23: "r5g6b5",
                    24: "x1r5g5b5", 25: "a1r5g5b5", 26: "a4r4g4b4"})


def normalized(reference: str) -> str:
    value = reference.rstrip("\0").strip().replace("\\", "/")
    return posixpath.normpath(value).casefold() if value else ""


def walk_files(root: Path, excluded: Path | None = None):
    pending = [root]
    while pending:
        folder = pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                if path == excluded or entry.is_symlink():
                    continue
                if os.name == "nt" and getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path


def texture_header(path: Path) -> dict:
    with path.open("rb") as stream:
        head = stream.read(1024)
    result = {"byte_size": path.stat().st_size}
    if len(head) >= 24:
        length = struct.unpack_from("<I", head)[0]
        offset = 4 + length
        if length <= 256 and head[offset:offset + 3] == b"NTF":
            if len(head) < offset + 20:
                raise ValueError("truncated NTF header")
            version, width, height, code, flags = struct.unpack_from("<B4I", head, offset + 3)
            result.update(container="ntf", version=version, encrypted=version == 7,
                          embedded_name=decode_string(head[4:offset])[0],
                          width=width, height=height, format=DXT_FORMATS.get(code, f"0x{code:08X}"),
                          format_code=code, flags=flags)
    if "width" not in result:
        if head.startswith(b"DDS ") and len(head) >= 128:
            height, width = struct.unpack_from("<II", head, 12)
            code = struct.unpack_from("<I", head, 84)[0]
            result.update(container="dds", width=width, height=height,
                          format=DXT_FORMATS.get(code, f"0x{code:08X}"), format_code=code)
        elif head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
            width, height = struct.unpack_from(">II", head, 16)
            result.update(container="png", width=width, height=height, format="png")
        elif head.startswith(b"BM") and len(head) >= 26:
            dib = struct.unpack_from("<I", head, 14)[0]
            if dib >= 40:
                width, height = struct.unpack_from("<ii", head, 18)
            elif dib == 12:
                width, height = struct.unpack_from("<HH", head, 18)
            else:
                raise ValueError("unsupported BMP header")
            result.update(container="bmp", width=abs(width), height=abs(height), format="bmp")
        elif len(head) >= 18 and head[2] in {1, 2, 3, 9, 10, 11} and head[16] in {8, 15, 16, 24, 32}:
            width, height = struct.unpack_from("<HH", head, 12)
            result.update(container="tga", width=width, height=height, format="tga", bits_per_pixel=head[16])
        else:
            raise ValueError("image dimensions unavailable from the resource header")
    if not (1 <= result["width"] <= 32768 and 1 <= result["height"] <= 32768):
        raise ValueError("invalid image dimensions")
    return result


class AssetCatalog:
    def __init__(self, root: Path, output: Path | None = None):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise NotADirectoryError(str(root))
        self.paths: dict[str, list[Path]] = defaultdict(list)
        self.basenames: dict[str, list[Path]] = defaultdict(list)
        self.metadata: dict[Path, dict] = {}
        self.cache: dict[tuple[str, str], dict] = {}
        self.file_count = 0
        for path in walk_files(self.root, output):
            relative = path.relative_to(self.root).as_posix()
            self.paths[relative.casefold()].append(path)
            self.basenames[path.name.casefold()].append(path)
            self.file_count += 1

    def resolve(self, reference: str, kind: str = "texture") -> dict:
        key = (reference, kind)
        if key not in self.cache:
            self.cache[key] = self._resolve(reference, kind)
        return self.cache[key]

    def visual_sources(self, path: Path) -> dict:
        """Point at existing rasters without claiming PNG/DXT pixel equality."""
        relative = path.relative_to(self.root).as_posix()
        stem = str(PurePosixPath(relative).with_suffix(""))
        plans = [(stem + ".png", "same_relative_stem"),
                 ("outputs/" + stem + ".png", "mirrored_path_under_outputs")]
        candidates, seen = [], set()
        for candidate, basis in plans:
            for match in self.paths.get(candidate.casefold(), []):
                if match not in seen:
                    seen.add(match)
                    candidates.append({"relative_path": match.relative_to(self.root).as_posix(),
                                       "absolute_path": str(match), "match_basis": basis,
                                       "matches_DXT_pixels_verified": False})
        if not candidates:
            basename = PurePosixPath(stem).name.casefold() + ".png"
            matches = self.basenames.get(basename, [])
            if len(matches) == 1:
                candidates.append({"relative_path": matches[0].relative_to(self.root).as_posix(),
                                   "absolute_path": str(matches[0]), "match_basis": "unique_basename_only",
                                   "matches_DXT_pixels_verified": False})
        dxt = self.paths.get((stem + ".dxt").casefold(), [])
        return {"original_relative_path": relative, "original_absolute_path": str(path),
                "dxt": {"relative_path": dxt[0].relative_to(self.root).as_posix(), "absolute_path": str(dxt[0])} if len(dxt) == 1 else None,
                "existing_png_candidates": candidates, "conversion_performed": False}

    def _resolve(self, reference: str, kind: str) -> dict:
        name = normalized(reference)
        result = {"reference": reference, "normalized_reference": name, "kind": kind}
        marker = " : load fail."
        if kind == "texture" and name.endswith(marker):
            result["editor_load_error"] = True
            clean = name[:-len(marker)].strip()
            if clean:
                name = clean
                result["lookup_reference"] = name
        if not name or name == ".":
            return {**result, "status": "empty", "asset_id": None}
        alternatives = [name]
        suffix = PurePosixPath(name).suffix
        if kind == "texture" and suffix in {".tga", ".bmp", ".dds", ".png", ".jpg", ".jpeg"}:
            alternatives.append(str(PurePosixPath(name).with_suffix(".dxt")))
        plans = []
        for i, candidate in enumerate(alternatives):
            plans.append((candidate, "client_relative" if i == 0 else "extension_alias_to_dxt"))
            if candidate.startswith("ui_us/"):
                plans.append(("ui/" + candidate[6:], "ui_us_to_ui_alias"))
            if ":" in candidate or candidate.startswith("/"):
                parts = candidate.split("/")
                plans.extend(("/".join(parts[index:]), "absolute_reference_rebased") for index in range(1, len(parts) - 1))
        path = None
        method = "not_found"
        ambiguous = []
        for candidate, candidate_method in plans:
            matches = self.paths.get(candidate, [])
            if len(matches) == 1:
                path, method = matches[0], candidate_method
                break
            if len(matches) > 1:
                ambiguous = matches
                break
        if path is None and not ambiguous:
            for candidate in alternatives:
                matches = self.basenames.get(PurePosixPath(candidate).name, [])
                if len(matches) == 1:
                    path, method = matches[0], "unique_basename" if candidate == name else "unique_basename_and_extension_alias"
                    break
                if len(matches) > 1:
                    ambiguous = matches
                    break
        if path is None:
            return {**result, "status": "ambiguous" if ambiguous else "missing", "asset_id": "unresolved:" + name,
                    "candidates": sorted(p.relative_to(self.root).as_posix() for p in ambiguous)}
        relative = path.relative_to(self.root).as_posix()
        result.update(status="found", asset_id=relative.casefold(), relative_path=relative,
                      absolute_path=str(path), resolution_method=method)
        if kind == "texture":
            result["visual_sources"] = self.visual_sources(path)
            if path not in self.metadata:
                try:
                    self.metadata[path] = texture_header(path)
                except (OSError, ValueError, struct.error) as error:
                    self.metadata[path] = {"metadata_error": str(error)}
            result["texture"] = self.metadata[path]
        return result
