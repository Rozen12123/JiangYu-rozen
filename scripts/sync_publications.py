#!/usr/bin/env python3
"""Synchronize public publications from OpenReview, Crossref, and OpenAlex.

Curated overrides always win for contribution marks, awards, venue wording,
links, and display order. Existing auto-discovered records are never deleted
just because an external API is temporarily unavailable.
"""

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

USER_AGENT = (
    "JiangYuAcademicHomepage/1.0 "
    "(https://github.com/Rozen12123/JiangYu-rozen)"
)

REJECTED_VENUE_MARKERS = (
    "submitted to",
    "under review",
    "withdrawn",
    "rejected",
    "desk rejected",
)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def fetch_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def unwrap(value):
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def norm_title(title: str) -> str:
    title = html.unescape(title or "")
    title = re.sub(r"<[^>]+>", " ", title)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z]+", " ", (name or "").lower()).strip()


def year_from(*values):
    for value in values:
        if isinstance(value, int) and 1900 <= value <= 2100:
            return value
        if isinstance(value, str):
            m = re.search(r"\b(19|20)\d{2}\b", value)
            if m:
                return int(m.group(0))
    return None


def format_authors(names, ids=None, orcids=None, profile_name="Jiang Yu",
                   profile_openreview="", profile_orcid=""):
    ids = ids or []
    orcids = orcids or []
    out = []
    for i, raw_name in enumerate(names or []):
        name = str(raw_name).strip()
        is_user = False
        if i < len(ids) and ids[i] == profile_openreview:
            is_user = True
        if i < len(orcids):
            oid = (orcids[i] or "").replace("https://orcid.org/", "")
            if oid and oid == profile_orcid:
                is_user = True
        if norm_name(name) in {norm_name(profile_name), "j yu"}:
            is_user = True
        safe = html.escape(name)
        out.append(f"<strong>{safe}</strong>" if is_user else safe)
    return ", ".join(out)


def is_public_venue(venue: str) -> bool:
    v = (venue or "").strip().lower()
    if not v:
        return False
    return not any(marker in v for marker in REJECTED_VENUE_MARKERS)


def merge_record(records, candidate, overwrite=False):
    title = candidate.get("title", "").strip()
    if not title:
        return

    nk = norm_title(title)
    best_i = None
    best_score = 0.0
    for i, record in enumerate(records):
        score = SequenceMatcher(None, nk, norm_title(record.get("title", ""))).ratio()
        if score > best_score:
            best_score, best_i = score, i

    if best_i is not None and best_score >= 0.94:
        target = records[best_i]
        if overwrite:
            merged = dict(target)
            merged.update({k: v for k, v in candidate.items() if v not in (None, "", [])})
            old_sources = set(target.get("sources", []))
            new_sources = set(candidate.get("sources", []))
            merged["sources"] = sorted(old_sources | new_sources)
            records[best_i] = merged
        else:
            for key, value in candidate.items():
                if key == "sources":
                    target["sources"] = sorted(set(target.get("sources", [])) | set(value or []))
                elif value not in (None, "", []) and not target.get(key):
                    target[key] = value
        return

    records.append(candidate)


def discover_openreview(profile, errors):
    oid = profile["openreview_id"]
    params = urllib.parse.urlencode({"content.authorids": oid, "limit": 1000})
    endpoints = [
        "https://api2.openreview.net/notes?" + params,
        "https://api.openreview.net/notes?" + params,
    ]

    data = None
    for url in endpoints:
        try:
            candidate = fetch_json(url)
            if isinstance(candidate, dict) and isinstance(candidate.get("notes"), list):
                data = candidate
                break
        except Exception as exc:
            errors.append(f"OpenReview endpoint failed: {exc}")

    if data is None:
        return []

    out = []
    for note in data.get("notes", []):
        content = note.get("content") or {}
        title = unwrap(content.get("title"))
        if isinstance(title, list):
            title = title[0] if title else ""
        title = str(title or "").strip()
        if not title:
            continue

        venue = unwrap(content.get("venue"))
        if isinstance(venue, list):
            venue = venue[0] if venue else ""
        venue = str(venue or "").strip()

        if not is_public_venue(venue):
            continue

        authors = unwrap(content.get("authors")) or []
        authorids = unwrap(content.get("authorids")) or []
        if isinstance(authors, str):
            authors = [authors]
        if isinstance(authorids, str):
            authorids = [authorids]

        year = year_from(unwrap(content.get("year")), venue)
        if year is None:
            for ts_key in ("pdate", "cdate", "mdate"):
                ts = note.get(ts_key)
                if isinstance(ts, (int, float)) and ts > 0:
                    from datetime import datetime, timezone
                    year = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).year
                    break

        note_id = note.get("id") or note.get("forum")
        url = f"https://openreview.net/forum?id={urllib.parse.quote(str(note_id))}" if note_id else ""

        out.append({
            "title": title,
            "authors_html": format_authors(
                authors,
                ids=authorids,
                profile_name=profile["name"],
                profile_openreview=profile["openreview_id"],
                profile_orcid=profile["orcid"],
            ),
            "venue": venue,
            "year": year or 0,
            "url": url,
            "award": "",
            "priority": 999,
            "curated": False,
            "sources": ["openreview"],
        })
    return out


def crossref_year(item):
    for key in ("published-print", "published-online", "issued", "created"):
        obj = item.get(key) or {}
        parts = obj.get("date-parts") or []
        if parts and parts[0]:
            y = parts[0][0]
            if isinstance(y, int):
                return y
    return 0


