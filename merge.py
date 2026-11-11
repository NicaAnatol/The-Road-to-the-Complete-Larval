import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd


SCOPUS_CSV = Path("review_scopus.csv")
WOS_GLOB = "savedrecs (*.xls"
BIB_FILE = Path("systematic_review_merged.bib")
ASREVIEW_FILE = Path("asreview_screening.csv")
DUPLICATES_FILE = Path("deduplication_log.csv")
DUPLICATE_CANDIDATES_FILE = Path("duplicate_candidates_for_manual_check.csv")
PRISMA_FILE = Path("prisma_identification_counts.csv")
START_YEAR = 2010
END_YEAR = 2026


def clean(value):
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.casefold() in {"nan", "none", "null"} else value


def first_doi(value):
    for candidate in clean(value).split(";"):
        doi = candidate.strip().lower()
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
        doi = re.sub(r"\s+", "", doi).rstrip(".,;")
        if doi and doi not in {"n/a", "na"}:
            return doi
    return ""


def title_key(value):
    normalized = unicodedata.normalize("NFKD", clean(value))
    normalized = normalized.encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def year_value(value):
    match = re.search(r"\b(?:19|20)\d{2}\b", clean(value))
    return match.group(0) if match else ""


def split_values(*values):
    result, seen = [], set()
    for value in values:
        for item in re.split(r"\s*;\s*", clean(value)):
            item = item.strip()
            key = item.casefold()
            if item and key not in seen:
                seen.add(key)
                result.append(item)
    return "; ".join(result)


def load_records():
    if not SCOPUS_CSV.is_file():
        raise FileNotFoundError(f"Required Scopus export not found: {SCOPUS_CSV}")

    records = []
    identified_counts = {"Scopus": 0}
    date_excluded = defaultdict(int)
    scopus = pd.read_csv(SCOPUS_CSV, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    identified_counts["Scopus"] = len(scopus)
    for index, row in scopus.iterrows():
        eid = clean(row.get("eid")) or f"scopus-row-{index + 1}"
        year = year_value(row.get("year"))
        if year and not START_YEAR <= int(year) <= END_YEAR:
            date_excluded["Scopus"] += 1
            continue
        records.append({
            "source": "Scopus",
            "source_id": eid,
            "eid": clean(row.get("eid")),
            "wos_id": "",
            "doi": first_doi(row.get("doi")),
            "title": clean(row.get("title")),
            "abstract": clean(row.get("abstract")),
            "authors": clean(row.get("authors") or row.get("first_author")),
            "year": year,
            "journal": clean(row.get("journal")),
            "doc_type": clean(row.get("doc_type")),
            "volume": "",
            "pages": "",
            "keywords": clean(row.get("keywords")),
            "affiliations": "",
            "scopus_cited_by": clean(row.get("cited_by")),
            "wos_times_cited": "",
            "language": "",
        })

    wos_files = sorted(Path(".").glob(WOS_GLOB))
    if not wos_files:
        raise FileNotFoundError("No savedrecs (*.xls) Web of Science exports found.")

    for path in wos_files:
        frame = pd.read_excel(path, dtype=str).fillna("")
        identified_counts[path.name] = len(frame)
        for index, row in frame.iterrows():
            year = year_value(row.get("Publication Year"))
            if year and not START_YEAR <= int(year) <= END_YEAR:
                date_excluded[path.name] += 1
                continue
            wos_id = clean(row.get("UT (Unique WOS ID)"))
            source_id = wos_id or f"{path.stem}-row-{index + 1}"
            full_authors = clean(row.get("Author Full Names"))
            authors = full_authors or clean(row.get("Authors"))
            records.append({
                "source": path.name,
                "source_id": source_id,
                "eid": "",
                "wos_id": wos_id,
                "doi": first_doi(row.get("DOI")),
                "title": clean(row.get("Article Title")),
                "abstract": clean(row.get("Abstract")),
                "authors": authors,
                "year": year,
                "journal": clean(row.get("Source Title")),
                "doc_type": clean(row.get("Document Type")),
                "volume": clean(row.get("Volume")),
                "pages": clean(row.get("Start Page") or row.get("Article Number")),
                "keywords": split_values(
                    row.get("Author Keywords"), row.get("Keywords Plus")
                ),
                "affiliations": clean(row.get("Affiliations")),
                "scopus_cited_by": "",
                "wos_times_cited": clean(row.get("Times Cited, WoS Core")),
                "language": clean(row.get("Language")),
            })

    if any(not record["title"] for record in records):
        raise ValueError("An imported record has no title; refusing unsafe deduplication.")
    return records, wos_files, identified_counts, date_excluded


class DisjointSet:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first, second):
        root_first, root_second = self.find(first), self.find(second)
        if root_first != root_second:
            self.parent[root_second] = root_first


