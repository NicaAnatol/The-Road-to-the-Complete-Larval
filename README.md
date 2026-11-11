# Larval Drosophila Connectome

This repository documents a historical systematic review of how imaging and
computational reconstruction enabled increasingly large-scale larval
*Drosophila melanogaster* connectomics. Bibliometric results are preliminary:
ASReview title-and-abstract labels have not yet been confirmed by full-text
eligibility assessment.

## Search and screening

The Scopus Search API was queried on 4 November 2026 using three Boolean
searches. They returned 577 query results, including overlap, and 488 unique
Scopus records. Web of Science (WoS) was searched manually on its website;
the three exports used were `savedrecs (7).xls`, `savedrecs (8).xls`, and
`savedrecs (9).xls`. The exact WoS query and search date were not retained.

Across both sources, 935 records were identified. Applying the 2010--2026
publication-year limit excluded 124 records, leaving 811 records within the
date range or awaiting year verification. Deduplication removed 257 records
by DOI or normalized title and year. One candidate pair (two records) with
conflicting DOIs was retained for manual checking. The resulting 554-record
set has 487 abstracts; records without abstracts were not automatically
excluded. Missing Scopus abstracts were manually checked where accessible;
an OpenAlex enrichment was also attempted, but per-record abstract
provenance was not preserved, so the exact manual-lookup count is unknown.

Title-and-abstract screening in ASReview LAB currently labels 32 records as
relevant, 507 as excluded with recorded reasons, and 15 as unclear. These are
not final full-text eligibility decisions. The concise files
`asreview_included.csv`, `asreview_excluded.csv`, and `asreview_unclear.csv`
contain identifiers, titles, years, DOIs, labels, and available reasons, but
no abstracts. The historical review will extract milestones in
electron-microscopy acquisition, image processing, neuron and synapse
reconstruction, and validation, then compare dataset scale and coverage where
reported.

## Extracted source metadata

The `data/` folder contains metadata-only records from Scopus and Web of
Science after the publication-year filter, the deduplicated dataset, an
out-of-range record log, a duplicate log, and counts for each filtering
stage. Abstracts, affiliations and addresses, emails, cited-reference text,
and full text are not included. See `data/README.md` for details and
regeneration instructions.

`search.txt` documents the Boolean expressions and data limitations.
`search_runs.csv` records the Scopus query results. `source_counts.csv` is a
retrospective 2015--2024 subset of the exports (568 source rows, 184
duplicates removed, and 384 unique records); it is not a new database search.
The full identification, date-filtering, and deduplication counts are in
`prisma_identification_counts.csv`.

## Preliminary bibliometric analysis

`bibliometrics.R` uses R 4.6.2 and bibliometrix 5.5.0 to generate aggregate
tables and figures from the local screening file. It profiles yearly output
for all 554 records, and authors, reported affiliations, keywords, outlets,
citations, keyword co-occurrence, and co-authorship for the 32 records
currently labeled relevant. `keyword_thesaurus.csv` records the initial
keyword normalization. Generated aggregate figures and tables are in
`bibliometrics/`.

The citation indicator is the per-record maximum of Scopus and WoS counts,
not their sum; citation counts are snapshots whose capture date was not
retained. The merged exports do not include cited-reference lists, so
co-citation and historiographic analyses are unavailable. Affiliation data
are incomplete and not consistently linked to individual authors, so
institutional collaboration claims are not made. These limitations, and the
preliminary status of the screening labels, should be considered when
interpreting the figures.

To reproduce the bibliometric outputs, keep
`screening_decisions_with_reasons.csv` in the project folder, install
bibliometrix from CRAN with `install.packages("bibliometrix")`, then run:

```powershell
Rscript.exe bibliometrics.R
```

The Python search and merge workflow additionally requires the files listed
in `search.txt`; install its dependencies with
`python -m pip install -r requirements.txt`. To rerun Scopus, set
`ELSEVIER_API_KEY` locally and run `python scopus.py`. Search WoS directly
on its website and save the exports locally. Then run:

```powershell
python merge.py
python stats.py
```

`stats.py` refreshes the concise screening exports and the PRISMA screening
status rows from the complete decision file. Its `counts.csv` and
`source_counts.csv` outputs use the selected 2015--2024 retrospective period.

Raw database exports, abstracts, the full screening file, and record-level
citation output are intentionally kept local and are not committed. The
derived metadata files in `data/` omit abstracts, affiliations and addresses,
emails, and cited-reference text.
