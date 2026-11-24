# Quality Gates

## Identity Gate

- DOI, PMID, PMCID, and normalized title agree with the authoritative record.
- Versions are deduplicated and the selected version is documented.
- Identity match target: 100%.

## Document Gate

- Acquisition is legal and license evidence is recorded.
- PDF begins with `%PDF-`; HTML login responses are rejected.
- Source URL, acquisition time, size, and SHA-256 are present.
- No credentials, cookies, tokens, or institution state enter a manifest or release.

## Parsing Gate

- MinerU completes every required PDF.
- Configured Docling and MarkItDown cross-parses complete.
- GROBID may be `skipped_unavailable` with a precise reason.
- Compare title, abstract, Methods, Results, reading order, figures, tables, and references against JATS.
- Figure/table label coverage target is at least 80%; every figure or table cited by evidence must resolve at 100%.

## Evidence Gate

- Each record is atomic and has an immutable source checksum.
- Each locator contains document, section, and a paragraph/page/figure/table/supplement coordinate.
- Numeric value, unit, sample size when stated, and direction match the source.
- Automated output remains `candidate` until a source audit marks it `verified`.
- Ambiguous entities enter the review queue.

## Release Gate

- Exact counts for `complete`, `partial`, `blocked`, `failed`, and `needs-review` reconcile with manifests.
- All release evidence is verified; rejected and unresolved candidates are excluded.
- Canonical JSONL, release manifest, and validation report agree.
- Restricted full text and raw subscription documents never enter a distributable release.

## Sampling

For initial validation, audit 100% of evidence. For established large batches, use risk-based sampling only after identity, checksum, and locator checks remain automated for 100% of records.

