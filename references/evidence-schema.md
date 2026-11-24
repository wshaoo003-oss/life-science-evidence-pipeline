# Evidence Schema

JSONL is canonical. Each line is an independently auditable object. Add fields without mutating source meaning; version breaking changes.

## Core Objects

- `paper`: DOI, PMID, PMCID, title, version, journal, year, OA status, license, source URLs, identity status.
- `document`: paper ID, format, source URL, acquired time, MIME/signature result, path, immutable SHA-256.
- `study`: design, domain profile, species, model, tissue, cell, age/stage, sex, setting, sample size.
- `arm`: cohort or experimental group, eligibility, allocation, baseline, sample size.
- `intervention`: treatment/exposure, dose, route, frequency, duration, comparator.
- `outcome`: endpoint name, definition, time point, analysis population.
- `measurement`: value, unit, statistic, uncertainty, sample size, direction, assay, source locator.
- `claim`: one source-grounded author conclusion with scope and source locator.
- `entity`: entity type, source text, normalized label, stable identifier, mapping status, candidates.
- `run`: protocol, environment, commands, tool versions, start/end time, status counts.
- `review`: record ID, reason, candidates, reviewer, decision, timestamp.

## Evidence JSONL

Required fields:

```json
{
  "evidence_id": "PMC123-E01",
  "paper_id": "PMC123",
  "evidence_type": "measurement",
  "claim": "Atomic source-grounded statement.",
  "species": ["Homo sapiens"],
  "model": "randomized controlled trial",
  "tissue_or_cell": ["skeletal muscle"],
  "life_stage_or_age": "70-80 years",
  "sex": "mixed",
  "intervention_or_exposure": "resistance exercise",
  "assay": "handgrip dynamometry",
  "outcome": "grip strength",
  "value": 1.2,
  "unit": "kg",
  "direction": "increase",
  "source_locator": {"document": "article.nxml", "section": "Results", "paragraph": 3},
  "source_checksum": "64 lowercase hexadecimal characters",
  "parser": "jats-reference",
  "review_status": "verified"
}
```

`evidence_type` is `measurement` or `author_claim`. A numeric value requires a unit and direction. `review_status` is `candidate`, `verified`, `rejected`, or `needs-review`. Use explicit `null` for inapplicable values. Do not encode missing values as zero.

## Source Locator

Require `document`, `section`, and at least one of `paragraph`, `page`, `figure`, `table`, or `supplement`. Add `panel`, `row`, `column`, `quote`, or JATS element ID when useful. The checksum identifies the exact source version.

## Entity Review

If one source string maps to multiple valid identifiers, create a review-queue line with context and candidate identifiers. Do not select the most common candidate without evidence.

