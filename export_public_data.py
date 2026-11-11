import csv
from collections import Counter
from pathlib import Path

import pandas as pd

import merge


OUTPUT_DIR = Path("data")
PUBLIC_FIELDS = [
    "source",
    "source_id",
    "record_id",
    "year",
    "title",
    "authors",
    "journal",
    "doc_type",
    "doi",
    "keywords",
    "volume",
    "pages",
    "scopus_cited_by",
    "wos_times_cited",
    "language",
    "sources",
    "source_ids",
    "source_record_count",
    "deduplication_status",
]
SOURCE_FIELDS = [
    "source",
    "source_id",
    "year",
    "title",
    "authors",
    "journal",
    "doc_type",
    "doi",
    "keywords",
    "volume",
    "pages",
    "scopus_cited_by",
    "wos_times_cited",
    "language",
]


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in fields}
            for row in rows
        )


def excluded_by_year():
    rows = []
    scopus = pd.read_csv(
        merge.SCOPUS_CSV,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    for index, row in scopus.iterrows():
        year = merge.year_value(row.get("year"))
        if year and not merge.START_YEAR <= int(year) <= merge.END_YEAR:
            rows.append({
                "source": "Scopus",
                "source_id": merge.clean(row.get("eid")) or f"scopus-row-{index + 1}",
                "year": year,
                "title": merge.clean(row.get("title")),
                "doi": merge.first_doi(row.get("doi")),
                "filter_reason": f"Publication year outside {merge.START_YEAR}-{merge.END_YEAR}",
            })

    for path in sorted(Path(".").glob(merge.WOS_GLOB)):
        frame = pd.read_excel(path, dtype=str).fillna("")
        for index, row in frame.iterrows():
            year = merge.year_value(row.get("Publication Year"))
            if year and not merge.START_YEAR <= int(year) <= merge.END_YEAR:
                wos_id = merge.clean(row.get("UT (Unique WOS ID)"))
                rows.append({
                    "source": path.name,
                    "source_id": wos_id or f"{path.stem}-row-{index + 1}",
                    "year": year,
                    "title": merge.clean(row.get("Article Title")),
                    "doi": merge.first_doi(row.get("DOI")),
                    "filter_reason": f"Publication year outside {merge.START_YEAR}-{merge.END_YEAR}",
                })
    return rows


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    records, wos_files, identified_counts, date_excluded = merge.load_records()
    groups, candidates = merge.group_records(records)
    excluded = excluded_by_year()

    for source in ["Scopus", *(path.name for path in wos_files)]:
        rows = [record for record in records if record["source"] == source]
        wos_number = Path(source).stem.rsplit("(", 1)[-1].rstrip(")")
        write_csv(
            OUTPUT_DIR / (
                "scopus_filtered.csv" if source == "Scopus"
                else f"wos_{wos_number}_filtered.csv"
            ),
            rows,
            SOURCE_FIELDS,
        )

    candidate_ids = {
        id(record)
        for candidate_group in candidates
        for record in candidate_group
    }
    deduplicated = []
    duplicates = []
    for group in groups:
        merged_record = merge.merge_group(group)
        merged_record["source_record_count"] = len(group)
        merged_record["deduplication_status"] = (
            "possible_duplicate_manual_check"
            if any(id(record) in candidate_ids for record in group)
            else "deduplicated"
        )
        deduplicated.append(merged_record)
        keeper = next(
            (record for record in group if record["source"] == "Scopus"),
            group[0],
        )
        for record in group:
            if record is keeper:
                continue
            same_doi = bool(record["doi"] and record["doi"] == keeper["doi"])
            duplicates.append({
                "duplicate_source": record["source"],
                "duplicate_source_id": record["source_id"],
                "duplicate_title": record["title"],
                "duplicate_year": record["year"],
                "duplicate_doi": record["doi"],
                "kept_record_id": merged_record["record_id"],
                "kept_source": keeper["source"],
                "kept_source_id": keeper["source_id"],
                "match_method": (
                    "same DOI" if same_doi
                    else "normalized title and year"
                ),
            })

    write_csv(
        OUTPUT_DIR / "deduplicated_records.csv",
        deduplicated,
        PUBLIC_FIELDS,
    )
    write_csv(
        OUTPUT_DIR / "removed_duplicates.csv",
        duplicates,
        [
            "duplicate_source",
            "duplicate_source_id",
            "duplicate_title",
            "duplicate_year",
            "duplicate_doi",
            "kept_record_id",
            "kept_source",
            "kept_source_id",
            "match_method",
        ],
    )
    write_csv(
        OUTPUT_DIR / "outside_year_range.csv",
        excluded,
        ["source", "source_id", "year", "title", "doi", "filter_reason"],
    )

    year_missing = Counter(
        record["source"] for record in records if not record["year"]
    )
    log_rows = [
        {
            "stage": "identified",
            "source": source,
            "records": count,
            "notes": "Rows in the supplied database export before year filtering.",
        }
        for source, count in identified_counts.items()
    ]
    log_rows.extend(
        {
            "stage": "excluded_outside_year_range",
            "source": source,
            "records": count,
            "notes": f"Publication year outside {merge.START_YEAR}-{merge.END_YEAR}.",
        }
        for source, count in date_excluded.items()
    )
    log_rows.extend(
        {
            "stage": "retained_after_year_filter",
            "source": source,
            "records": sum(record["source"] == source for record in records),
            "notes": "Known years within range; records with missing year retained for verification.",
        }
        for source in identified_counts
    )
    log_rows.extend([
        {
            "stage": "missing_publication_year",
            "source": source,
            "records": count,
            "notes": "Retained for manual year verification; not excluded by the year filter.",
        }
        for source, count in year_missing.items()
    ])
    log_rows.extend([
        {
            "stage": "removed_as_duplicates",
            "source": "All sources",
            "records": len(duplicates),
            "notes": "Matched by DOI or normalized title and year.",
        },
        {
            "stage": "retained_after_deduplication",
            "source": "All sources",
            "records": len(deduplicated),
            "notes": "Includes possible duplicate records retained for manual checking.",
        },
        {
            "stage": "possible_duplicate_manual_check",
            "source": "All sources",
            "records": sum(len(group) for group in candidates),
            "notes": "Same normalized title and year with conflicting DOIs; retained, not merged.",
        },
    ])
    write_csv(
        OUTPUT_DIR / "filtering_log.csv",
        log_rows,
        ["stage", "source", "records", "notes"],
    )

    if sum(identified_counts.values()) - sum(date_excluded.values()) != len(records):
        raise RuntimeError("The year-filter counts do not reconcile with retained records.")
    if len(records) - len(duplicates) != len(deduplicated):
        raise RuntimeError("The deduplication counts do not reconcile.")
    if sum(date_excluded.values()) != len(excluded):
        raise RuntimeError("The out-of-range export does not reconcile with the filter log.")

    print(
        f"Identified: {sum(identified_counts.values())}; "
        f"outside year range: {len(excluded)}; "
        f"after year filter: {len(records)}; "
        f"duplicates removed: {len(duplicates)}; "
        f"deduplicated records: {len(deduplicated)}"
    )


if __name__ == "__main__":
    main()
