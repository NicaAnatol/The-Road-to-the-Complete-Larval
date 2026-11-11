import argparse
import csv
import html
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import date
from urllib.parse import quote

import requests

API_URL = "https://api.elsevier.com/content/search/scopus"
ABSTRACT_API_URL = "https://api.elsevier.com/content/abstract/eid"
OPENALEX_API_URL = "https://api.openalex.org/works"
API_KEY = os.environ.get("ELSEVIER_API_KEY", "")

DB_FILE = "review_scopus.sqlite"
BIB_FILE = "review_scopus.bib"
CSV_FILE = "review_scopus.csv"

PAGE_SIZE = 25
MAX_RECORDS = 5000
SLEEP_BETWEEN = 0.4
ABSTRACT_COMMIT_EVERY = 10
OPENALEX_COMMIT_EVERY = 20
OPENALEX_SLEEP = 1.0
CROSSREF_API_URL = "https://api.crossref.org/works"
CROSSREF_SLEEP = 0.5

SEARCH_START_YEAR = 2010
SEARCH_END_YEAR = 2026

QUERIES = [
    '(drosophila OR "fruit fly" OR "fly") AND (larva* OR larval) AND (connectom* OR "wiring diagram" OR "synaptic connectivity")',
    'drosophila AND (larva* OR larval) AND ("electron microscopy" OR "serial section*" OR "volume EM" OR "neuron reconstruction" OR "circuit reconstruction")',
    'drosophila AND (larva* OR larval) AND ("neural circuit*" OR "neuronal circuit*") AND (connectom* OR "electron microscop*")',
]


def map_scopus_query(query):
    return (
        f"TITLE-ABS-KEY({query}) AND "
        f"PUBYEAR > {SEARCH_START_YEAR - 1} AND "
        f"PUBYEAR < {SEARCH_END_YEAR + 1}"
    )



def as_list(x):
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


def text_of(x):
    """Scopus intoarce uneori text simplu, alteori {'$': 'text'}."""
    if isinstance(x, dict):
        x = x.get("$", "")
    return str(x or "").strip()



def search_page(query, start):
    if not API_KEY:
        raise RuntimeError("API_KEY este gol.")
    headers = {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}
    params = {
        "query": map_scopus_query(query),
        "count": PAGE_SIZE,
        "start": start,
        "view": "STANDARD",
    }
    for attempt in range(5):
        r = requests.get(API_URL, headers=headers, params=params, timeout=30)
        if r.status_code == 429:
            wait = 2 ** attempt
            print(f"429 (limita de cereri), astept {wait}s")
            time.sleep(wait)
            continue
        if r.status_code in (401, 403):
            raise SystemExit(
                f"Cautarea Scopus a esuat cu HTTP {r.status_code}. Verifica accesul "
                f"cheii la Search API.\n{r.text[:300]}"
            )
        r.raise_for_status()
        return r.json()["search-results"]
    raise RuntimeError("Prea multe reincercari la API.")


def fetch_query(query):
    """Returneaza (total_gasit, lista_de_inregistrari_brute)."""
    start, records, total = 0, [], None
    while True:
        data = search_page(query, start)
        if total is None:
            total = int(data.get("opensearch:totalResults", 0))
            print(f"  Total gasit: {total}")
        entries = data.get("entry", [])

        if not entries or "error" in entries[0]:
            break
        records.extend(entries)
        start += len(entries)
        if start >= min(total, MAX_RECORDS):
            break
        time.sleep(SLEEP_BETWEEN)
    return total, records[:MAX_RECORDS]



class AbstractAccessError(RuntimeError):
    pass


def parse_abstract_response(payload):
    """Extrage abstract, lista completa de autori si keywords din raspunsul Abstract Retrieval."""
    coredata = payload.get("coredata", {}) or {}
    abstract = text_of(coredata.get("dc:description", ""))

    authors = []
    for a in as_list((payload.get("authors") or {}).get("author")):
        if not isinstance(a, dict):
            continue
        sur = text_of(a.get("ce:surname"))
        ini = text_of(a.get("ce:initials")) or text_of(a.get("ce:given-name"))
        if sur and ini:
            authors.append(f"{sur}, {ini}")
        elif sur:
            authors.append(sur)
        elif a.get("ce:indexed-name"):
            authors.append(text_of(a["ce:indexed-name"]))

    kws = []
    raw = payload.get("authkeywords")
    if isinstance(raw, dict):
        raw = raw.get("author-keyword")
    for k in as_list(raw):
        t = text_of(k)
        if t:
            kws.append(t)

    return {"abstract": abstract, "authors": " and ".join(authors), "keywords": "; ".join(kws)}