def group_records(records):
    sets = DisjointSet(len(records))
    by_doi, by_title_year = defaultdict(list), defaultdict(list)
    ambiguous_title_groups = []

    for index, record in enumerate(records):
        if record["doi"]:
            by_doi[record["doi"]].append(index)
        key = (title_key(record["title"]), record["year"])
        if key[0] and key[1]:
            by_title_year[key].append(index)

    for matches in by_doi.values():
        for index in matches[1:]:
            sets.union(matches[0], index)
    for matches in by_title_year.values():
        doi_values = {records[index]["doi"] for index in matches if records[index]["doi"]}
        if len(doi_values) > 1:
            ambiguous_title_groups.append(matches)
            continue
        for index in matches[1:]:
            sets.union(matches[0], index)

    groups = defaultdict(list)
    for index, record in enumerate(records):
        groups[sets.find(index)].append(record)
    index_by_id = {id(record): index for index, record in enumerate(records)}
    ordered_groups = sorted(
        groups.values(),
        key=lambda group: min(index_by_id[id(record)] for record in group),
    )
    candidates = [
        [records[index] for index in matches]
        for matches in ambiguous_title_groups
    ]
    return ordered_groups, candidates


def choose_value(group, field):
    values = [record[field] for record in group if record.get(field)]
    return max(values, key=len) if values else ""


def author_for_bib(value):
    parts = [part.strip() for part in value.split(";") if part.strip()]
    return " and ".join(parts) if len(parts) > 1 else value


def merge_group(group):
    ordered = sorted(
        group,
        key=lambda record: (record["source"] != "Scopus", record["source"]),
    )
    merged = {}
    for field in ("title", "abstract", "authors", "year", "journal", "doc_type",
                  "volume", "pages", "affiliations", "language"):
        merged[field] = choose_value(ordered, field)
    merged["doi"] = next((record["doi"] for record in ordered if record["doi"]), "")
    merged["eid"] = next((record["eid"] for record in ordered if record["eid"]), "")
    merged["wos_id"] = next((record["wos_id"] for record in ordered if record["wos_id"]), "")
    merged["keywords"] = split_values(*(record["keywords"] for record in ordered))
    merged["sources"] = "; ".join(dict.fromkeys(r["source"] for r in ordered))
    merged["source_ids"] = "; ".join(
        f"{record['source']}:{record['source_id']}" for record in ordered
    )
    merged["scopus_cited_by"] = next(
        (r["scopus_cited_by"] for r in ordered if r["scopus_cited_by"]), ""
    )
    merged["wos_times_cited"] = next(
        (r["wos_times_cited"] for r in ordered if r["wos_times_cited"]), ""
    )
    merged["record_id"] = (
        merged["doi"] or merged["eid"] or merged["wos_id"] or
        f"{title_key(merged['title'])}-{merged['year']}"
    )
    return merged


def bib_escape(value):
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in clean(value))


def cite_key(record, used):
    author_parts = record["authors"].split(";")[0].split(",")[0].split()
    author = author_parts[0] if author_parts else "anon"
    title_words = re.findall(r"[A-Za-z0-9]+", record["title"])
    title_word = title_words[0].lower() if title_words else "work"
    base = re.sub(r"[^A-Za-z0-9]", "", author).lower()
    base = f"{base or 'anon'}{record['year'] or 'nd'}{title_word}"
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}{count + 1}"


