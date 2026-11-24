---
name: life-science-evidence-pipeline
description: Build, validate, and release traceable evidence datasets from life-science literature. Use for literature evidence ETL, batch open-access retrieval, scientific PDF/JATS parsing, figure/table-aware extraction, atomic claims and measurements, evidence database preparation, or domain batches in molecular biology, omics, animal studies, clinical research, plant science, reviews, and aging skeletal muscle.
---

# Life Science Evidence Pipeline

Build an evidence system, not a PDF archive. Keep every released claim traceable to a legally obtained immutable source and an exact source locator.

## Core Rules

- Treat JSONL as the canonical source; derive databases and graphs later.
- Keep `raw`, `parsed`, `curated`, and `release` layers separate.
- Prefer Europe PMC, NCBI PMC OA packages, and publisher OA routes.
- Use InstSci only for content the user is entitled to access. Never export credentials, cookies, tokens, or institution session state.
- Reject login pages or HTML saved with a `.pdf` suffix.
- Treat parser output as a candidate. Only verified records enter a release.
- Never silently infer ambiguous genes, species, tissues, cells, diseases, or compounds. Send them to `review_queue.jsonl`.
- Preserve source files, parser versions, commands, logs, checksums, and audit decisions.

## Ten-Stage Workflow

1. **Protocol**: define question, profile, corpus, inclusion criteria, evidence fields, and release gate in `protocol.json`.
2. **Runtime**: run `scripts/check_runtime.py`; require MinerU, MarkItDown, and Docling for a full batch. GROBID may degrade.
3. **Discovery**: retrieve metadata through Europe PMC/NCBI or another authoritative API. `agent-reach` is an optional discovery enhancement.
4. **Identity**: normalize DOI, PMID, PMCID, and title; deduplicate versions before downloading.
5. **Acquisition**: run `scripts/fetch_open_access.py`; record license, URL, time, MIME/signature checks, and SHA-256.
6. **Parsing**: run MinerU as the primary PDF parser. Route JATS/HTML/Office to MarkItDown, selected PDFs to Docling, and scholarly structure to GROBID when available.
7. **Structure QA**: compare parser outputs with JATS when available for title, abstract, Methods, Results, figures, tables, references, and reading order.
8. **Evidence Curation**: create atomic measurements and author claims using the schema in `references/evidence-schema.md`.
9. **Entity Review**: normalize entities only when identifiers are defensible; otherwise append a review item with candidates and context.
10. **Release**: run `scripts/validate_run.py`; reconcile complete, partial, blocked, failed, and needs-review counts before publishing.

## Tool Routing

Read `references/tool-routing.md` before acquisition or parsing. Runtime discovery order is `PATH`, `RESEARCH_PIPELINE_ROOT`, then `CODEX_HOME/tool-runtimes`; do not hardcode a username.

Use the public run interface:

```text
run/
|-- protocol.json
|-- raw/
|-- parsed/
|-- curated/
|   |-- evidence.jsonl
|   `-- review_queue.jsonl
|-- manifests/
|   |-- papers.jsonl
|   |-- downloads.jsonl
|   `-- parsing.jsonl
`-- release/
    |-- release_manifest.json
    `-- validation_report.md
```

## Failure States

- `complete`: required artifacts exist and all gates pass.
- `partial`: useful outputs exist, but a noncritical parser or coverage target failed.
- `blocked`: an external dependency, entitlement, or explicit user action is required.
- `failed`: required acquisition, identity, integrity, or validation failed.
- `needs-review`: ambiguity or content verification prevents release of specific records.
- `skipped_unavailable`: optional tool is absent; use this for GROBID degradation and do not translate it into success.

## Domain Profiles

Select one or more profiles from `references/domain-profiles.md`. The `aging-muscle` profile is the first concrete specialization and complements, rather than replaces, `$aging-muscle-db-pipeline`.

## Commands

```powershell
python scripts/check_runtime.py --json
python scripts/build_manifest.py --corpus assets/validation-corpus.json --run <run>
python scripts/fetch_open_access.py --run <run>
python scripts/parse_batch.py --run <run> --corpus assets/validation-corpus.json
python scripts/validate_run.py --run <run> --expected-papers 5 --expected-evidence 25
```

## Release Gate

Read `references/quality-gates.md`. A release must not contain restricted full text, credentials, cookies, access tokens, institution state, or unverified evidence. Report exact status counts and every degradation reason.

