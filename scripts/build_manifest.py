#!/usr/bin/env python3
"""Resolve authoritative metadata, normalize identifiers, and build a paper manifest."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from pipeline_common import (  # noqa: E402
    canonical_title,
    ensure_run_layout,
    normalize_doi,
    normalize_pmcid,
    normalize_pmid,
    utc_now,
    write_json,
    write_jsonl,
)


EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def normalize_paper(row: dict) -> dict:
    result = dict(row)
    result["doi"] = normalize_doi(row.get("doi"))
    result["pmcid"] = normalize_pmcid(row.get("pmcid"))
    result["pmid"] = normalize_pmid(row.get("pmid"))
    result["title"] = (row.get("title") or "").strip()
    return result


def deduplicate_papers(rows: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    output = []
    for raw in rows:
        row = normalize_paper(raw)
        keys = [
            ("pmcid", row["pmcid"] or ""),
            ("doi", row["doi"] or ""),
            ("pmid", row["pmid"] or ""),
            ("title", canonical_title(row["title"])),
        ]
        if any(value and (kind, value) in seen for kind, value in keys):
            continue
        output.append(row)
        seen.update((kind, value) for kind, value in keys if value)
    return output


def fetch_europe_pmc(pmcid: str) -> dict:
    query = urllib.parse.urlencode({"query": f"PMCID:{pmcid}", "format": "json", "pageSize": 5})
    request = urllib.request.Request(f"{EUROPE_PMC_SEARCH}?{query}", headers={"User-Agent": "life-science-evidence-pipeline/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    results = payload.get("resultList", {}).get("result", [])
    exact = [item for item in results if normalize_pmcid(item.get("pmcid")) == normalize_pmcid(pmcid)]
    if len(exact) != 1:
        raise ValueError(f"expected one Europe PMC result for {pmcid}, found {len(exact)}")
    return exact[0]


def resolve_corpus(corpus: dict) -> list[dict]:
    resolved = []
    for expected in corpus.get("papers", []):
        pmcid = normalize_pmcid(expected.get("pmcid"))
        if not pmcid:
            raise ValueError("every corpus paper requires a PMCID")
        source = fetch_europe_pmc(pmcid)
        row = {
            **expected,
            "pmcid": pmcid,
            "pmid": normalize_pmid(source.get("pmid")),
            "doi": normalize_doi(source.get("doi")),
            "title": source.get("title", "").strip(),
            "journal": source.get("journalTitle"),
            "publication_year": source.get("pubYear"),
            "is_open_access": str(source.get("isOpenAccess", "N")).upper() == "Y",
            "metadata_source": "Europe PMC",
            "metadata_url": f"https://europepmc.org/article/PMC/{pmcid.removeprefix('PMC')}",
            "resolved_at": utc_now(),
            "identity_status": "complete",
        }
        expected_doi = normalize_doi(expected.get("doi"))
        if expected_doi and row["doi"] != expected_doi:
            raise ValueError(f"DOI mismatch for {pmcid}: expected {expected_doi}, got {row['doi']}")
        if not row["is_open_access"]:
            raise ValueError(f"Europe PMC does not mark {pmcid} open access")
        resolved.append(row)
    return deduplicate_papers(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    run_dir = ensure_run_layout(args.run)
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    rows = resolve_corpus(corpus)
    write_jsonl(run_dir / "manifests" / "papers.jsonl", rows)
    protocol_path = run_dir / "protocol.json"
    if not protocol_path.exists():
        write_json(protocol_path, {
            "run_id": run_dir.name,
            "created_at": utc_now(),
            "purpose": corpus.get("purpose"),
            "source_policy": "open-access-only",
            "canonical_format": "JSONL",
            "expected_papers": len(corpus.get("papers", [])),
            "expected_evidence_per_paper": 5,
            "profiles": sorted({p["profile"] for p in corpus.get("papers", [])}),
            "status": "in_progress",
        })
    print(json.dumps({"papers": len(rows), "manifest": str(run_dir / "manifests" / "papers.jsonl")}, indent=2))
    return 0 if len(rows) == len(corpus.get("papers", [])) else 2


if __name__ == "__main__":
    raise SystemExit(main())