def write_exports(
    merged_records, groups, candidate_groups, raw_records, wos_files,
    identified_counts, date_excluded,
):
    used, entries = {}, []
    for record in merged_records:
        key = cite_key(record, used)
        doc_type = record["doc_type"].casefold()
        is_conference = "conference" in doc_type or "proceeding" in doc_type
        kind = "inproceedings" if is_conference else "article"
        venue = "booktitle" if is_conference else "journal"
        fields = [
            ("author", author_for_bib(record["authors"])),
            ("title", record["title"]),
            (venue, record["journal"]),
            ("year", record["year"]),
            ("volume", record.get("volume", "")),
            ("pages", record.get("pages", "")),
            ("doi", record["doi"]),
            ("keywords", record["keywords"]),
            ("abstract", record["abstract"]),
            ("note", f"Sources: {record['sources']} | IDs: {record['source_ids']}"),
        ]
        body = ",\n".join(
            f"  {field} = {{{bib_escape(value)}}}"
            for field, value in fields if value
        )
        entries.append(f"@{kind}{{{key},\n{body}\n}}")
    BIB_FILE.write_text("\n\n".join(entries) + "\n", encoding="utf-8")

    csv_fields = [
        "record_id", "title", "abstract", "authors", "year", "journal", "doi",
        "keywords", "affiliations", "doc_type", "sources", "source_ids",
        "scopus_cited_by", "wos_times_cited", "eid", "wos_id",
    ]
    with ASREVIEW_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows({field: record.get(field, "") for field in csv_fields}
                         for record in merged_records)

    keeper_ids = {
        id(record): merged["record_id"]
        for group, merged in zip(groups, merged_records)
        for record in group
    }
    duplicates = []
    for group, merged in zip(groups, merged_records):
        keeper = next(
            (record for record in group if record["source"] == "Scopus"),
            group[0],
        )
        for record in group:
            if record is keeper:
                continue
            same_doi = bool(record["doi"] and record["doi"] == keeper["doi"])
            method = "same DOI" if same_doi else "exact normalized title and year"
            duplicates.append({
                "duplicate_source": record["source"],
                "duplicate_source_id": record["source_id"],
                "duplicate_title": record["title"],
                "duplicate_doi": record["doi"],
                "kept_record_id": keeper_ids[id(keeper)],
                "kept_source": keeper["source"],
                "match_method": method,
            })
    with DUPLICATES_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        fields = [
            "duplicate_source", "duplicate_source_id", "duplicate_title",
            "duplicate_doi", "kept_record_id", "kept_source", "match_method",
        ]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(duplicates)

    with DUPLICATE_CANDIDATES_FILE.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        fields = [
            "candidate_group", "source", "source_id", "title", "doi", "year",
            "abstract",
        ]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for group_number, group in enumerate(candidate_groups, start=1):
            for record in group:
                writer.writerow({
                    "candidate_group": group_number,
                    "source": record["source"],
                    "source_id": record["source_id"],
                    "title": record["title"],
                    "doi": record["doi"],
                    "year": record["year"],
                    "abstract": record["abstract"],
                })

    total_identified = sum(identified_counts.values())
    excluded_by_date = sum(date_excluded.values())
    with_abstract = sum(bool(record["abstract"]) for record in merged_records)
    prisma_rows = [
        *[
            ("Records identified", source, count,
             "Records in the supplied database export.")
            for source, count in sorted(identified_counts.items())
        ],
        ("Records identified", "All sources", total_identified,
         "Before deduplication; counts imported from supplied exports."),
        ("Records excluded before screening", "Outside 2010-2026", excluded_by_date,
         "Excluded by the agreed publication-year limit."),
        ("Records remaining after date limit", "All sources", len(raw_records),
         "Records within 2010-2026 or with no year available for manual verification."),
        ("Duplicate records removed", "All sources", len(duplicates),
         "Matched by DOI or exact normalized title/year when non-conflicting DOIs are present."),
        ("Potential duplicates needing manual check", "All sources",
         sum(len(group) for group in candidate_groups),
         "Exact title/year matches with conflicting DOIs were retained; see candidate log."),
        ("Records remaining for screening", "All sources", len(merged_records),
         "Screening has not yet been performed."),
        ("Records with abstract available", "All sources", with_abstract,
         "Abstract availability only; not an inclusion/exclusion decision."),
        ("Records without abstract", "All sources", len(merged_records) - with_abstract,
         "Retain for title/full-text assessment; do not automatically exclude."),
        ("Records screened", "All sources", "",
         "Pending ASReview/manual title and abstract screening."),
        ("Reports assessed for eligibility", "All sources", "",
         "Pending full-text review."),
        ("Studies included", "All sources", "",
         "Pending eligibility decisions."),
    ]
    with PRISMA_FILE.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["stage", "source", "records_n", "notes"])
        writer.writerows(prisma_rows)

    return len(duplicates), with_abstract


def main():
    raw_records, wos_files, identified_counts, date_excluded = load_records()
    groups, candidate_groups = group_records(raw_records)
    merged_records = [merge_group(group) for group in groups]
    duplicate_count, abstract_count = write_exports(
        merged_records, groups, candidate_groups, raw_records, wos_files,
        identified_counts, date_excluded,
    )
    print(f"Scopus records: {sum(r['source'] == 'Scopus' for r in raw_records)}")
    print(f"Web of Science files: {len(wos_files)}")
    print(f"Records within 2010-{END_YEAR}: {len(raw_records)}")
    print(f"Records outside period: {sum(date_excluded.values())}")
    print(f"Duplicates removed: {duplicate_count}")
    print(f"Unique records for screening: {len(merged_records)}")
    print(f"Records with abstract: {abstract_count}")
    print(f"Records without abstract: {len(merged_records) - abstract_count}")
    print(f"Potential duplicates for manual check: {len(candidate_groups)} groups")
    print(
        f"Created: {BIB_FILE}, {ASREVIEW_FILE}, {DUPLICATES_FILE}, "
        f"{DUPLICATE_CANDIDATES_FILE}, {PRISMA_FILE}"
    )


if __name__ == "__main__":
    main()
