"""UIF to JSON — native Python CLI by Zorlanis."""

from __future__ import annotations

import argparse
import codecs
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from uif_assets import AssetCatalog, walk_files
from uif_export import ANALYSIS_VERSION, SCHEMA_VERSION, analyze
from uif_audit import RUNTIME_ONLY
from uif_parser import UIFError
from uif_tbl_links import TableIndex
from uif_migration import MigrationAudit, decorate_uif

__version__ = ANALYSIS_VERSION
DEFAULT_CLIENT = Path(os.environ.get("KO_CLIENT_ROOT", r"C:\NTTGame\KnightOnlineEn"))


def write_json(path: Path, value: dict, compact: bool, overwrite: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        return False
    if overwrite:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".uif-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False, allow_nan=False,
                          indent=None if compact else 2, separators=(",", ":") if compact else None)
                stream.write("\n")
            os.replace(temporary, path)
            return True
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError:
        return False
    try:
        with stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False,
                      indent=None if compact else 2, separators=(",", ":") if compact else None)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return True


class Reporter:
    def __init__(self, json_mode: bool, quiet: bool):
        self.json_mode, self.quiet = json_mode, quiet
        self.active = 0

    def close(self):
        if self.active:
            print(flush=True)
            self.active = 0

    def event(self, kind: str, **fields):
        if self.quiet and kind not in {"summary", "error", "cancelled"}:
            return
        if self.json_mode:
            print(json.dumps({"schema_version": SCHEMA_VERSION, "event": kind, **fields}, ensure_ascii=False), flush=True)
        elif kind == "indexing":
            print(f"Client dosyaları eşleştiriliyor: {fields['client_root']}", flush=True)
        elif kind == "found":
            print(f"{fields['total']} UIF bulundu. JSON çıktıları: {fields['output']}", flush=True)
        elif kind == "tbl_found":
            self.close()
            print(f"{fields['total']} TBL bulundu. Tablo bağlantıları çözülüyor…", flush=True)
        elif kind == "audit_stage":
            self.close()
            print(f"Aktarım denetimi: {fields['stage']} · {fields['total']} dosya", flush=True)
        elif kind == "audit_progress":
            self.close()
            print(f"{fields['stage']}: {fields['processed']}/{fields['total']}", flush=True)
        elif kind in {"file", "tbl_file"}:
            done, total = fields["processed"], fields["total"]
            width = 18
            bar = "█" * (done * width // total) + "░" * (width - done * width // total)
            line = (f"[{bar}] {done}/{total} · Kalan {total - done} · Hata {fields['failed']}"
                    f" · {fields['source']}")
            line = line.replace("\x1b", "?").replace("\r", " ").replace("\n", " ")
            if sys.stdout.isatty():
                line = line[:max(40, os.get_terminal_size().columns - 1)]
                sys.stdout.write("\r" + line + " " * max(0, self.active - len(line)))
                sys.stdout.flush()
                self.active = len(line)
            else:
                print(line, flush=True)
        elif kind == "summary":
            self.close()
            print(f"\nTamamlandı: {fields['parsed']} UIF çözüldü, {fields['failed']} hata."
                  f" {fields['nodes']} öğe, {fields['text_elements']} yazı, {fields['unique_textures']} doku referansı.")
            print(f"Eşleşmeyen doku referansları: {fields['unresolved_textures']}. Süre: {fields['elapsed_seconds']:.1f} sn.")
            print(f"Çıktı: {fields['output']}")
            if fields.get("tbl_enabled"):
                print(f"TBL: {fields['tbl_parsed']}/{fields['tbl_total']} çözüldü · Hata {fields['tbl_failed']}"
                      f" · UIF bağlantısı {fields['tbl_uif_references']}"
                      f" · Eşleşmeyen {fields['tbl_unresolved_uif_references']}")
            if fields.get("migration_audit"):
                print(f"Efekt: {fields['effect_parsed']}/{fields['effect_total']} · Hata {fields['effect_failed']}"
                      f" · Client fontu bulunamayan aile {fields['font_families_without_client_file']}")
                print("Unity aktarım raporu: migration_report.json · Birebir görüntü doğrulaması henüz yapılmadı.")
        elif kind == "error":
            self.close()
            print(f"HATA: {fields.get('source', '')} {fields['error']}", file=sys.stderr, flush=True)
        elif kind == "cancelled":
            self.close()
            print("Durduruldu. Tamamlanan JSON dosyaları korundu.", file=sys.stderr)


def export_batch(source: Path, client_root: Path, output: Path, *, encoding: str = "auto",
                 compact: bool = False, overwrite: bool = False, reporter: Reporter | None = None,
                 tables: bool = True, tbl_encoding: str = "auto", effects: bool = True) -> dict:
    started = time.monotonic()
    reporter = reporter or Reporter(False, False)
    source, client_root = source.resolve(strict=True), client_root.resolve(strict=True)
    output = output.resolve()
    if output == source or output == client_root:
        raise ValueError("çıktı klasörü kaynak/client kökü ile aynı olamaz")
    if output.exists() and not output.is_dir():
        raise NotADirectoryError(f"çıktı yolu klasör olmalı: {output}")
    if source.is_file():
        files = [source]
    else:
        files = sorted(path for path in walk_files(source, output) if path.suffix.casefold() == ".uif")
    reporter.event("indexing", client_root=str(client_root))
    catalog = AssetCatalog(client_root, output)
    table_index = TableIndex(catalog, output, write_json, reporter, ANALYSIS_VERSION, tbl_encoding, compact, overwrite) if tables else None
    if table_index:
        table_index.scan()
    migration = MigrationAudit(catalog, output, write_json, reporter, ANALYSIS_VERSION, compact, effects)
    reporter.event("found", total=len(files), output=str(output), client_files=catalog.file_count)
    records, texts = [], []
    assets = {}
    other_assets, coverage_groups = {}, {}
    encoding_counts = Counter()
    verified_files, verified_bytes = 0, 0
    totals = Counter(parsed=0, written=0, skipped=0, failed=0, nodes=0, text_elements=0, tooltip_elements=0)
    type_counts, warning_counts = Counter(), Counter()
    for index, path in enumerate(files, 1):
        try:
            relative = path.relative_to(client_root)
        except ValueError:
            relative = Path(path.name) if source.is_file() else path.relative_to(source)
        # Keep document names separate from aggregate index names.
        target = output / "uif" / relative.with_suffix(".json")
        record = {"source": relative.as_posix(), "output": target.relative_to(output).as_posix()}
        try:
            document = analyze(path, catalog, encoding)
            document["table_links"] = table_index.links_for(document["source"]["relative_path"]) if table_index else []
            document["format"]["table_analysis"] = "enabled" if table_index else "disabled"
            decorate_uif(document)
            if target.exists() and not overwrite:
                previous = json.loads(target.read_text(encoding="utf-8"))
                if (not isinstance(previous, dict) or previous.get("schema_version") != SCHEMA_VERSION
                        or previous.get("analysis_version") != ANALYSIS_VERSION
                        or previous.get("format", {}).get("string_encoding") != encoding
                        or previous.get("format", {}).get("table_analysis") != document["format"]["table_analysis"]
                        or previous.get("source") != document["source"]
                        or previous.get("textures") != document["textures"]
                        or previous.get("resources") != document["resources"]
                        or previous.get("table_links") != document["table_links"]):
                    raise ValueError("mevcut JSON kaynak/sürüm/kodlama/kaynak eşleşmeleriyle güncel değil; --overwrite kullan")
            written = write_json(target, document, compact, overwrite)
            migration.add_uif(document, record["output"])
            record.update(status="written" if written else "skipped", source_sha256=document["source"]["sha256"],
                          **document["summary"])
            if table_index:
                table_index.add_uif(document, record["output"])
            totals["parsed"] += 1
            totals["written" if written else "skipped"] += 1
            totals["nodes"] += document["summary"]["nodes"]
            totals["text_elements"] += document["summary"]["text_elements"]
            totals["tooltip_elements"] += document["summary"]["tooltip_elements"]
            type_counts.update(document["summary"]["types"])
            warning_counts.update(document["summary"]["warning_counts"])
            audit = document["coverage"]
            verified_files += 1
            verified_bytes += audit["verified_bytes"]
            encoding_counts.update(audit["string_encoding_counts"])
            for item in audit["uninterpreted_fields"]:
                key = (item["field"], item["type_id"], json.dumps(item["value"], sort_keys=True))
                group = coverage_groups.setdefault(key, {field: value for field, value in item.items() if field != "nodes"})
                group.setdefault("used_by", []).append({"uif": relative.as_posix(), "json": record["output"], "nodes": item["nodes"]})
            for resource in document["resources"]:
                key = (resource["kind"], resource["asset_id"])
                asset = other_assets.setdefault(key, {field: value for field, value in resource.items()
                                                     if field not in {"node_uid", "role", "reference"}})
                asset.setdefault("used_by", []).append({"uif": relative.as_posix(), "json": record["output"],
                                                       "node_uid": resource["node_uid"], "role": resource["role"],
                                                       "reference": resource["reference"]})
            for asset in document["textures"]:
                key = asset["asset_id"]
                if key not in assets:
                    assets[key] = {field: value for field, value in asset.items()
                                   if field not in {"reference", "references", "used_by_nodes"}}
                    assets[key].update(references=set(), used_by=[])
                assets[key]["references"].update(asset["references"])
                assets[key]["used_by"].append({"uif": relative.as_posix(), "json": record["output"],
                                                "nodes": asset["used_by_nodes"]})
            for entry in document["texts"]:
                texts.append({"uif": relative.as_posix(), "json": record["output"],
                              "kind": "text", "node_uid": entry["node_uid"], "id": entry["id"], "text": entry["text"]})
            for entry in document["tooltips"]:
                texts.append({"uif": relative.as_posix(), "json": record["output"],
                              "kind": "tooltip", "node_uid": entry["node_uid"], "id": entry["id"], "text": entry["text"]})
        except (UIFError, OSError, ValueError, RecursionError) as error:
            totals["failed"] += 1
            record.update(status="error", error=str(error))
            if isinstance(error, UIFError):
                record.update(error_offset=error.offset, error_field=error.field)
            reporter.event("error", **record)
        records.append(record)
        reporter.event("file", **record, processed=index, total=len(files), failed=totals["failed"])
    asset_list = []
    for _, asset in sorted(assets.items()):
        asset["references"] = sorted(asset["references"])
        asset_list.append(asset)
    unresolved = [asset for asset in asset_list if asset["status"] != "found"]
    other_list = sorted(other_assets.values(), key=lambda asset: (asset["kind"], asset["asset_id"] or ""))
    unresolved_other = [asset for asset in other_list if asset["status"] in {"missing", "ambiguous"}]
    summary = {"total": len(files), **dict(totals), "unique_textures": len(asset_list),
               "tbl_enabled": tables, **(table_index.summary if table_index else {}),
               "unresolved_textures": len(unresolved), "types": dict(sorted(type_counts.items())),
               "unresolved_other_resources": len(unresolved_other), "byte_verified_files": verified_files,
               "warning_counts": dict(sorted(warning_counts.items())),
               "elapsed_seconds": round(time.monotonic() - started, 3), "output": str(output)}
    shared = {"schema_version": SCHEMA_VERSION, "analysis_version": ANALYSIS_VERSION, "client_root": str(client_root)}
    # Aggregate indexes are refreshed only after the batch has completed.
    write_json(output / "texture_index.json", {**shared, "assets": asset_list}, compact, True)
    write_json(output / "unresolved_textures.json", {**shared, "assets": unresolved}, compact, True)
    write_json(output / "text_index.json", {**shared, "texts": texts}, compact, True)
    write_json(output / "resource_index.json", {**shared, "textures": asset_list,
                                               "other_resources": other_list}, compact, True)
    write_json(output / "coverage_report.json", {
        **shared, "verified_files": verified_files, "verified_bytes": verified_bytes,
        "byte_reconstruction": "all_successful_files_exact_match" if verified_files else "no_files_verified",
        "failed_files": totals["failed"], "uninterpreted_fields": list(coverage_groups.values()),
        "string_encoding_counts": dict(sorted(encoding_counts.items())),
        "runtime_only_not_serialized": RUNTIME_ONLY,
        "scope": "Byte coverage is verified; opaque field meanings and runtime behavior are not fully known.",
    }, compact, True)
    if table_index:
        table_index.finish()
    migration_summary = migration.finish(summary, table_index)
    summary.update(migration_audit=True, **migration_summary)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_json(output / "manifest.json", {**shared, "summary": summary, "files": records}, compact, True)
    reporter.event("summary", **summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="uif2json", description="Knight Online UIF → JSON | Zorlanis")
    parser.add_argument("input", nargs="?", type=Path, help="UIF dosyası veya taranacak klasör")
    parser.add_argument("-d", "--directory", nargs="?", const=DEFAULT_CLIENT, type=Path, metavar="DIR")
    parser.add_argument("--client-root", type=Path, default=DEFAULT_CLIENT, help="DXT ve diğer kaynakların bulunduğu client kökü")
    parser.add_argument("-o", "--output", type=Path, default=Path.cwd() / "outputs", help="JSON çıktı klasörü")
    parser.add_argument("--encoding", default="auto", help="metin kodlaması: auto, cp949, cp1254, utf-8…")
    parser.add_argument("--tbl-encoding", default="auto", help="TBL metin kodlaması; auto: ASCII/UTF-8 ve Korece karakter kanıtıyla CP949, ardından diğer adaylar")
    parser.add_argument("--no-tbl", action="store_true", help="TBL çözümleme ve bağlantı taramasını kapat")
    parser.add_argument("--no-effects", action="store_true", help="FXB parça çözümlemesini kapat; dosyalar envanterde korunur")
    parser.add_argument("--compact", action="store_true", help="JSON dosyalarında boşlukları azalt")
    parser.add_argument("--overwrite", action="store_true", help="mevcut UIF/TBL JSON dosyalarını güncelle")
    parser.add_argument("--strict-assets", action="store_true", help="eşleşmeyen UIF kaynağı veya TBL → UIF referansı varsa hata kodu döndür")
    parser.add_argument("--non-interactive", action="store_true", help="soru sorma; kaynak verilmezse client kökünü kullan")
    parser.add_argument("--json", action="store_true", help="terminal olaylarını NDJSON olarak yaz")
    parser.add_argument("--quiet", action="store_true", help="yalnızca sonuç ve hataları yaz")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__} · Zorlanis")
    args = parser.parse_args(argv)
    if args.input is not None and args.directory is not None:
        parser.error("input ile --directory birlikte kullanılamaz")
    for selected_encoding in (args.encoding, args.tbl_encoding):
        if selected_encoding == "auto":
            continue
        try:
            codecs.lookup(selected_encoding)
            b"".decode(selected_encoding)
        except (LookupError, TypeError):
            parser.error("bilinmeyen metin kodlaması")
    reporter = Reporter(args.json, args.quiet)
    try:
        source = args.directory if args.directory is not None else args.input
        if source is None:
            if args.non_interactive or args.json or not sys.stdin.isatty():
                source = args.client_root
            else:
                print(f"\n  UIF → JSON · Zorlanis\n  Varsayılan: {args.client_root}\n")
                value = input("  UIF klasörü veya dosyası (Enter: varsayılan) > ").strip().strip('"\'')
                source = Path(os.path.expandvars(value)).expanduser() if value else args.client_root
        result = export_batch(source, args.client_root, args.output, encoding=args.encoding,
                              compact=args.compact, overwrite=args.overwrite, reporter=reporter,
                              tables=not args.no_tbl, tbl_encoding=args.tbl_encoding, effects=not args.no_effects)
        return 1 if (result["failed"] or result.get("tbl_failed", 0) or result.get("effect_failed", 0) or
                     (args.strict_assets and (result["unresolved_textures"] or result["unresolved_other_resources"]
                                             or result.get("tbl_unresolved_uif_references", 0)))) else 0
    except KeyboardInterrupt:
        reporter.event("cancelled")
        return 130
    except (OSError, ValueError, EOFError) as error:
        reporter.event("error", error=str(error))
        return 1
    finally:
        reporter.close()


if __name__ == "__main__":
    raise SystemExit(main())
