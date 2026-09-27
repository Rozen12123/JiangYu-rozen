#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = ROOT / "_data" / "publication_overrides.json"
OUTPUT_PATH = ROOT / "_data" / "publications.json"
USER_AGENT = "JiangYuAcademicHomepage/1.1 (https://github.com/Rozen12123/JiangYu-rozen)"
REJECTED = ("submitted to", "under review", "withdrawn", "rejected", "desk rejected")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unwrap(v):
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def norm_title(s):
    s = html.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def norm_name(s):
    return re.sub(r"[^a-z]+", " ", str(s or "").lower()).strip()


def year_from(*values):
    for value in values:
        if isinstance(value, int) and 1900 <= value <= 2100:
            return value
        m = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
        if m:
            return int(m.group(0))
    return 0


def format_authors(names, profile, ids=None, orcids=None):
    ids, orcids = ids or [], orcids or []
    out = []
    for i, raw in enumerate(names or []):
        name = str(raw).strip()
        is_user = norm_name(name) in {norm_name(profile["name"]), "j yu"}
        if i < len(ids) and ids[i] == profile.get("openreview_id"):
            is_user = True
        if i < len(orcids):
            oid = str(orcids[i] or "").replace("https://orcid.org/", "")
            if oid and oid == profile.get("orcid"):
                is_user = True
        safe = html.escape(name)
        out.append(f"<strong>{safe}</strong>" if is_user else safe)
    return ", ".join(out)


def merge_record(records, candidate, overwrite=False):
    title = candidate.get("title", "").strip()
    if not title:
        return
    key = norm_title(title)
    best_i, best = None, 0.0
    for i, r in enumerate(records):
        score = SequenceMatcher(None, key, norm_title(r.get("title", ""))).ratio()
        if score > best:
            best_i, best = i, score
    if best_i is not None and best >= 0.94:
        target = records[best_i]
        if overwrite:
            merged = dict(target)
            merged.update({k: v for k, v in candidate.items() if v not in (None, "", [])})
            merged["sources"] = sorted(set(target.get("sources", [])) | set(candidate.get("sources", [])))
            records[best_i] = merged
        else:
            for k, v in candidate.items():
                if k == "sources":
                    target["sources"] = sorted(set(target.get("sources", [])) | set(v or []))
                elif v not in (None, "", []) and not target.get(k):
                    target[k] = v
        return
    records.append(candidate)


def public_venue(venue):
    v = str(venue or "").strip().lower()
    return bool(v) and not any(x in v for x in REJECTED)


def discover_openreview(profile, errors):
    out = []
    try:
        import openreview
        client = openreview.api.OpenReviewClient(baseurl="https://api2.openreview.net")
        notes = client.get_all_notes(content={"authorids": profile["openreview_id"]})
        for note in notes:
            c = note.content or {}
            title = unwrap(c.get("title"))
            if isinstance(title, list):
                title = title[0] if title else ""
            title = str(title or "").strip()
            venue = unwrap(c.get("venue"))
            if isinstance(venue, list):
                venue = venue[0] if venue else ""
            venue = str(venue or "").strip()
            if not title or not public_venue(venue):
                continue

            authors = unwrap(c.get("authors")) or []
            authorids = unwrap(c.get("authorids")) or []
            if isinstance(authors, str):
                authors = [authors]
            if isinstance(authorids, str):
                authorids = [authorids]

            y = year_from(unwrap(c.get("year")), venue)
            note_id = getattr(note, "id", None) or getattr(note, "forum", None)
            url = f"https://openreview.net/forum?id={urllib.parse.quote(str(note_id))}" if note_id else ""
            out.append({
                "title": title,
                "authors_html": format_authors(authors, profile, ids=authorids),
                "venue": venue,
                "year": y,
                "url": url,
                "award": "",
                "priority": 999,
                "curated": False,
                "sources": ["openreview"],
            })
    except Exception as exc:
        errors.append(f"OpenReview failed: {exc}")
    return out


def discover_scholar(profile, errors):
    out = []
    try:
        from scholarly import scholarly
        author = scholarly.search_author_id(profile["scholar_id"])
        scholarly.fill(author, sections=["basics", "publications"])
        for pub in author.get("publications", []):
            bib = pub.get("bib") or {}
            title = str(bib.get("title") or "").strip()
            if not title:
                continue
            raw_authors = bib.get("author") or bib.get("authors") or ""
            if isinstance(raw_authors, str):
                if " and " in raw_authors:
                    authors = [x.strip() for x in raw_authors.split(" and ") if x.strip()]
                else:
                    authors = [x.strip() for x in raw_authors.split(",") if x.strip()]
            else:
                authors = list(raw_authors or [])

            y = year_from(bib.get("pub_year"), bib.get("year"))
            venue = (
                bib.get("venue")
                or bib.get("journal")
                or bib.get("conference")
                or bib.get("citation")
                or ""
            )
            venue = str(venue).strip()
            if y and venue and str(y) not in venue:
                venue = f"{venue} {y}"
            elif not venue and y:
                venue = str(y)

            url = str(pub.get("pub_url") or pub.get("eprint_url") or "")
            out.append({
                "title": title,
                "authors_html": format_authors(authors, profile),
                "venue": venue,
                "year": y,
                "url": url,
                "award": "",
                "priority": 999,
                "curated": False,
                "sources": ["google-scholar"],
            })
    except Exception as exc:
        errors.append(f"Google Scholar failed: {exc}")
    return out


