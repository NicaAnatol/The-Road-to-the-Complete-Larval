# Larval Drosophila Connectome

This repository documents a systematic review of how imaging and reconstruction advances made large-scale larval Drosophila connectomics possible.

## Search and analysis

The Scopus Search API was queried on 2026-11-04 with three Boolean searches. Together they returned 577 query results, including overlap, and added 488 unique records to the local Scopus database. The Web of Science (WoS) search was performed directly on its website; the three exports used were `savedrecs (7).xls`, `savedrecs (8).xls`, and `savedrecs (9).xls`. The exact WoS query and search date were not retained.

The quantitative results are a retrospective 2015-2024 subset of the available exports, not a new database search. The subset contains 568 source rows: 340 from Scopus and 228 from WoS. Deduplication removed 184 records, leaving 384 unique records. Source-level counts are in `source_counts.csv`; Scopus query counts are in `search_runs.csv`; Boolean expressions and limitations are in `search.txt`.

Title/abstract screening in ASReview LAB has reached 554 deduplicated records: 32 marked relevant, 507 excluded with recorded reasons, and 15 unclear. Within the 2015-2024 quantitative subset, the corresponding labels are 21, 354, and 9; 343 of its 384 records have abstracts. These are screening decisions, not completed full-text eligibility checks. The review will trace electron-microscopy acquisition, image processing, neuron/synapse reconstruction, and validation milestones, then compare reported dataset scale and coverage where measures are available.

The concise screening exports are `asreview_included.csv`, `asreview_excluded.csv`, and `asreview_unclear.csv`. They contain record identifiers, titles, years, DOIs, screening labels, and recorded reasons, but no abstracts. Every excluded record has an explanation in `asreview_excluded.csv`.

The Scopus export has abstracts for 269 of its 340 records in this period. Missing abstracts were manually looked up where accessible, as reported by the researcher. An OpenAlex enrichment check was also attempted for all 488 Scopus records, but per-record abstract provenance was not preserved; an exact manual-lookup count cannot be reported.

## Reproduce the workflow

Raw database exports and record-level screening files are intentionally excluded from Git. Keep these local files in the project folder:

- `review_scopus.csv`
- `savedrecs (7).xls`, `savedrecs (8).xls`, and `savedrecs (9).xls`
- `screening_decisions_with_reasons.csv`
- `deduplication_log.csv`

Install dependencies with `python -m pip install -r requirements.txt`. To rerun Scopus, set `ELSEVIER_API_KEY` in the local environment and run `python scopus.py`. Query expressions are field-neutral in `QUERIES`; the script maps them to Scopus syntax and applies the 2010-2026 publication-year filter. Search WoS directly on its website and save the exports locally. Then run:

```powershell
python merge.py
python stats.py
```

`merge.py` imports the Scopus and WoS exports, deduplicates by DOI and then normalized title/year, and writes local screening and duplicate-review files. After title/abstract decisions and rationales are recorded, `stats.py` filters aggregate counts to 2015-2024, checks source, screening, and deduplication totals, and writes `counts.csv` and `source_counts.csv`. It also refreshes the three screening CSVs from the full decision file. Change the analysis period with `--start-year` and `--end-year`.

`screening_criteria.csv` records the eligibility rules and decision rationale. The WoS query history/date and per-record abstract-source provenance were not retained; these limitations are reported in `search.txt` and Section 3 of `document.tex`. The project is a historical systematic review, not a planned connectome graph-ablation experiment. Raw records and abstracts are not included in this repository.
