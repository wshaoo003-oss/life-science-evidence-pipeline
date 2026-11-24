#!/usr/bin/env python3
"""Validate run integrity, evidence records, status counts, and release artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import (  # noqa: E402
    STATUSES,
    canonical_title,
    ensure_run_layout,
    read_jsonl,
    safe_relative_path,
    sha256_file,
    utc_now,
    write_json,
)


REQUIRED_EVIDENCE_FIELDS = {
    "evidence_id", "paper_id", "evidence_type", "claim", "species", "model",
    "tissue_or_cell", "life_stage_or_age", "sex", "intervention_or_exposure",
    "assay", "outcome", "value", "unit", "direction", "source_locator",
    "source_checksum", "parser", "review_status",
}
REVIEW_STATUSES = {"candidate", "verified", "rejected", "needs-review"}


def element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()


def label_number(value: str | None) -> str | None:
    match = re.search(r"\d+", value or "")
    return match.group(0) if match else None


def validate_source_locator(nxml: Path, locator: dict) -> list[str]:
    errors = []
    try:
        root = ET.parse(nxml).getroot()
    except (OSError, ET.ParseError) as exc:
        return [f"cannot parse source document: {exc}"]
    wanted_section = canonical_title(locator.get("section"))
    matching_sections = [
        sec for sec in root.findall(".//sec")
        if canonical_title(element_text(sec.find("title"))) == wanted_section
    ]
    if not matching_sections:
        errors.append(f"section not found: {locator.get('section')}")
    elif "paragraph" in locator:
        paragraph = locator.get("paragraph")
        paragraphs = matching_sections[0].findall("p")
        if not isinstance(paragraph, int) or paragraph < 1 or paragraph > len(paragraphs):
            errors.append(f"paragraph out of range: {paragraph}")
    if locator.get("figure"):
        wanted = label_number(locator["figure"])
        available = {label_number(element_text(label)) for label in root.findall(".//fig/label")}
        if not wanted or wanted not in available:
            errors.append(f"figure not found: {locator['figure']}")
    if locator.get("table"):
        wanted = label_number(locator["table"])
        available = {label_number(element_text(label)) for label in root.findall(".//table-wrap/label")}
        if not wanted or wanted not in available:
            errors.append(f"table not found: {locator['table']}")
    return errors


def compute_label_coverage(nxml: Path, markdown_files: list[Path]) -> dict:
    root = ET.parse(nxml).getroot()
    labels = []
    labels.extend(("figure", element_text(label), label_number(element_text(label))) for label in root.findall(".//fig/label"))
    labels.extend(("table", element_text(label), label_number(element_text(label))) for label in root.findall(".//table-wrap/label"))
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in markdown_files if path.is_file())
    matched_labels = []
    for kind, label, number in labels:
        prefix = r"fig(?:ure)?" if kind == "figure" else "table"
        if number and re.search(rf"{prefix}\s*\.?\s*{re.escape(number)}\b", text, re.IGNORECASE):
            matched_labels.append(label)
    total = len(labels)
    matched = len(matched_labels)
    return {
        "matched": matched,
        "total": total,
        "rate": round(matched / total, 6) if total else 1.0,
        "matched_labels": matched_labels,
        "missing_labels": [label for _, label, _ in labels if label not in matched_labels],
    }


def validate_evidence_record(row: dict) -> list[str]:
    errors = []
    missing = sorted(REQUIRED_EVIDENCE_FIELDS - set(row))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if not str(row.get("claim", "")).strip():
        errors.append("claim is empty")
    if row.get("evidence_type") not in {"measurement", "author_claim"}:
        errors.append("invalid evidence_type")
    if row.get("review_status") not in REVIEW_STATUSES:
        errors.append("invalid review_status")
    checksum = str(row.get("source_checksum", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        errors.append("source_checksum must be a lowercase SHA-256")
    locator = row.get("source_locator")
    if not isinstance(locator, dict):
        errors.append("source_locator must be an object")
    else:
        if not locator.get("document"):
            errors.append("source_locator.document is required")
        if not locator.get("section"):
            errors.append("source_locator.section is required")
        if not any(key in locator for key in ("paragraph", "page", "figure", "table", "supplement")):
            errors.append("source_locator needs paragraph, page, figure, table, or supplement")
    if row.get("value") is not None:
        if row.get("unit") in (None, ""):
            errors.append("numeric evidence requires unit")
        if row.get("direction") in (None, ""):
            errors.append("numeric evidence requires direction")
    return errors


def reconcile_status_counts(rows: list[dict], declared: dict) -> dict:
    actual = Counter(row.get("status") for row in rows)
    normalized = {status: actual.get(status, 0) for status in STATUSES}
    expected = {status: int(declared.get(status, 0)) for status in STATUSES}
    return {"actual": normalized, "declared": expected, "consistent": normalized == expected}


def finalize_protocol(protocol: dict, summary: dict) -> dict:
    updated = dict(protocol)
    updated["status"] = summary["overall_status"]
    updated["completed_at"] = summary["generated_at"]
    updated["release_manifest"] = "release/release_manifest.json"
    updated["validation_report"] = "release/validation_report.md"
    return updated


def validate_downloads(run_dir: Path, downloads: list[dict]) -> list[str]:
    errors = []
    for row in downloads:
        if row.get("status") != "complete":
            errors.append(f"download failed for {row.get('paper_id')}: {row.get('error')}")
            continue
        for kind in ("pdf", "jats"):
            relative = row.get(f"{kind}_path")
            declared = row.get(f"{kind}_sha256")
            path = run_dir / relative if relative else None
            if path is None or not path.is_file():
                errors.append(f"missing {kind} for {row.get('paper_id')}")
            elif sha256_file(path) != declared:
                errors.append(f"checksum mismatch for {row.get('paper_id')} {kind}")
    return errors


def paper_statuses(papers: list[dict], downloads: list[dict], parsing: list[dict]) -> list[dict]:
    download_by_id = {row["paper_id"]: row for row in downloads}
    parser_by_id: dict[str, list[dict]] = {}
    for row in parsing:
        parser_by_id.setdefault(row["paper_id"], []).append(row)
    results = []
    for paper in papers:
        paper_id = paper["pmcid"]
        download = download_by_id.get(paper_id)
        required = [row for row in parser_by_id.get(paper_id, []) if row.get("required")]
        if not download or download.get("status") != "complete":
            status = "failed"
        elif any(row.get("status") in {"failed", "blocked"} for row in required):
            status = "partial"
        elif not required or any(row.get("status") != "complete" for row in required):
            status = "blocked"
        else:
            status = "complete"
        results.append({"paper_id": paper_id, "status": status})
    return results


def render_report(summary: dict, issues: list[str], parser_counts: dict, evidence_by_paper: dict) -> str:
    lines = [
        "# Life Science Evidence Pipeline Validation",
        "",
        f"- Generated: {summary['generated_at']}",
        f"- Overall status: **{summary['overall_status']}**",
        f"- Papers: {summary['papers']['actual']} / {summary['papers']['expected']}",
        f"- Evidence: {summary['evidence']['actual']} / {summary['evidence']['expected']}",
        f"- Verified evidence: {summary['evidence']['verified']}",
        f"- Review queue: {summary['review_queue']}",
        "",
        "## Paper Status",
        "",
    ]
    for status in ("complete", "partial", "blocked", "failed", "needs-review"):
        lines.append(f"- {status}: {summary['paper_status_counts'].get(status, 0)}")
    lines.extend(["", "## Parser Status", ""])
    for status in ("complete", "partial", "blocked", "failed", "needs-review", "skipped_unavailable"):
        lines.append(f"- {status}: {parser_counts.get(status, 0)}")
    lines.extend(["", "## Evidence Per Paper", ""])
    for paper_id, count in sorted(evidence_by_paper.items()):
        lines.append(f"- {paper_id}: {count}")
    lines.extend(["", "## Quality Gates", ""])
    for name, passed in summary["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: {name}")
    structure = summary.get("structure", {})
    lines.extend([
        "",
        "## Structure Coverage",
        "",
        f"- Figure/table labels in MinerU: {structure.get('matched_labels', 0)} / {structure.get('total_labels', 0)} ({structure.get('coverage_rate', 0):.1%})",
        f"- Evidence figure/table locators resolved: {structure.get('evidence_locators_resolved', 0)} / {structure.get('evidence_locators_total', 0)}",
    ])
    for paper_id, coverage in sorted(structure.get("by_paper", {}).items()):
        lines.append(f"- {paper_id}: {coverage['matched']} / {coverage['total']} ({coverage['rate']:.1%})")
    lines.extend(["", "## Degradation", ""])
    degradation = summary.get("degradation", [])
    lines.extend(f"- {item}" for item in degradation or ["None"])
    lines.extend(["", "## Issues", ""])
    lines.extend(f"- {issue}" for issue in issues or ["None"])
    lines.append("")
    return "\n".join(lines)


def validate_run(run_dir: Path, expected_papers: int, expected_evidence: int) -> tuple[dict, list[str]]:
    papers = read_jsonl(run_dir / "manifests" / "papers.jsonl")
    downloads = read_jsonl(run_dir / "manifests" / "downloads.jsonl")
    parsing = read_jsonl(run_dir / "manifests" / "parsing.jsonl")
    evidence = read_jsonl(run_dir / "curated" / "evidence.jsonl")
    review_queue = read_jsonl(run_dir / "curated" / "review_queue.jsonl")
    issues = validate_downloads(run_dir, downloads)

    valid_source_hashes = {
        value for row in downloads for value in (row.get("pdf_sha256"), row.get("jats_sha256")) if value
    }
    seen_ids = set()
    evidence_by_paper = Counter()
    download_by_id = {row.get("paper_id"): row for row in downloads}
    evidence_locator_total = 0
    evidence_locator_resolved = 0
    for index, row in enumerate(evidence, 1):
        for error in validate_evidence_record(row):
            issues.append(f"evidence line {index}: {error}")
        if row.get("evidence_id") in seen_ids:
            issues.append(f"duplicate evidence_id: {row.get('evidence_id')}")
        seen_ids.add(row.get("evidence_id"))
        evidence_by_paper[row.get("paper_id")] += 1
        if row.get("source_checksum") not in valid_source_hashes:
            issues.append(f"evidence {row.get('evidence_id')} checksum is not a downloaded source")
        download = download_by_id.get(row.get("paper_id"), {})
        nxml = run_dir / download["jats_path"] if download.get("jats_path") else None
        locator_errors = validate_source_locator(nxml, row.get("source_locator", {})) if nxml else ["JATS source missing"]
        for error in locator_errors:
            issues.append(f"evidence {row.get('evidence_id')} locator: {error}")
        if row.get("source_locator", {}).get("figure") or row.get("source_locator", {}).get("table"):
            evidence_locator_total += 1
            if not locator_errors:
                evidence_locator_resolved += 1

    coverage_by_paper = {}
    for paper in papers:
        paper_id = paper.get("pmcid")
        download = download_by_id.get(paper_id, {})
        nxml = run_dir / download["jats_path"] if download.get("jats_path") else None
        markdown_files = list((run_dir / "parsed" / paper_id / "mineru").rglob("*.md"))
        if nxml and nxml.is_file():
            coverage_by_paper[paper_id] = compute_label_coverage(nxml, markdown_files)
    total_labels = sum(row["total"] for row in coverage_by_paper.values())
    matched_labels = sum(row["matched"] for row in coverage_by_paper.values())
    coverage_rate = matched_labels / total_labels if total_labels else 1.0

    paper_rows = paper_statuses(papers, downloads, parsing)
    paper_counts = Counter(row["status"] for row in paper_rows)
    parser_counts = Counter(row.get("status") for row in parsing)
    verified = sum(row.get("review_status") == "verified" for row in evidence)
    gates = {
        "paper identity count": len(papers) == expected_papers and len({row.get("pmcid") for row in papers}) == expected_papers,
        "legal downloads and checksums": len(downloads) == expected_papers and not validate_downloads(run_dir, downloads),
        "required parsers": bool(parsing) and all(row.get("status") == "complete" for row in parsing if row.get("required")),
        "evidence count": len(evidence) == expected_evidence,
        "evidence source locators": len(evidence) == expected_evidence and all(not validate_evidence_record(row) for row in evidence),
        "evidence locators resolve in JATS": not any(" locator: " in issue for issue in issues),
        "figure/table label coverage >= 80%": coverage_rate >= 0.8,
        "evidence figure/table locators resolve": evidence_locator_resolved == evidence_locator_total,
        "all evidence verified": verified == expected_evidence,
        "five evidence per paper": len(evidence_by_paper) == expected_papers and all(value == 5 for value in evidence_by_paper.values()),
        "review queue resolved": len(review_queue) == 0,
    }
    if len(papers) != expected_papers:
        issues.append(f"expected {expected_papers} papers, found {len(papers)}")
    if len(evidence) != expected_evidence:
        issues.append(f"expected {expected_evidence} evidence records, found {len(evidence)}")
    if verified != expected_evidence:
        issues.append(f"expected {expected_evidence} verified evidence records, found {verified}")
    degradation = [
        f"{row['paper_id']}: {row['parser']} skipped because {row.get('error', 'unavailable')}"
        for row in parsing if row.get("status") == "skipped_unavailable"
    ]
    overall = "complete" if all(gates.values()) and not issues else "partial" if papers and downloads and evidence else "failed"
    summary = {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "overall_status": overall,
        "papers": {"expected": expected_papers, "actual": len(papers)},
        "evidence": {"expected": expected_evidence, "actual": len(evidence), "verified": verified},
        "review_queue": len(review_queue),
        "paper_status_counts": {status: paper_counts.get(status, 0) for status in STATUSES},
        "parser_status_counts": {status: parser_counts.get(status, 0) for status in STATUSES},
        "gates": gates,
        "degradation": degradation,
        "issues": issues,
        "structure": {
            "matched_labels": matched_labels,
            "total_labels": total_labels,
            "coverage_rate": round(coverage_rate, 6),
            "evidence_locators_resolved": evidence_locator_resolved,
            "evidence_locators_total": evidence_locator_total,
            "by_paper": coverage_by_paper,
        },
        "canonical_files": {
            "papers": "manifests/papers.jsonl",
            "downloads": "manifests/downloads.jsonl",
            "parsing": "manifests/parsing.jsonl",
            "evidence": "curated/evidence.jsonl",
            "review_queue": "curated/review_queue.jsonl",
        },
    }
    return summary, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--expected-papers", required=True, type=int)
    parser.add_argument("--expected-evidence", required=True, type=int)
    args = parser.parse_args()
    run_dir = ensure_run_layout(args.run)
    summary, issues = validate_run(run_dir, args.expected_papers, args.expected_evidence)
    write_json(run_dir / "release" / "release_manifest.json", summary)
    evidence_by_paper = Counter(row.get("paper_id") for row in read_jsonl(run_dir / "curated" / "evidence.jsonl"))
    report = render_report(summary, issues, summary["parser_status_counts"], evidence_by_paper)
    (run_dir / "release" / "validation_report.md").write_text(report, encoding="utf-8")
    protocol_path = run_dir / "protocol.json"
    if protocol_path.is_file():
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        write_json(protocol_path, finalize_protocol(protocol, summary))
    print(json.dumps({"status": summary["overall_status"], "issues": len(issues), "report": safe_relative_path(run_dir, run_dir / "release" / "validation_report.md")}, indent=2))
    return 0 if summary["overall_status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
