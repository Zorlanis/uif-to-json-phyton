"""AI navigation, complete file inventory and honest Unity migration preflight."""

from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import struct

from uif_effects import inspect_effect
from uif_parser import iter_nodes


def font_names(path):
    """Read SFNT family names without requiring an installed font/library."""
    raw = path.read_bytes()
    if len(raw) > 32 * 1024 * 1024 or len(raw) < 12:
        raise ValueError("unsupported font size")
    offsets = [0]
    if raw[:4] == b"ttcf":
        count = struct.unpack_from(">I", raw, 8)[0]
        if not 0 < count <= 128:
            raise ValueError("invalid font collection count")
        offsets = struct.unpack_from(">" + "I" * count, raw, 12)
    result = []
    for face, offset in enumerate(offsets):
        count = struct.unpack_from(">H", raw, offset + 4)[0]
        if not 0 < count <= 256:
            raise ValueError("invalid SFNT table count")
        for index in range(count):
            tag, _, start, size = struct.unpack_from(">4sIII", raw, offset + 12 + index * 16)
            if tag != b"name":
                continue
            if start + size > len(raw):
                raise ValueError("font name table outside file")
            _, names, storage = struct.unpack_from(">3H", raw, start)
            if names > 4096 or 6 + names * 12 > size:
                raise ValueError("invalid font name records")
            for i in range(names):
                platform, encoding, language, name_id, length, name_offset = struct.unpack_from(">6H", raw, start + 6 + i * 12)
                if name_id not in {1, 2, 4, 6, 16, 17}:
                    continue
                position = start + storage + name_offset
                if position + length > start + size:
                    raise ValueError("font name string outside table")
                data = raw[position:position + length]
                codec = "utf-16-be" if platform in {0, 3} else "mac_roman" if platform == 1 else "latin1"
                result.append({"face": face, "name_id": name_id, "platform": platform,
                               "encoding_id": encoding, "language_id": language,
                               "text": data.decode(codec, errors="replace"), "raw_hex": data.hex()})
    return {"names": result, "sha256": hashlib.sha256(raw).hexdigest()}


def ugui_geometry(node):
    """Optional fixed-pixel recipe, not a claim about original runtime anchors."""
    rect = node["layout"]["relative_to_parent"] or node["region"]
    return {"anchor_min": [0, 1], "anchor_max": [0, 1], "pivot": [0, 1],
            "anchored_position": [rect["left"], -rect["top"]],
            "size_delta": [rect["width"], rect["height"]],
            "valid_positive_size": rect["width"] > 0 and rect["height"] > 0}


def decorate_uif(document):
    for node in iter_nodes(document["root"]):
        node["unity_ugui_geometry"] = ugui_geometry(node)
    document["migration"] = {
        "geometry_recipe": "optional_fixed_pixel_ugui_top_left",
        "recipe_assumptions": "Parent pivot is top-left, unit scale, no layout components, source pixels are canvas units.",
        "reference_resolution": None, "runtime_anchors": "unknown", "pixel_identity_verified": False,
        "root_placement": "Stored root position is preserved; runtime centering/placement is unknown.",
    }


