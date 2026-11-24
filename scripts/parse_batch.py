#!/usr/bin/env python3
"""Run the configured primary, cross, and optional scholarly parsers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_runtime import inspect_runtime  # noqa: E402
from pipeline_common import (  # noqa: E402
    ensure_run_layout,
    read_jsonl,
    safe_relative_path,
    sha256_file,
    utc_now,
    write_json,
    write_jsonl,
)


def clean_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()


def jats_reference(nxml: Path, output_dir: Path) -> dict:
    root = ET.parse(nxml).getroot()
    title = clean_text(root.find(".//article-title"))
    abstract = clean_text(root.find(".//abstract"))
    sections = []
    for sec in root.findall(".//body//sec"):
        heading = clean_text(sec.find("title"))
        if heading:
            sections.append({"id": sec.get("id"), "title": heading})
    figures = []
    for fig in root.findall(".//fig"):
        figures.append({
            "id": fig.get("id"),
            "label": clean_text(fig.find("label")),
            "caption": clean_text(fig.find("caption")),
        })
    tables = []
    for table in root.findall(".//table-wrap"):
        tables.append({
            "id": table.get("id"),
            "label": clean_text(table.find("label")),
            "caption": clean_text(table.find("caption")),
        })
    references = root.findall(".//ref-list//ref")
    structure = {
        "title": title,
        "abstract_present": bool(abstract),
        "sections": sections,
        "figures": figures,
        "tables": tables,
        "reference_count": len(references),
        "source_sha256": sha256_file(nxml),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "structure.json", structure)
    lines = [f"# {title}", "", "## Abstract", "", abstract, "", "## Sections"]
    lines.extend(f"- {section['title']}" for section in sections)
    lines.extend(["", "## Figures"])
    lines.extend(f"- {item['label']}: {item['caption']}" for item in figures)
    lines.extend(["", "## Tables"])
    lines.extend(f"- {item['label']}: {item['caption']}" for item in tables)
    lines.extend(["", f"## References ({len(references)})", ""])
    (output_dir / "reference.md").write_text("\n".join(lines), encoding="utf-8")
    return structure


def output_artifacts(run_dir: Path, output_dir: Path) -> list[dict]:
    artifacts = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            artifacts.append({
                "path": safe_relative_path(run_dir, path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            })
    return artifacts


def run_command(run_dir: Path, paper_id: str, parser_name: str, command: list[str], output_dir: Path, timeout: int) -> dict:
    log_path = run_dir / "logs" / f"{paper_id}-{parser_name}.log"
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        log_path.write_text(
            "COMMAND\n" + json.dumps(command, ensure_ascii=False) + "\n\nSTDOUT\n" + completed.stdout + "\n\nSTDERR\n" + completed.stderr,
            encoding="utf-8",
        )
        artifacts = output_artifacts(run_dir, output_dir)
        success = completed.returncode == 0 and bool(artifacts)
        return {
            "status": "complete" if success else "failed",
            "exit_code": completed.returncode,
            "error": None if success else "parser returned no usable artifact" if completed.returncode == 0 else f"exit code {completed.returncode}",
            "artifacts": artifacts,
            "log_path": safe_relative_path(run_dir, log_path),
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(f"COMMAND\n{json.dumps(command)}\n\nTIMEOUT\n{exc}", encoding="utf-8")
        return {
            "status": "failed",
            "exit_code": None,
            "error": f"timeout after {timeout} seconds",
            "artifacts": output_artifacts(run_dir, output_dir),
            "log_path": safe_relative_path(run_dir, log_path),
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def parser_record(paper_id: str, parser_name: str, required: bool, runtime: dict, command: list[str] | None, result: dict) -> dict:
    return {
        "paper_id": paper_id,
        "parser": parser_name,
        "required": required,
        "runtime_path": runtime.get("path"),
        "runtime_source": runtime.get("source"),
        "command": command,
        "finished_at": utc_now(),
        **result,
    }


def write_jats_record(run_dir: Path, download: dict) -> dict:
    paper_id = download["paper_id"]
    output_dir = run_dir / "parsed" / paper_id / "jats-reference"
    nxml = run_dir / download["jats_path"]
    started = time.monotonic()
    try:
        structure = jats_reference(nxml, output_dir)
        return {
            "paper_id": paper_id,
            "parser": "jats-reference",
            "required": True,
            "runtime_path": sys.executable,
            "runtime_source": "stdlib",
            "command": [sys.executable, "xml.etree.ElementTree", str(nxml)],
            "status": "complete",
            "exit_code": 0,
            "error": None,
            "artifacts": output_artifacts(run_dir, output_dir),
            "structure": {
                "sections": len(structure["sections"]),
                "figures": len(structure["figures"]),
                "tables": len(structure["tables"]),
                "references": structure["reference_count"],
            },
            "duration_seconds": round(time.monotonic() - started, 3),
            "finished_at": utc_now(),
        }
    except Exception as exc:
        return {
            "paper_id": paper_id,
            "parser": "jats-reference",
            "required": True,
            "runtime_path": sys.executable,
            "runtime_source": "stdlib",
            "command": None,
            "status": "failed",
            "exit_code": 1,
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts": [],
            "duration_seconds": round(time.monotonic() - started, 3),
            "finished_at": utc_now(),
        }


def run_grobid(run_dir: Path, download: dict, runtime: dict, timeout: int) -> dict:
    paper_id = download["paper_id"]
    if not runtime["available"]:
        return parser_record(paper_id, "grobid", False, runtime, None, {
            "status": "skipped_unavailable",
            "exit_code": None,
            "error": runtime.get("detail", "GROBID service unavailable"),
            "artifacts": [],
            "duration_seconds": 0,
        })
    curl = subprocess.run(["where.exe", "curl.exe"], capture_output=True, text=True, check=False).stdout.splitlines()
    if not curl:
        return parser_record(paper_id, "grobid", False, runtime, None, {
            "status": "skipped_unavailable", "exit_code": None, "error": "curl.exe unavailable", "artifacts": [], "duration_seconds": 0,
        })
    output_dir = run_dir / "parsed" / paper_id / "grobid"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "article.tei.xml"
    endpoint = runtime["url"].rstrip("/") + "/api/processFulltextDocument"
    pdf = run_dir / download["pdf_path"]
    command = [curl[0], "--fail", "--silent", "--show-error", "-F", f"input=@{pdf}", endpoint, "-o", str(output)]
    return parser_record(paper_id, "grobid", False, runtime, command, run_command(run_dir, paper_id, "grobid", command, output_dir, timeout))


def build_tasks(run_dir: Path, corpus: dict, downloads: list[dict], runtime: dict, timeout: int) -> list[dict]:
    by_id = {row["pmcid"]: row for row in corpus.get("papers", [])}
    records = []
    for download in downloads:
        paper_id = download["paper_id"]
        if download.get("status") != "complete":
            continue
        profile = by_id.get(paper_id, {})
        pdf = run_dir / download["pdf_path"]
        nxml = run_dir / download["jats_path"]
        records.append(write_jats_record(run_dir, download))

        mineru = runtime["tools"]["mineru"]
        mineru_output = run_dir / "parsed" / paper_id / "mineru"
        if mineru["available"]:
            command = [mineru["path"], "-p", str(pdf), "-o", str(mineru_output), "-b", "pipeline", "-m", "txt"]
            result = run_command(run_dir, paper_id, "mineru", command, mineru_output, timeout)
        else:
            command = None
            result = {"status": "blocked", "exit_code": None, "error": "MinerU unavailable", "artifacts": [], "duration_seconds": 0}
        records.append(parser_record(paper_id, "mineru", True, mineru, command, result))

        for parser_name in profile.get("cross_parsers", []):
            tool = runtime["tools"][parser_name]
            output_dir = run_dir / "parsed" / paper_id / parser_name
            if not tool["available"]:
                records.append(parser_record(paper_id, parser_name, True, tool, None, {
                    "status": "blocked", "exit_code": None, "error": f"{parser_name} unavailable", "artifacts": [], "duration_seconds": 0,
                }))
                continue
            if parser_name == "markitdown":
                output_dir.mkdir(parents=True, exist_ok=True)
                command = [tool["path"], str(nxml), "-o", str(output_dir / "article.md"), "-x", ".xml"]
            elif parser_name == "docling":
                command = [tool["path"], "convert", str(pdf), "--to", "md", "--to", "json", "--output", str(output_dir), "--device", "cpu", "--no-ocr"]
            else:
                raise ValueError(f"unsupported cross parser: {parser_name}")
            result = run_command(run_dir, paper_id, parser_name, command, output_dir, timeout)
            records.append(parser_record(paper_id, parser_name, True, tool, command, result))
        records.append(run_grobid(run_dir, download, runtime["tools"]["grobid"], timeout))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=1800, help="Per-parser timeout in seconds")
    args = parser.parse_args()
    run_dir = ensure_run_layout(args.run)
    downloads = read_jsonl(run_dir / "manifests" / "downloads.jsonl")
    if not downloads:
        raise SystemExit("downloads.jsonl is empty; run fetch_open_access.py first")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    runtime = inspect_runtime()
    write_json(run_dir / "manifests" / "runtime.json", runtime)
    records = build_tasks(run_dir, corpus, downloads, runtime, args.timeout)
    write_jsonl(run_dir / "manifests" / "parsing.jsonl", records)
    counts = Counter(row["status"] for row in records)
    print(json.dumps(dict(sorted(counts.items())), indent=2))
    required_failures = [row for row in records if row["required"] and row["status"] != "complete"]
    return 0 if not required_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())