def discover_crossref(profile, errors):
    try:
        params = urllib.parse.urlencode({"filter": f"orcid:{profile['orcid']}", "rows": 100})
        data = fetch_json("https://api.crossref.org/works?" + params)
    except Exception as exc:
        errors.append(f"Crossref failed: {exc}")
        return []

    out = []
    for item in ((data.get("message") or {}).get("items") or []):
        titles = item.get("title") or []
        title = str(titles[0] if titles else "").strip()
        if not title:
            continue
        names, orcids = [], []
        for a in item.get("author") or []:
            name = " ".join(x for x in (a.get("given", ""), a.get("family", "")) if x).strip()
            if name:
                names.append(name)
                orcids.append(a.get("ORCID", ""))

        y = 0
        for key in ("published-print", "published-online", "issued"):
            parts = (item.get(key) or {}).get("date-parts") or []
            if parts and parts[0] and isinstance(parts[0][0], int):
                y = parts[0][0]
                break
        containers = item.get("container-title") or []
        container = str(containers[0] if containers else "").strip()
        venue = f"{container} {y}".strip() if container else (str(y) if y else "")
        doi = item.get("DOI")
        url = f"https://doi.org/{doi}" if doi else str(item.get("URL") or "")
        out.append({
            "title": title,
            "authors_html": format_authors(names, profile, orcids=orcids),
            "venue": venue,
            "year": y,
            "url": url,
            "award": "",
            "priority": 999,
            "curated": False,
            "sources": ["crossref"],
        })
    return out


def discover_openalex(profile, errors):
    try:
        params = urllib.parse.urlencode({"filter": f"orcid:{profile['orcid']}"})
        authors = fetch_json("https://api.openalex.org/authors?" + params).get("results") or []
        if not authors:
            return []
        aid = str(authors[0].get("id") or "").rsplit("/", 1)[-1]
        if not aid:
            return []
        params = urllib.parse.urlencode({"filter": f"author.id:{aid}", "per-page": 200})
        works = fetch_json("https://api.openalex.org/works?" + params).get("results") or []
    except Exception as exc:
        errors.append(f"OpenAlex failed: {exc}")
        return []

    out = []
    for w in works:
        title = str(w.get("title") or "").strip()
        if not title:
            continue
        names, orcids = [], []
        for authorship in w.get("authorships") or []:
            a = authorship.get("author") or {}
            if a.get("display_name"):
                names.append(a["display_name"])
                orcids.append(a.get("orcid") or "")
        y = int(w.get("publication_year") or 0)
        source = (((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "")
        venue = f"{source} {y}".strip() if source else (str(y) if y else "")
        url = str(w.get("doi") or w.get("id") or "")
        out.append({
            "title": title,
            "authors_html": format_authors(names, profile, orcids=orcids),
            "venue": venue,
            "year": y,
            "url": url,
            "award": "",
            "priority": 999,
            "curated": False,
            "sources": ["openalex"],
        })
    return out


def main():
    config = load_json(OVERRIDES_PATH, {})
    profile = config["profile"]
    curated = config.get("overrides", [])
    existing = load_json(OUTPUT_PATH, [])

    records = []
    for r in existing:
        if not r.get("curated"):
            merge_record(records, r)

    errors = []
    discovered = []
    discovered.extend(discover_openreview(profile, errors))
    discovered.extend(discover_scholar(profile, errors))
    discovered.extend(discover_crossref(profile, errors))
    discovered.extend(discover_openalex(profile, errors))

    for r in discovered:
        merge_record(records, r, overwrite=True)

    for o in curated:
        aliases = o.get("aliases") or [o.get("title", "")]
        match_i = None
        for i, r in enumerate(records):
            if any(SequenceMatcher(None, norm_title(a), norm_title(r.get("title", ""))).ratio() >= 0.94 for a in aliases):
                match_i = i
                break
        curated_record = {
            "title": o["title"],
            "authors_html": o["authors_html"],
            "venue": o["venue"],
            "year": o["year"],
            "url": o["url"],
            "award": o.get("award", ""),
            "priority": o.get("priority", 100),
            "curated": True,
            "sources": ["curated"],
        }
        if match_i is not None:
            curated_record["sources"] = sorted(set(records[match_i].get("sources", [])) | {"curated"})
            records[match_i] = curated_record
        else:
            records.append(curated_record)

    final = []
    for r in records:
        merge_record(final, r, overwrite=bool(r.get("curated")))
    final.sort(key=lambda p: (-int(p.get("year") or 0), int(p.get("priority") or 999), norm_title(p.get("title", ""))))

    text = json.dumps(final, ensure_ascii=False, indent=2) + "\n"
    old = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
    if text != old:
        OUTPUT_PATH.write_text(text, encoding="utf-8")
        print(f"Updated publication list: {len(final)} records.")
    else:
        print(f"No publication changes ({len(final)} records).")
    print(f"Discovered this run: {len(discovered)} records.")
    for e in errors:
        print("WARNING:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
