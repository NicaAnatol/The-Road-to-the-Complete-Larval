# Larval Drosophila Connectome

`document.tex` contains the existing IEEE-style draft. Only Section 3 was expanded with a documented preliminary search method, filtered quantitative results, and the proposed research pipeline.

The initial analysis uses a 10-year window (2015-2024), excluding the current and preceding years. The source exports were collected for 2010-2026, so these results are a retrospective subset. The exact search date, original WoS query, and controlled-vocabulary mapping still need confirmation before the search is reported as final.

## Reproduce aggregate results

Keep the Scopus/WoS exports and record-level screening files local. They are excluded from Git because database exports can be subject to reuse restrictions.

```powershell
python -m pip install -r requirements.txt
python stats.py
```

By default, the script reads `review_scopus.csv`, `savedrecs (*.xls`, `screening_decisions_with_reasons.csv`, and `deduplication_log.csv`, filters records to 2015-2024, checks that source, screening, and duplicate totals reconcile, and writes aggregate results to `counts.csv`. Override the period with `--start-year` and `--end-year`.

`search.txt` documents the current query variants, proposed WoS translation, date boundary, export formats, and remaining search-log items. `pipe.drawio` is the editable diagram; `pipe.png` is used in the paper. The last three diagram stages are proposed research, not completed analyses.