def fetch_abstract(eid):
    """Returneaza dict cu abstract/authors/keywords, {} daca nu exista (404),
    sau None daca a esuat temporar (se reincearca la urmatoarea rulare)."""
    headers = {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}
    params = {"view": "META_ABS"}
    url = f"{ABSTRACT_API_URL}/{eid}"
    for attempt in range(5):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  Eroare de retea la {eid}: {e}; reincerc")
            time.sleep(2 ** attempt)
            continue
        if response.status_code == 429:
            wait = 2 ** attempt
            print(f"429 (limita cereri abstract), astept {wait}s")
            time.sleep(wait)
            continue
        if response.status_code in (401, 403):
            raise AbstractAccessError(
                f"Abstract Retrieval API a refuzat accesul (HTTP {response.status_code}). "
                "Cheia sau institutia ta poate sa nu aiba drepturi pentru abstracte. "
                "Incearca din reteaua universitatii / VPN."
            )
        if response.status_code == 404:
            return {}
        if response.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return parse_abstract_response(response.json().get("abstracts-retrieval-response", {}))
    return None


def fill_missing_abstracts(con):
    rows = con.execute(
        """SELECT eid FROM records
           WHERE (abstract IS NULL OR abstract = '') AND COALESCE(abstract_checked, 0) = 0
           ORDER BY eid"""
    ).fetchall()
    retrieved = failed = 0
    try:
        for index, (eid,) in enumerate(rows, start=1):
            info = fetch_abstract(eid)
            if info is None:
                failed += 1
            else:
                if info.get("abstract"):
                    retrieved += 1
                con.execute(
                    """UPDATE records SET
                           abstract = COALESCE(NULLIF(?, ''), abstract),
                           authors = COALESCE(NULLIF(?, ''), authors),
                           keywords = CASE WHEN keywords IS NULL OR keywords = ''
                                           THEN ? ELSE keywords END,
                           abstract_checked = 1
                       WHERE eid = ?""",
                    (info.get("abstract", ""), info.get("authors", ""),
                     info.get("keywords", ""), eid),
                )
            if index % ABSTRACT_COMMIT_EVERY == 0:
                con.commit()
                print(f"  Abstracte verificate: {index}/{len(rows)}")
            if index < len(rows):
                time.sleep(SLEEP_BETWEEN)
    finally:
        con.commit()
    return retrieved, len(rows), failed



def restore_openalex_abstract(inverted_index):
    if not isinstance(inverted_index, dict):
        return ""
    words_by_position = {}
    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                words_by_position[position] = word
    return " ".join(words_by_position[position]
                    for position in sorted(words_by_position))


def normalized_title(title):
    normalized = unicodedata.normalize("NFKC", str(title or "")).casefold()
    return re.sub(r"[\W_]+", "", normalized)


def openalex_get(url, params=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "ScopusAbstractExport/1.0",
    }
    for attempt in range(6):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
            continue
        if response.status_code == 404:
            return None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == 5:
                response.raise_for_status()
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 5 * (2 ** attempt)
                except ValueError:
                    wait = 5 * (2 ** attempt)
                time.sleep(min(wait, 60))
            else:
                time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return response.json()
    return None


def fetch_openalex_abstract(doi, title, year):
    fields = "doi,title,publication_year,abstract_inverted_index"
    work = None
    if doi:
        doi_path = quote(doi.strip(), safe="/")
        work = openalex_get(
            f"{OPENALEX_API_URL}/https://doi.org/{doi_path}",
            params={"select": fields},
        )

    abstract = restore_openalex_abstract(
        (work or {}).get("abstract_inverted_index")
    )
    if abstract:
        return abstract
    if not title:
        return ""
    result = openalex_get(
        OPENALEX_API_URL,
        params={"search": title, "per-page": 5, "select": fields},
    )
    if not result:
        return ""

    target_title = normalized_title(title)
    try:
        target_year = int(year)
    except (TypeError, ValueError):
        target_year = None
    for candidate in result.get("results", []):
        if normalized_title(candidate.get("title")) != target_title:
            continue
        candidate_year = candidate.get("publication_year")
        if target_year and candidate_year and abs(target_year - candidate_year) > 1:
            continue
        abstract = restore_openalex_abstract(
            candidate.get("abstract_inverted_index")
        )
        if abstract:
            return abstract
    return ""


