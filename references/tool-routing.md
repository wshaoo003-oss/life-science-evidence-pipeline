# Tool Routing

## Acquisition

1. Use Europe PMC metadata and the versioned PMC AWS Open Data objects for PMCID-indexed open articles. Use the legacy OA package only as a temporary fallback.
2. Use a publisher OA URL only when the license and article identity are explicit.
3. Use InstSci only for a user-entitled closed article. Authentication must occur in a visible user-controlled browser. Never persist cookies or credentials in the run or release.
4. Use `agent-reach` for optional broad discovery when its CLI is available. API-first retrieval remains functional without it.

Reject downloads when the article identifiers disagree, the license is absent, the content starts as HTML instead of `%PDF-`, or the checksum changes without a documented version event.

PMC moved legacy OA packages under `/pub/pmc/deprecated/` on 2026-04-13 and scheduled their removal for August 2026. Prefer `https://pmc-oa-opendata.s3.amazonaws.com/metadata/<PMCID>.<version>.json`, then use its versioned PDF, XML, and media URLs.

## Parsing

| Input or goal | Primary | Cross-check | Notes |
|---|---|---|---|
| Scientific PDF | MinerU CPU pipeline | Docling | Preserve Markdown, JSON, figures, tables, and logs. |
| JATS XML or HTML | MarkItDown | JATS reference extractor | Use JATS as the structural authority when present. |
| Office, archives, simple files | MarkItDown | Docling where supported | Keep original source format. |
| Scholarly metadata, references, citations | GROBID | JATS | Optional when service is unavailable. |
| Scanned or complex PDF | MinerU OCR | Docling OCR | Record OCR mode and confidence limitations. |

MinerU is the required primary PDF parser. Route the highest-risk documents through Docling. Run GROBID when reachable; otherwise record `skipped_unavailable` for each affected paper.

## Runtime Discovery

Resolve executables in this order:

1. `PATH`
2. `RESEARCH_PIPELINE_ROOT`
3. `CODEX_HOME/tool-runtimes`

Never hardcode a username or assume that a virtual environment is activated.