class MigrationAudit:
    def __init__(self, catalog, output, writer, reporter, version, compact=False, effects=True):
        self.catalog, self.output, self.writer, self.reporter = catalog, output, writer, reporter
        self.compact, self.effects_enabled = compact, effects
        self.shared = {"schema_version": 1, "analysis_version": version, "client_root": str(catalog.root)}
        self.screens, self.effect_records = [], []
        self.font_usage = defaultdict(list)
        self.requested_characters = defaultdict(set)
        self.opaque_UI_fields = Counter()
        self.referenced_files = set()
        self.effects = {"effect_total": 0, "effect_parsed": 0, "effect_failed": 0,
                        "effect_with_uninterpreted_fields": 0, "effect_parts": 0}

    def add_uif(self, document, output):
        path = document["source"]["relative_path"]
        groups = defaultdict(list)
        for group in document["coverage"]["uninterpreted_fields"]:
            self.opaque_UI_fields[group["field"]] += len(group["nodes"])
        for node in iter_nodes(document["root"]):
            font = node.get("font", {})
            if font.get("name"):
                signature = (font["name"], font["height_pixels"], font["bold"], font["italic"])
                groups[signature].append(node["uid"])
                self.requested_characters[font["name"]].update(node.get("text", ""))
        for (name, height, bold, italic), nodes in groups.items():
            self.font_usage[name].append({"uif": path, "json": output, "nodes": nodes,
                                         "height_pixels": height, "bold": bold, "italic": italic})
        textures = []
        for asset in document["textures"]:
            textures.append({"asset_id": asset["asset_id"], "status": asset["status"],
                             "nodes": asset["used_by_nodes"], "visual_sources": asset.get("visual_sources")})
            if asset["status"] == "found":
                self.referenced_files.add(asset["asset_id"])
        for resource in document["resources"]:
            if resource["status"] == "found":
                self.referenced_files.add(resource["asset_id"])
        self.screens.append({"uif": path, "json": output, "source_sha256": document["source"]["sha256"],
                             "root_region": document["root"]["region"], "summary": document["summary"],
                             "table_links": document.get("table_links", []), "textures": textures,
                             "fonts": sorted({key[0] for key in groups}),
                             "effect_binding": "not_established_by_UIF_or_text_equality"})

    def scan_effects(self):
        if not self.effects_enabled:
            return
        files = sorted(path for matches in self.catalog.paths.values() for path in matches if path.suffix.casefold() == ".fxb")
        self.effects["effect_total"] = len(files)
        self.reporter.event("audit_stage", stage="effects", total=len(files))
        for index, path in enumerate(files, 1):
            relative = path.relative_to(self.catalog.root).as_posix()
            record = {"source": relative, "absolute_path": str(path),
                      "conversion": "delegated_to_consumer_AI", "scan_mode": "resource_paths_only"}
            try:
                document = inspect_effect(path, self.catalog)
                record.update(status="parsed", parts=len(document["parts"]),
                              unknown_fields=len(document["interpretation"]["uninterpreted_fields"]),
                              source_sha256=document["source"]["sha256"],
                              images=[ref for ref in document["references"] if ref["kind"] == "texture"],
                              other_dependencies=[ref for ref in document["references"] if ref["kind"] != "texture"])
                self.effects["effect_parsed"] += 1
                self.effects["effect_parts"] += len(document["parts"])
                self.effects["effect_with_uninterpreted_fields"] += bool(record["unknown_fields"])
                for reference in document["references"]:
                    if reference["resource"]["status"] == "found":
                        self.referenced_files.add(reference["resource"]["asset_id"])
            except (ValueError, OSError) as error:
                self.effects["effect_failed"] += 1
                record.update(status="error", error=str(error))
                self.reporter.event("error", stage="effect", **record)
            self.effect_records.append(record)
            if index % 100 == 0 or index == len(files):
                self.reporter.event("audit_progress", stage="effects", processed=index, total=len(files))

    def finish(self, summary, table_index):
        self.scan_effects()
        font_files, font_errors = [], []
        for matches in self.catalog.paths.values():
            for path in matches:
                if path.suffix.casefold() not in {".ttf", ".otf", ".ttc"}:
                    continue
                try:
                    font_files.append({"relative_path": path.relative_to(self.catalog.root).as_posix(), **font_names(path)})
                except (ValueError, OSError, struct.error) as error:
                    font_errors.append({"path": path.relative_to(self.catalog.root).as_posix(), "error": str(error)})
        fonts = []
        for name, usage in sorted(self.font_usage.items()):
            matches = [item["relative_path"] for item in font_files
                       if any(record["name_id"] in {1, 4, 6, 16} and record["text"].casefold() == name.casefold()
                              for record in item["names"])]
            fonts.append({"name": name, "client_font_candidates": matches, "used_by": usage,
                          "resolution": "family_name_match_only" if matches else "font_file_not_located_in_client",
                          "style_face_and_metrics_verified": False,
                          "required_unicode_codepoints": sorted(ord(c) for c in self.requested_characters[name]),
                          "glyph_coverage_verified": False})
        self.writer(self.output / "font_index.json", {**self.shared, "requested_fonts": fonts,
                    "client_font_files": font_files, "font_errors": font_errors,
                    "scope": "Client font name tables only. OS fonts, shaping and glyph coverage are not verified."}, self.compact, True)
        self.writer(self.output / "screen_index.json", {**self.shared, "screens": self.screens,
                    "scope": "Every exported UIF is indexed; runtime visibility and screen roles are not inferred from filenames."}, self.compact, True)
        self.writer(self.output / "effect_index.json", {**self.shared, "enabled": self.effects_enabled,
                    "summary": self.effects, "mode": "DXT_and_existing_PNG_paths_only_no_FXB_conversion",
                    "files": self.effect_records}, self.compact, True)

        self.reporter.event("audit_stage", stage="asset_inventory", total=self.catalog.file_count)
        inventory, extensions = [], Counter()
        if table_index:
            for reference in table_index.references:
                if reference["resource"]["status"] == "found":
                    self.referenced_files.add(reference["resource"]["asset_id"])
        for relative, paths in sorted(self.catalog.paths.items()):
            for path in paths:
                stat = path.stat()
                suffix = path.suffix.casefold()
                item = {"path": path.relative_to(self.catalog.root).as_posix(), "bytes": stat.st_size,
                        "extension": suffix, "referenced_by_extracted_data": relative in self.referenced_files}
                # Preserve existing derived files too; relevance belongs to the consumer.
                item["under_outputs_named_directory"] = "outputs" in [part.casefold() for part in path.relative_to(self.catalog.root).parts[:-1]]
                if relative in self.referenced_files or suffix in {".uif", ".tbl", ".fxb", ".ttf", ".otf", ".ttc"}:
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    item["sha256"] = digest.hexdigest()
                inventory.append(item)
                extensions[suffix] += 1
        self.writer(self.output / "asset_inventory.json", {**self.shared, "files": inventory,
                    "extensions": dict(sorted(extensions.items())), "relevance_policy": "consumer_decides",
                    "source_binaries_copied": False,
                    "hash_policy": "UIF/TBL/FXB/fonts and resolved referenced assets; no hash means not computed",
                    "scope": "All indexed client files, including potential derived outputs. No files are deleted."}, self.compact, True)

        unresolved_fonts = sum(not item["client_font_candidates"] for item in fonts)
        blockers = [
            {"code": "runtime_bindings_missing", "scope": "global", "required_evidence": "target client code or runtime observations",
             "details": "Event handlers, screen placement/anchors, server text, live visibility/state, effect attachment and TBL ID meaning are not proven."},
            {"code": "font_rendering_not_verified", "count_without_client_font": unresolved_fonts,
             "details": "Family names and pixel heights are preserved; exact font faces, glyphs, shaping, rasterization and line wrapping need verification."},
            {"code": "unity_rendering_not_verified", "details": "Canvas reference size, DPI, texture sampling, UV origin, alpha, blend and gamma must be compared to target-client captures."},
            {"code": "other_game_asset_formats_not_decoded", "details": "Meshes, skeletons, animations, maps and shaders remain source files in inventory; this is not a whole-game importer."},
        ]
        if summary["warning_counts"].get("unknown_control_semantics"):
            blockers.append({"code": "unknown_UI_control_semantics", "count": summary["warning_counts"]["unknown_control_semantics"], "report": "coverage_report.json"})
        if summary["unresolved_textures"] or summary.get("tbl_unresolved_uif_references"):
            blockers.append({"code": "missing_UI_assets", "textures": summary["unresolved_textures"],
                             "table_UIF_references": summary.get("tbl_unresolved_uif_references", 0)})
        if summary.get("tbl_failed"):
            blockers.append({"code": "undecoded_tables", "count": summary["tbl_failed"], "report": "table_index.json"})
        if summary.get("tbl_columns"):
            blockers.append({"code": "table_column_meanings_and_numeric_joins_unverified", "columns": summary["tbl_columns"],
                             "report": "table_schema_report.json"})
        if summary.get("tbl_ambiguous_encoding_cells"):
            blockers.append({"code": "table_encoding_requires_review", "cells": summary["tbl_ambiguous_encoding_cells"],
                             "report": "table_schema_report.json"})
        if self.effects["effect_failed"] or self.effects["effect_with_uninterpreted_fields"]:
            blockers.append({"code": "effect_conversion_delegated_to_AI", **self.effects, "report": "effect_index.json"})
        if not self.effects_enabled:
            blockers.append({"code": "effect_scan_disabled"})
        if table_index is None:
            blockers.append({"code": "table_scan_disabled"})
        if self.opaque_UI_fields:
            blockers.append({"code": "uninterpreted_UI_fields", "field_use_counts": dict(self.opaque_UI_fields),
                             "report": "coverage_report.json"})
        report = {**self.shared, "target": "Unity", "pixel_identical_ready": False,
                  "whole_game_importer": False, "relevance_policy": "consumer_decides_keep_source_data",
                  "summary": {"screens": len(self.screens), "requested_font_families": len(fonts),
                              "font_families_without_client_file": unresolved_fonts,
                              "inventory_files": len(inventory), **self.effects}, "blockers": blockers,
                  "entry_points": {"screens": "screen_index.json", "fonts": "font_index.json", "effects": "effect_index.json",
                                   "table_links": "tbl_uif_links.json", "all_assets": "asset_inventory.json",
                                   "table_profiles": "table_schema_report.json", "table_candidates": "table_review_candidates.json",
                                   "raw_UI_fields": "coverage_report.json", "instructions": "AI_GUIDE.md"},
                  "render_validation": {"performed": False, "required": "Compare target-client captures and Unity renders at equal resolution, DPI, language and control state."}}
        self.writer(self.output / "migration_report.json", report, self.compact, True)
        guide = """# AI aktarım rehberi

Amaç: kaynak oyun verilerinden Unity aktarımını planlamak ve kanıtlanmış alanları korumak.
İlk olarak migration_report.json, ardından screen_index.json okuyun. Hazır olma durumu
false ise bunu tam/birebir aktarım olarak sunmayın. Dosya yolları client_root'a göredir.

Bir ekran: screen_index -> uif/<yol>.json -> root/node_index -> image/texture/text/font.
TBL hücresi: tbl_uif_links -> ilgili UIF -> textures -> texture_index. Efektler için
effect_index -> images -> resource.visual_sources içindeki DXT ve mevcut PNG
yolları izlenir. FXB dosyası dönüştürülmez; original source/absolute_path üzerinden
dönüşümü aktarım yapan AI yapar. Efektin hangi sahne/ekrana ne zaman bağlandığı oyun
kodu gerektirir. Kaynak prefix+kare numarası bağımlılığını okumak, FXB dönüşümü değildir.

TBL kolonları konumsaldır. Eşit ID veya eşit yazı, çalışma anında bağlantı kanıtı değildir.
table_schema_report sütun tipleri, dağılımları, boş/negatif değerleri, küçük değer
kümelerini ve kodlama alternatiflerini gösterir; bunlar kolon anlamını kanıtlamaz.
table_review_candidates dış URL'leri ve henüz sınıflandırılmamış yol benzeri hücreleri
korur. Kontrol karakteri bulunan bir yolu sessizce düzeltmeyin; ham değeri inceleyin.
Bir dosyanın tabloda listelenmesi onun yüklendiğini kanıtlamaz; örneğin bakım/silme
listeleri de dosya adları içerebilir. Oyun içi kullanımı ayrıca doğrulayın.
tbl_text_matches yalnızca arama ipucudur. UI ağacı çizim sırası ve durum adaylarını
saklar; bütün alt görselleri aynı anda çizmek doğru değildir. font_index fontun tüm
kullanımlarını ve client dosyası adaylarını gösterir. Font adı eşitliği; gerçek yüz,
stil, glif kapsamı veya piksel metrikleri eşitliğini garanti etmez.

unity_ugui_geometry isteğe bağlı sabit piksel tarifidir: top-left anchor/pivot,
birim ölçek ve otomatik layout olmadan anchoredPosition=(relative_left,-relative_top).
Bu tarif orijinal çalışma anı anchor/ölçek bilgisi değildir. Reference resolution
bilinmiyor; root boyutundan tahmin etmeyin. PNG'ler üstten satır sıralıysa Unity UV
kökenini ayrıca doğrulayın. Stil bitleri, font yüksekliği ve renkler ham kaynaktan
korunur; TMP veya başka bir yazı çizicisinin aynı piksel sonucunu verdiğini varsaymayın.

asset_inventory hiçbir dosyayı gereksiz diye elemez. Referans bulunmaması dosyanın
kullanılmadığı anlamına gelmez. under_outputs_named_directory yalnızca yol bilgisidir;
mevcut PNG/JSON'un güncel veya kaynakla eşdeğer olduğunu kanıtlamaz. Uygunluk kararını
aktarım yapan AI verir; ham alanları ve bilinmeyen baytları silmeden kaynak referansı
ile gerekçelendirin. Kaynak binary dosyalar pakete kopyalanmamıştır; erişilebilir
client_root gereklidir. Başarılı yeniden oluşturma, alan anlamının veya oyun davranışının
tam bilindiğini kanıtlamaz. Bilinmeyen kontrol, stil, efekt baytları ve dosyalar raporda
kalır. Birebir iddiasından önce aynı durumdaki gerçek client ekran görüntülerini,
Unity sonucunu, fontları, alpha/blend/sampling/gamma ve etkileşimleri karşılaştırın.
"""
        (self.output / "AI_GUIDE.md").write_text(guide, encoding="utf-8")
        return report["summary"]
