# Domain Profiles

Profiles extend the shared schema; they do not replace it.

## molecular-cellular

Capture gene/protein identifiers, perturbation, cell line or primary cell, tissue, species, assay, pathway, phenotype, dose, time, and figure panel.

## omics

Capture platform, modality, accession, tissue, cell type, sample count, donor/animal metadata, preprocessing, batch correction, differential threshold, cluster annotation, and supplement location.

## preclinical

Capture species, strain, model induction, age, sex, housing where relevant, randomization/blinding, intervention, dose, route, duration, endpoint, sample size, and effect statistic.

## clinical

Capture registration, design, eligibility, cohort/arm, allocation, baseline, intervention, comparator, time point, outcome definition, analysis population, sample size, estimate, uncertainty, and adverse events.

## plant

Capture species and cultivar, tissue, developmental stage, growth conditions, stressor, intensity, duration, gene/transcript/protein, phenotype, assay, treatment group, and recovery period.

## review

Capture the review type, search scope, evidence class, mechanism claim, cited support, limitations, and whether the statement is an author synthesis rather than a primary measurement.

## aging-muscle

Combine molecular-cellular, omics, preclinical, clinical, and review fields. Add muscle group, fiber type, neuromuscular junction, satellite cell state, chronological age, frailty/sarcopenia definition, exercise/nutrition exposure, strength, power, mass, function, regeneration, fibrosis, inflammation, metabolism, and mechanotransduction. Use `$aging-muscle-db-pipeline` when the request is specifically about maintaining the existing aging-muscle database.