def discover_crossref(profile, errors):
    params = urllib.parse.urlencode({
        "filter": f"orcid:{profile['orcid']}",
        "rows": 100,
    })
    url = "https://api.crossref.org/works?" + params
    try:
        data = fetch_json(url)
    except Exception as exc:
        errors.append(f"Crossref failed: {exc}")
        return []

    items = (((data or {}).get("message") or {}).get("items") or [])
    out = []
    for item in items:
        titles = item.get("title") or []
        title = str(titles[0] if titles else "").strip()
        if not title:
            continue

        names, orcids = [], []
        for author in item.get("author") or []:
            name = " ".join(
                x for x in [author.get("given", ""), author.get("family", "")] if x
            ).strip()
            if name:
                names.append(name)
                orcids.append(author.get("ORCID", ""))

        year = crossref_year(item)
        containers = item.get("container-title") or []
        container = str(containers[0] if containers else "").strip()
        venue = f"{container} {year}".strip() if container else (str(year) if year else "")
        doi = item.get("DOI")
        url = f"https://doi.org/{doi}" if doi else (item.get("URL") or "")

        out.append({
            "title": title,
            "authors_html": format_authors(
                names,
                orcids=orcids,
                profile_name=profile["name"],
                profile_openreview=profile["openreview_id"],
                profile_orcid=profile["orcid"],
            ),
            "venue": venue,
            "year": year,
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
        author_data = fetch_json("https://api.openalex.org/authors?" + params)
        authors = author_data.get("results") or []
        if not authors:
            return []
        author_id = authors[0].get("id", "").rsplit("/", 1)[-1]
        if not author_id:
            return []

        params = urllib.parse.urlencode({
            "filter": f"author.id:{author_id}",
            "per-page": 200,
        })
        data = fetch_json("https://api.openalex.org/works?" + params)
    except Exception as exc:
        errors.append(f"OpenAlex failed: {exc}")
        return []

    out = []
    for work in data.get("results") or []:
        title = str(work.get("title") or "").strip()
        if not title:
            continue

        names, orcids = [], []
        for authorship in work.get("authorships") or []:
            author = authorship.get("author") or {}
            name = str(author.get("display_name") or "").strip()
            if name:
                names.append(name)
                orcids.append(author.get("orcid") or "")

        year = int(work.get("publication_year") or 0)
        source = (((work.get("primary_location") or {}).get("source") or {}).get("display_name") or "")
        venue = f"{source} {year}".strip() if source else (str(year) if year else "")
        doi = str(work.get("doi") or "").strip()
        url = doi if doi.startswith("http") else str(work.get("id") or "")

        out.append({
            "title": title,
            "authors_html": format_authors(
                names,
                orcids=orcids,
                profile_name=profile["name"],
                profile_openreview=profile["openreview_id"],
                profile_orcid=profile["orcid"],
            ),
            "venue": venue,
            "year": year,
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
    for record in existing:
        if not record.get("curated"):
            merge_record(records, record, overwrite=False)

    errors = []
    discovered = []
    discovered.extend(discover_openreview(profile, errors))
    discovered.extend(discover_crossref(profile, errors))
    discovered.extend(discover_openalex(profile, errors))

    for record in discovered:
        merge_record(records, record, overwrite=True)

    for override in curated:
        aliases = override.get("aliases") or [override.get("title", "")]
        matched = False
        for alias in aliases:
            nk = norm_title(alias)
            for i, record in enumerate(records):
                score = SequenceMatcher(None, nk, norm_title(record.get("title", ""))).ratio()
                if score >= 0.94:
                    old_sources = set(record.get("sources", []))
                    new_record = {
                        "title": override["title"],
                        "authors_html": override["authors_html"],
                        "venue": override["venue"],
                        "year": override["year"],
                        "url": override["url"],
                        "award": override.get("award", ""),
                        "priority": override.get("priority", 100),
                        "curated": True,
                        "sources": sorted(old_sources | {"curated"}),
                    }
                    records[i] = new_record
                    matched = True
                    break
            if matched:
                break

        if not matched:
            records.append({
                "title": override["title"],
                "authors_html": override["authors_html"],
                "venue": override["venue"],
                "year": override["year"],
                "url": override["url"],
                "award": override.get("award", ""),
                "priority": override.get("priority", 100),
                "curated": True,
                "sources": ["curated"],
            })

    # De-duplicate once more after overrides.
    final_records = []
    for record in records:
        merge_record(final_records, record, overwrite=bool(record.get("curated")))

    final_records.sort(
        key=lambda p: (
            -int(p.get("year") or 0),
            int(p.get("priority") or 999),
            norm_title(p.get("title", "")),
        )
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_text = json.dumps(final_records, ensure_ascii=False, indent=2) + "\n"
    old_text = OUTPUT_PATH.read_text(encoding="utf-8") if OUTPUT_PATH.exists() else ""
    if new_text != old_text:
        OUTPUT_PATH.write_text(new_text, encoding="utf-8")
        print(f"Updated {OUTPUT_PATH} with {len(final_records)} publications.")
    else:
        print(f"No publication changes ({len(final_records)} records).")

    print(f"Discovered this run: {len(discovered)} records.")
    for error in errors:
        print("WARNING:", error, file=sys.stderr)


if __name__ == "__main__":
    main()
