#!/usr/bin/env python3
"""Shared, dependency-free helpers for the evidence pipeline scripts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


STATUSES = {"complete", "partial", "blocked", "failed", "needs-review", "skipped_unavailable"}
RUN_DIRS = (
    "raw",
    "parsed",
    "curated",
    "manifests",
    "release",
    "logs",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    text = re.sub(r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", "", text)
    text = text.strip(" \t\r\n.;,()[]{}")
    return text or None


def normalize_pmcid(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return f"PMC{digits}" if digits else None


def normalize_pmid(value: str | int | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def canonical_title(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def looks_like_pdf(path: Path) -> bool:
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 8:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def safe_relative_path(root: Path, path: Path) -> str:
    root_resolved = Path(root).resolve()
    path_resolved = Path(path).resolve()
    try:
        relative = path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes run directory: {path}") from exc
    return relative.as_posix()


def ensure_run_layout(run_dir: Path) -> Path:
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    for relative in RUN_DIRS:
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    for relative in ("curated/evidence.jsonl", "curated/review_queue.jsonl"):
        target = run_dir / relative
        if not target.exists():
            target.write_text("", encoding="utf-8")
    return run_dir


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).is_file():
        return []
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    target.write_text(content, encoding="utf-8")


def write_json(path: Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