def fill_openalex_abstracts(con):
    rows = con.execute(
        """SELECT eid, doi, title, year FROM records
           WHERE (abstract IS NULL OR abstract = '')
             AND COALESCE(openalex_checked, 0) = 0
           ORDER BY eid"""
    ).fetchall()
    retrieved = failed = consecutive_failures = processed = 0
    try:
        for index, (eid, doi, title, year) in enumerate(rows, start=1):
            try:
                abstract = fetch_openalex_abstract(doi, title, year)
            except (requests.RequestException, RuntimeError) as error:
                failed += 1
                consecutive_failures += 1
                processed += 1
                print(f"  OpenAlex request failed for {eid}: {error}")
                if consecutive_failures >= 3:
                    print("  Stopping after repeated OpenAlex errors; rerun to resume.")
                    break
            else:
                consecutive_failures = 0
                processed += 1
                if abstract:
                    con.execute(
                        """UPDATE records
                           SET abstract = ?, openalex_checked = 1
                           WHERE eid = ? AND (abstract IS NULL OR abstract = '')""",
                        (abstract, eid),
                    )
                    retrieved += 1
                else:
                    con.execute(
                        "UPDATE records SET openalex_checked = 1 WHERE eid = ?",
                        (eid,),
                    )
            if processed % OPENALEX_COMMIT_EVERY == 0:
                con.commit()
                print(f"  OpenAlex records checked: {processed}/{len(rows)}")
            if index < len(rows):
                time.sleep(OPENALEX_SLEEP)
    finally:
        con.commit()
    return retrieved, processed, failed


def fill_openalex_title_fallbacks(con):
    rows = con.execute(
        """SELECT eid, title, year FROM records
           WHERE (abstract IS NULL OR abstract = '')
             AND COALESCE(openalex_title_checked, 0) = 0
           ORDER BY eid"""
    ).fetchall()
    retrieved = failed = processed = consecutive_failures = 0
    try:
        for index, (eid, title, year) in enumerate(rows, start=1):
            try:
                abstract = fetch_openalex_abstract("", title, year)
            except (requests.RequestException, RuntimeError) as error:
                failed += 1
                processed += 1
                consecutive_failures += 1
                print(f"  OpenAlex title lookup failed for {eid}: {error}")
                if consecutive_failures >= 3:
                    print("  Stopping after repeated OpenAlex errors; rerun to resume.")
                    break
            else:
                processed += 1
                consecutive_failures = 0
                con.execute(
                    """UPDATE records
                       SET abstract = COALESCE(NULLIF(?, ''), abstract),
                           openalex_title_checked = 1
                       WHERE eid = ?""",
                    (abstract, eid),
                )
                if abstract:
                    retrieved += 1
            if processed % OPENALEX_COMMIT_EVERY == 0:
                con.commit()
                print(f"  OpenAlex title matches checked: {processed}/{len(rows)}")
            if index < len(rows):
                time.sleep(OPENALEX_SLEEP)
    finally:
        con.commit()
    return retrieved, processed, failed


class CrossrefRateLimit(RuntimeError):
    pass


def fetch_crossref_abstract(doi):
    if not doi:
        return ""
    url = f"{CROSSREF_API_URL}/{quote(doi.strip(), safe='')}"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "ScopusAbstractExport/1.0"},
            timeout=30,
        )
    except requests.RequestException:
        raise
    if response.status_code == 404:
        return ""
    if response.status_code == 429:
        raise CrossrefRateLimit("Crossref rate limit reached; rerun later to resume.")
    response.raise_for_status()
    markup = response.json().get("message", {}).get("abstract", "")
    text = re.sub(r"<[^>]+>", " ", str(markup))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fill_crossref_abstracts(con):
    rows = con.execute(
        """SELECT eid, doi FROM records
           WHERE (abstract IS NULL OR abstract = '')
             AND COALESCE(crossref_checked, 0) = 0
           ORDER BY eid"""
    ).fetchall()
    retrieved = failed = processed = 0
    try:
        for index, (eid, doi) in enumerate(rows, start=1):
            try:
                abstract = fetch_crossref_abstract(doi)
            except CrossrefRateLimit as error:
                print(f"  {error}")
                break
            except requests.RequestException as error:
                failed += 1
                processed += 1
                print(f"  Crossref request failed for {eid}: {error}")
            else:
                processed += 1
                con.execute(
                    """UPDATE records
                       SET abstract = COALESCE(NULLIF(?, ''), abstract),
                           crossref_checked = 1
                       WHERE eid = ?""",
                    (abstract, eid),
                )
                if abstract:
                    retrieved += 1
            if processed % OPENALEX_COMMIT_EVERY == 0:
                con.commit()
                print(f"  Crossref records checked: {processed}/{len(rows)}")
            if index < len(rows):
                time.sleep(CROSSREF_SLEEP)
    finally:
        con.commit()
    return retrieved, processed, failed



