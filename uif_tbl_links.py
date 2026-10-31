"""Trace table string cells to UIF/resources; keep text matches as candidates."""

from collections import defaultdict
from pathlib import PurePosixPath
import re

from uif_tbl import TBLError, load_table, string_cells
from uif_tbl_audit import audit_table, unclassified_cell

REFERENCE = re.compile(r"\.([a-z][a-z0-9_]{0,15})$", re.IGNORECASE)
STANDARD_EXTENSIONS = {"uif", "dxt", "tga", "dds", "png", "bmp", "jpg", "jpeg", "wav", "ogg", "mp3", "swf", "tbl", "fxb", "ttf", "otf", "ttc"}
IMAGE_EXTENSIONS = {"dxt", "tga", "dds", "png", "bmp", "jpg", "jpeg"}


class TableIndex:
    def __init__(self, catalog, output, writer, reporter, version, encoding="auto", compact=False, overwrite=False):
        self.catalog, self.output, self.writer, self.reporter = catalog, output, writer, reporter
        self.encoding, self.compact, self.overwrite = encoding, compact, overwrite
        self.shared = {"schema_version": 1, "analysis_version": version, "client_root": str(catalog.root)}
        self.records, self.references = [], []
        self.profiles, self.cell_reviews = [], []
        self.file_extensions = {path.suffix.casefold().lstrip(".") for matches in catalog.paths.values() for path in matches}
        self.inbound, self.text_cells = defaultdict(list), defaultdict(list)
        self.uif_texts = defaultdict(list)
        self.exported_uifs = {}
        self.summary = {"tbl_total": 0, "tbl_parsed": 0, "tbl_written": 0, "tbl_skipped": 0,
                        "tbl_failed": 0, "tbl_rows": 0, "tbl_uif_references": 0,
                        "tbl_unresolved_uif_references": 0}
        self.summary.update(tbl_columns=0, tbl_ambiguous_encoding_cells=0, tbl_review_candidates=0)

    def scan(self):
        import json

        files = sorted(path for matches in self.catalog.paths.values() for path in matches
                       if path.suffix.casefold() == ".tbl")
        self.summary["tbl_total"] = len(files)
        self.reporter.event("tbl_found", total=len(files))
        for index, path in enumerate(files, 1):
            relative = path.relative_to(self.catalog.root).as_posix()
            target = self.output / "tbl" / PurePosixPath(relative).with_suffix(".json")
            record = {"source": relative, "output": target.relative_to(self.output).as_posix()}
            try:
                table = load_table(path, self.catalog.root, self.encoding)
                profile = audit_table(table)
                profile["table_json"] = record["output"]
                source_cells, references, reviews = [], [], []
                for cell in string_cells(table):
                    source = {"table": relative, "table_json": record["output"],
                              **{key: value for key, value in cell.items() if key != "text"}}
                    text = cell["text"]
                    if len(text.strip()) >= 4:
                        source_cells.append((text, source))
                    candidate = text.rstrip("\0").strip()
                    match = REFERENCE.search(candidate)
                    extension = match.group(1).lower() if match else ""
                    is_reference = (bool(match) and len(candidate) <= 1024 and not any(ord(c) < 32 for c in candidate)
                                    and "://" not in candidate and (extension in self.file_extensions
                                                                 or extension in STANDARD_EXTENSIONS or extension.startswith("n3")))
                    review = unclassified_cell(cell, self.catalog, relative, record["output"], is_reference)
                    if review:
                        reviews.append(review)
                    if not is_reference:
                        continue
                    kind = ("uif" if extension == "uif" else "table" if extension == "tbl" else
                            "effect" if extension == "fxb" else "model" if extension.startswith("n3") else
                            "font" if extension in {"ttf", "otf", "ttc"} else
                            "flash" if extension == "swf" else "sound" if extension in {"wav", "ogg", "mp3"} else
                            "texture" if extension in IMAGE_EXTENSIONS else "asset")
                    resource = self.catalog.resolve(candidate, kind)
                    references.append({**source, "reference": text, "resource": resource,
                                       "evidence": "file_path_in_typed_string_cell", "usage_semantics": "not_inferred"})
                table.update(self.shared, references=references)
                if target.exists() and not self.overwrite:
                    previous = json.loads(target.read_text(encoding="utf-8"))
                    if (not isinstance(previous, dict) or previous.get("analysis_version") != self.shared["analysis_version"]
                            or previous.get("source") != table["source"] or previous.get("format") != table["format"]
                            or previous.get("references") != table["references"]):
                        raise TBLError("existing TBL JSON is stale; use --overwrite")
                written = self.writer(target, table, self.compact, self.overwrite)
                self.summary["tbl_parsed"] += 1
                self.summary["tbl_written" if written else "tbl_skipped"] += 1
                self.summary["tbl_rows"] += len(table["rows"])
                self.summary["tbl_columns"] += len(table["columns"])
                self.summary["tbl_ambiguous_encoding_cells"] += profile["ambiguous_encoding_cells"]
                self.summary["tbl_review_candidates"] += len(reviews)
                self.profiles.append(profile)
                self.cell_reviews.extend(reviews)
                record.update(status="written" if written else "skipped", rows=len(table["rows"]),
                              columns=len(table["columns"]), source_sha256=table["source"]["sha256"],
                              plaintext_sha256=table["integrity"]["plaintext_sha256"],
                              crypto=table["format"]["scheme"], byte_reconstruction="exact_match",
                              references=len(references))
                self.references.extend(references)
                for text, source in source_cells:
                    self.text_cells[text].append(source)
                for reference in references:
                    resource = reference["resource"]
                    if resource["kind"] == "uif":
                        self.summary["tbl_uif_references"] += 1
                        if resource["status"] != "found":
                            self.summary["tbl_unresolved_uif_references"] += 1
                        else:
                            self.inbound[resource["asset_id"]].append(reference)
            except (ValueError, OSError) as error:
                self.summary["tbl_failed"] += 1
                record.update(status="error", error=str(error))
                self.reporter.event("error", stage="tbl", **record)
            self.records.append(record)
            self.reporter.event("tbl_file", **record, processed=index, total=len(files), failed=self.summary["tbl_failed"])
        self.reporter.close()

    def links_for(self, relative):
        return self.inbound.get(relative.casefold(), [])

    def add_uif(self, document, output):
        relative = document["source"]["relative_path"]
        self.exported_uifs[relative.casefold()] = output
        for kind, entries in (("text", document["texts"]), ("tooltip", document["tooltips"])):
            for entry in entries:
                if entry["text"] in self.text_cells:
                    self.uif_texts[entry["text"]].append({"uif": relative, "uif_json": output, "kind": kind,
                                                        "node_uid": entry["node_uid"], "id": entry["id"]})

    def finish(self):
        direct, others = [], []
        for reference in self.references:
            if reference["resource"]["kind"] == "uif":
                direct.append({**reference, "uif_json": self.exported_uifs.get(reference["resource"]["asset_id"]),
                               "uif_exported_in_this_run": reference["resource"]["asset_id"] in self.exported_uifs})
            else:
                others.append(reference)
        candidates = [{"text": text, "table_cells": self.text_cells[text], "uif_elements": entries,
                       "evidence": "identical_decoded_text_only", "is_runtime_binding": False}
                      for text, entries in sorted(self.uif_texts.items())]
        self.writer(self.output / "table_index.json", {**self.shared, "summary": self.summary,
                                                      "files": self.records}, self.compact, True)
        self.writer(self.output / "tbl_uif_links.json", {
            **self.shared, "direct_uif_links": direct, "other_file_references": others,
            "scope": "Typed string-cell paths only. Numeric IDs are not joined to UIF node IDs.",
            "failed_tables": [record for record in self.records if record["status"] == "error"],
        }, self.compact, True)
        self.writer(self.output / "tbl_text_matches.json", {
            **self.shared, "matches": candidates,
            "scope": "Exact decoded text equality is a search clue, not proof of a runtime binding.",
            "table_encoding": self.encoding,
        }, self.compact, True)
        self.writer(self.output / "table_schema_report.json", {
            **self.shared, "summary": self.summary, "tables": self.profiles,
            "semantics": "Column names, units, bitfields and numeric foreign keys remain unverified.",
            "note": "Small observed domains are not verified enum definitions; equal IDs are not automatically joined.",
        }, self.compact, True)
        self.writer(self.output / "table_review_candidates.json", {
            **self.shared, "candidates": self.cell_reviews,
            "scope": "External URIs and unclassified path-shaped strings; not confirmed dependencies and never fetched.",
        }, self.compact, True)
