import argparse
import csv
import re
from collections import Counter
from pathlib import Path

import pandas as pd


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def year_value(value):
    match = re.search(r"\b(?:19|20)\d{2}\b", str(value))
    return int(match.group()) if match else None


def in_period(value, start, end):
    year = year_value(value)
    return year is not None and start <= year <= end


def h_index(citations):
    return max(
        (rank for rank, count in enumerate(sorted(citations, reverse=True), 1)
         if count >= rank),
        default=0,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scopus", type=Path, default=Path("review_scopus.csv"))
    parser.add_argument("--wos-pattern", default="savedrecs (*.xls")
    parser.add_argument(
        "--decisions",
        type=Path,
        default=Path("screening_decisions_with_reasons.csv"),
    )
    parser.add_argument(
        "--duplicates",
        type=Path,
        default=Path("deduplication_log.csv"),
    )
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--output", type=Path, default=Path("counts.csv"))
    args = parser.parse_args()

    if args.start_year > args.end_year:
        raise ValueError("start-year must be less than or equal to end-year")

    source_counts = Counter()
    source_years = {}
    scopus = pd.read_csv(
        args.scopus, dtype=str, keep_default_na=False, encoding="utf-8-sig"
    )
    for row in scopus.to_dict("records"):
        source = "Scopus"
        source_id = row.get("eid", "").strip()
        year = year_value(row.get("year", ""))
        if year is not None:
            source_years[(source, source_id)] = year
        if year is not None and args.start_year <= year <= args.end_year:
            source_counts[source] += 1

    wos_files = sorted(Path(".").glob(args.wos_pattern))
    if not wos_files:
        raise FileNotFoundError(f"No WoS exports matched {args.wos_pattern!r}")

    for path in wos_files:
        frame = pd.read_excel(path, dtype=str).fillna("")
        source = path.name
        for row in frame.to_dict("records"):
            source_id = row.get("UT (Unique WOS ID)", "").strip()
            year = year_value(row.get("Publication Year", ""))
            if year is not None:
                source_years[(source, source_id)] = year
            if year is not None and args.start_year <= year <= args.end_year:
                source_counts[source] += 1

    decisions = read_csv(args.decisions)
    records = [
        row for row in decisions
        if in_period(row.get("year", ""), args.start_year, args.end_year)
    ]
    if not records:
        raise ValueError("No screened records fall within the selected period")

    record_ids = [row["record_id"] for row in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("The screened records contain duplicate record_id values")

    labels = Counter(row["decision"].strip().upper() for row in records)
    expected_labels = {"INCLUDE", "EXCLUDE", "UNCLEAR"}
    if set(labels) - expected_labels:
        raise ValueError(f"Unexpected screening labels: {set(labels) - expected_labels}")

    duplicates = read_csv(args.duplicates)
    duplicate_methods = Counter()
    for row in duplicates:
        key = (row["duplicate_source"], row["duplicate_source_id"])
        if key not in source_years:
            raise ValueError(f"Duplicate record not found in source exports: {key}")
        year = source_years[key]
        if args.start_year <= year <= args.end_year:
            duplicate_methods[row["match_method"].strip()] += 1

    identified = sum(source_counts.values())
    unique_count = len(records)
    duplicate_count = sum(duplicate_methods.values())
    if identified - unique_count != duplicate_count:
        raise ValueError(
            "Source, screening, and duplicate totals do not reconcile: "
            f"{identified} - {unique_count} != {duplicate_count}"
        )

    rows = []

    def add(group, category, value, denominator="", percentage=""):
        rows.append({
            "group": group,
            "category": category,
            "value": value,
            "denominator": denominator,
            "percentage": percentage,
        })

    for source, count in sorted(source_counts.items()):
        add("Records identified", source, count)
    add("Records identified", "All sources", identified)
    add(
        "Deduplication",
        "Duplicates removed",
        duplicate_count,
        identified,
        f"{100 * duplicate_count / identified:.1f}",
    )
    add(
        "Screening",
        "Unique records",
        unique_count,
        identified,
        f"{100 * unique_count / identified:.1f}",
    )

    for label in ("INCLUDE", "EXCLUDE", "UNCLEAR"):
        add(
            "Screening decision",
            label,
            labels[label],
            unique_count,
            f"{100 * labels[label] / unique_count:.1f}",
        )

    abstracts = Counter(
        "Available" if row.get("abstract", "").strip() else "Missing"
        for row in records
    )
    for category in ("Available", "Missing"):
        add(
            "Abstract",
            category,
            abstracts[category],
            unique_count,
            f"{100 * abstracts[category] / unique_count:.1f}",
        )

    annual = Counter(str(year_value(row["year"])) for row in records)
    for year, count in sorted(annual.items()):
        add(
            "Publication year",
            year,
            count,
            unique_count,
            f"{100 * count / unique_count:.1f}",
        )

    document_types = Counter(
        row.get("doc_type", "").strip() or "Not reported" for row in records
    )
    for category, count in sorted(document_types.items()):
        add("Document type", category, count, unique_count)

    citations = []
    for row in records:
        value = row.get("scopus_cited_by", "").strip()
        if value:
            try:
                citations.append(int(float(value)))
            except ValueError as error:
                raise ValueError(f"Invalid Scopus citation count: {value!r}") from error

    if citations:
        add("Scopus citations", "Records with citation data", len(citations), unique_count)
        add("Scopus citations", "Total citations", sum(citations))
        add("Scopus citations", "Mean citations per record with data",
            f"{sum(citations) / len(citations):.1f}")
        add("Scopus citations", "Median citations per record with data",
            sorted(citations)[len(citations) // 2])
        add("Scopus citations", "h-index of records with citation data",
            h_index(citations))
        add("Scopus citations", "Records cited at least 10 times",
            sum(value >= 10 for value in citations), len(citations))

    keyword_counts = Counter()
    keyword_records = 0
    for row in records:
        terms = {
            term.strip().casefold()
            for term in re.split(r"\s*;\s*", row.get("keywords", ""))
            if term.strip()
        }
        if terms:
            keyword_records += 1
            keyword_counts.update(terms)
    add("Keywords", "Records with keywords", keyword_records, unique_count)
    for term, count in keyword_counts.most_common(10):
        add("Keyword frequency", term, count, unique_count)

    for method, count in sorted(duplicate_methods.items()):
        add("Duplicate match", method, count, duplicate_count)

    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["group", "category", "value", "denominator", "percentage"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"{args.start_year}-{args.end_year}: {identified} identified, "
        f"{duplicate_count} duplicates removed, {unique_count} unique records"
    )
    print(f"Wrote {len(rows)} aggregate rows to {args.output}")


if __name__ == "__main__":
    main()