def parse_entry(e):
    raw_keywords = e.get("authkeywords", "")
    keywords_list = []


    if isinstance(raw_keywords, list):
        for item in raw_keywords:
            t = text_of(item)
            if t:
                keywords_list.append(t)
    elif isinstance(raw_keywords, str):
        keywords_list = [k.strip() for k in raw_keywords.split("|") if k.strip()]

    return {
        "eid": str(e.get("eid", "") or ""),
        "title": str(e.get("dc:title", "") or ""),

        "first_author": str(e.get("dc:creator", "") or ""),
        "year": str(e.get("prism:coverDate", "") or "")[:4],
        "journal": str(e.get("prism:publicationName", "") or ""),
        "volume": str(e.get("prism:volume", "") or ""),
        "pages": str(e.get("prism:pageRange", "") or ""),
        "doi": str(e.get("prism:doi", "") or ""),
        "doc_type": str(e.get("subtypeDescription", "") or ""),
        "cited_by": str(e.get("citedby-count", "0") or "0"),
        "keywords": "; ".join(keywords_list),
        "abstract": str(e.get("dc:description", "") or "").strip(),
    }



def init_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS records (
            eid TEXT PRIMARY KEY,
            title TEXT,
            first_author TEXT,
            year TEXT,
            journal TEXT,
            volume TEXT,
            pages TEXT,
            doi TEXT,
            doc_type TEXT,
            cited_by TEXT,
            keywords TEXT,
            abstract TEXT,
            first_query TEXT,
            run_date TEXT,
            raw_json TEXT
        )""")

    existing = {row[1] for row in con.execute("PRAGMA table_info(records)").fetchall()}
    for col, ddl in [("abstract", "TEXT"), ("authors", "TEXT"),
                      ("abstract_checked", "INTEGER DEFAULT 0"),
                      ("openalex_checked", "INTEGER DEFAULT 0"),
                      ("openalex_title_checked", "INTEGER DEFAULT 0"),
                      ("crossref_checked", "INTEGER DEFAULT 0")]:
        if col not in existing:
            con.execute(f"ALTER TABLE records ADD COLUMN {col} {ddl}")
    con.execute("""
        CREATE TABLE IF NOT EXISTS search_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            query TEXT,
            total_found INTEGER,
            retrieved INTEGER,
            new_records INTEGER
        )""")
    con.commit()


def save_records(con, query, run_date, raw_records):
    new = 0
    for e in raw_records:
        p = parse_entry(e)
        if not p["eid"]:
            continue
        cur = con.execute(
            """INSERT OR IGNORE INTO records
               (eid, title, first_author, year, journal, volume, pages, doi,
                doc_type, cited_by, keywords, abstract, first_query, run_date, raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p["eid"], p["title"], p["first_author"], p["year"], p["journal"],
             p["volume"], p["pages"], p["doi"], p["doc_type"], p["cited_by"],
             p["keywords"], p["abstract"], query, run_date,
             json.dumps(e, ensure_ascii=False)),
        )
        new += cur.rowcount
        if cur.rowcount == 0 and p["abstract"]:
            con.execute(
                """UPDATE records SET abstract = ?, raw_json = ?
                   WHERE eid = ? AND (abstract IS NULL OR abstract = '')""",
                (p["abstract"], json.dumps(e, ensure_ascii=False), p["eid"]),
            )
    con.commit()
    return new



