# Extracted database metadata

These files are derived from the local Scopus Search API export and the three
Web of Science website exports. They contain bibliographic metadata only;
abstracts, affiliations and addresses, cited-reference text, email addresses,
and full text are omitted.
The original database exports are not redistributed.

## Files

- `scopus_filtered.csv`: Scopus records retained by the publication-year filter.
- `wos_7_filtered.csv`, `wos_8_filtered.csv`, `wos_9_filtered.csv`: retained
  records from the three Web of Science exports.
- `deduplicated_records.csv`: merged metadata for the resulting 554 records.
- `removed_duplicates.csv`: 257 source rows removed during deduplication,
  with the matched retained record and match method.
- `outside_year_range.csv`: 124 source rows excluded because their reported
  publication year is outside 2010--2026.
- `filtering_log.csv`: per-source counts at each processing stage.

## Filtering and deduplication

The year rule retains records with a publication year from 2010 through
2026, inclusive. Records with no parseable year are retained for manual
verification and counted separately; they are not classified as outside the
date range.

The supplied exports contained 935 rows: 488 Scopus and 447 Web of Science.
The year filter excluded 124 rows and retained 811. Deduplication first
matches DOI and then normalized title and year when those records do not
have conflicting DOI values. This removed 257 rows and produced 554 records.
One same-title/year pair with conflicting DOIs remains unmerged for manual
verification.

Run `python export_public_data.py` from the project root to regenerate these
files from the local exports. The script requires the source files named in
the root README and does not export abstracts, affiliations, addresses, or full text.