def ascii_key(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", s)


def esc(s):
    s = str(s or "")
    for ch in ["&", "%", "$", "#", "_", "{", "}"]:
        s = s.replace(ch, "\\" + ch)
    return s


def export_all(con):
    rows = con.execute(
        """SELECT eid, title, first_author, authors, year, journal, volume, pages, doi,
                  doc_type, cited_by, keywords, abstract
           FROM records ORDER BY year DESC, title ASC"""
    ).fetchall()

    used, bib_chunks, csv_rows = {}, [], []
    for (eid, title, first_author, authors, year, journal, volume, pages,
         doi, doc_type, cited_by, keywords, abstract) in rows:

        author_field = authors or first_author
        lead = (authors.split(" and ")[0].split(",")[0] if authors
                else (first_author.split()[0] if first_author else "anon"))
        words = re.findall(r"[A-Za-z]+", title or "")
        word = words[0].lower() if words else "work"
        base = f"{ascii_key(lead).lower() or 'anon'}{year or 'nd'}{word}"
        n = used.get(base, 0)
        used[base] = n + 1
        key = base if n == 0 else f"{base}{chr(97 + n)}"

        t = str(doc_type or "").lower()
        is_conf = "conference" in t or "proceeding" in t
        kind = "inproceedings" if is_conf else "article"
        venue = "booktitle" if is_conf else "journal"

        fields = [
            ("author", author_field),
            ("title", title),
            (venue, journal),
            ("year", year),
            ("volume", volume),
            ("pages", pages),
            ("doi", doi),
            ("keywords", keywords),
            ("abstract", abstract),
            ("note", f"Scopus EID: {eid} | Citations: {cited_by or 0}"),
        ]
        body = ",\n".join(f"  {k} = {{{esc(v)}}}" for k, v in fields if v)
        bib_chunks.append(f"@{kind}{{{key},\n{body}\n}}")

        csv_rows.append({
            "eid": eid, "year": year, "title": title, "abstract": abstract,
            "authors": author_field, "journal": journal, "doc_type": doc_type,
            "cited_by": cited_by, "doi": doi, "keywords": keywords,
        })

    with open(BIB_FILE, "w", encoding="utf-8") as f:
        f.write("\n\n".join(bib_chunks) + "\n")

    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "eid", "year", "title", "abstract", "authors", "journal",
            "doc_type", "cited_by", "doi", "keywords"])
        w.writeheader()
        w.writerows(csv_rows)

    return len(rows)



def main(openalex_only=False, crossref_only=False):
    if not openalex_only and not crossref_only and not API_KEY:
        raise RuntimeError("API_KEY este gol.")
    print("Pornesc verificarea Crossref..." if crossref_only
          else "Pornesc exportul OpenAlex..." if openalex_only
          else "Pornesc exportul Scopus...")

    run_date = date.today().isoformat()
    con = sqlite3.connect(DB_FILE)
    init_db(con)

    try:
        if not openalex_only and not crossref_only:
            for q in QUERIES:
                print(f"Caut: {q[:80]}...")
                mapped_query = map_scopus_query(q)
                total, raw = fetch_query(q)
                new = save_records(con, mapped_query, run_date, raw)
                con.execute(
                    "INSERT INTO search_log (run_date, query, total_found, retrieved, new_records) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_date, mapped_query, total, len(raw), new),
                )
                con.commit()
                print(f"  Recuperate: {len(raw)} | Noi in baza: {new}")

            try:
                got, checked, failed = fill_missing_abstracts(con)
                print(f"Abstracte gasite: {got} din {checked} verificate "
                      f"({failed} esuate temporar - rularea din nou le reia)")
            except AbstractAccessError as error:
                print(f"ATENTIE: {error}")
                print("Se incearca acum recuperarea abstractelor din OpenAlex.")

        if not crossref_only:
            got, checked, failed = fill_openalex_abstracts(con)
            print(f"Abstracte OpenAlex gasite: {got} din {checked} verificate "
                  f"({failed} erori temporare)")
            title_got, title_checked, title_failed = fill_openalex_title_fallbacks(con)
            print(f"Abstracte gasite prin potrivire exacta a titlului: "
                  f"{title_got} din {title_checked} verificate "
                  f"({title_failed} erori temporare)")

        crossref_got, crossref_checked, crossref_failed = fill_crossref_abstracts(con)
        print(f"Abstracte Crossref gasite: {crossref_got} din {crossref_checked} verificate "
              f"({crossref_failed} erori temporare)")

        n = export_all(con)
        with_abstract = con.execute(
            "SELECT COUNT(*) FROM records WHERE abstract IS NOT NULL AND abstract != ''"
        ).fetchone()[0]
        with_kw = con.execute(
            "SELECT COUNT(*) FROM records WHERE keywords IS NOT NULL AND keywords != ''"
        ).fetchone()[0]
        with_authors = con.execute(
            "SELECT COUNT(*) FROM records WHERE authors IS NOT NULL AND authors != ''"
        ).fetchone()[0]
    finally:
        con.close()
    print(f"\nInregistrari unice in baza: {n}")
    print(f"Cu abstract: {with_abstract}/{n} | cu keywords: {with_kw}/{n} | cu lista completa de autori: {with_authors}/{n}")
    print(f"Fisiere create: {DB_FILE}, {BIB_FILE}, {CSV_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openalex-only",
        action="store_true",
        help="Completeaza abstractele lipsa din baza existenta folosind OpenAlex.",
    )
    parser.add_argument(
        "--crossref-only",
        action="store_true",
        help="Completeaza abstractele lipsa din baza existenta folosind Crossref.",
    )
    args = parser.parse_args()
    if args.openalex_only and args.crossref_only:
        parser.error("Choose only one abstract provider.")
    main(openalex_only=args.openalex_only, crossref_only=args.crossref_only)