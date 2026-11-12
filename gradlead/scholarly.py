"""Free scholarly metadata: OpenAlex first, Semantic Scholar as a fallback. No paid APIs.

OpenAlex works without a key. Optional env vars:
  OPENALEX_API_KEY   - higher limits if you register one (free)
  OPENALEX_MAILTO    - joins OpenAlex's "polite pool"; set it yourself, nothing is sent by default
  S2_API_KEY         - Semantic Scholar key (free); without it S2 is heavily rate-limited

Author disambiguation is conservative: a candidate must share the professor's family name and be
affiliated with the professor's university. Anything ambiguous comes back as `candidates` for the
profiler to choose from (`scholar ID --openalex-id A…`) instead of being guessed.
"""
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from gradlead.normalize import same_person, university_key

OPENALEX = "https://api.openalex.org"
S2 = "https://api.semanticscholar.org/graph/v1"
UA = "GradResearch/1.0 (academic outreach research)"
WORK_FIELDS = "id,title,publication_year,primary_location,doi,abstract_inverted_index,cited_by_count"


def _get_json(url: str, headers: dict | None = None, retries: int = 5) -> dict | None:
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < retries:
                # Several headless sessions share one IP: back off 3s, 6s, 12s, 24s, 48s (+ jitter).
                wait = exc.headers.get("Retry-After") if exc.headers else None
                time.sleep(min(60, float(wait)) if wait and wait.isdigit() else 3 * 2 ** attempt + random.random())
                continue
            if exc.code == 404:
                return None
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries:
                time.sleep(1)
                continue
            raise
    return None


def _openalex(path: str, params: dict) -> dict | None:
    params = {k: v for k, v in params.items() if v not in (None, "")}
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.environ.get("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    return _get_json(f"{OPENALEX}/{path}?{urllib.parse.urlencode(params)}")


def short_id(openalex_url: str | None) -> str | None:
    return openalex_url.rsplit("/", 1)[-1] if openalex_url else None


def abstract_text(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    positions = [(i, word) for word, idx in inverted.items() for i in idx]
    return " ".join(w for _, w in sorted(positions))


def same_institution(a: str | None, b: str | None) -> bool:
    ka, kb = university_key(a or ""), university_key(b or "")
    if not ka or not kb:
        return False
    if ka == kb or ka in kb or kb in ka:
        return True
    ta, tb = set(ka.split()) - {"university", "institute", "technology", "college"}, set(kb.split()) - {"university", "institute", "technology", "college"}
    return bool(ta) and bool(tb) and len(ta & tb) / min(len(ta), len(tb)) >= 0.75


# --------------------------------------------------------------------------- OpenAlex

def institution_id(name: str) -> str | None:
    data = _openalex("institutions", {"search": name, "per-page": 5, "select": "id,display_name,display_name_acronyms"})
    for inst in (data or {}).get("results", []):
        acronyms = [a.lower() for a in inst.get("display_name_acronyms") or []]
        if same_institution(inst["display_name"], name) or name.lower() in acronyms:
            return short_id(inst["id"])
    return None


def _author_summary(a: dict) -> dict:
    insts = [i.get("display_name") for i in a.get("last_known_institutions") or []]
    insts += [aff["institution"].get("display_name") for aff in a.get("affiliations") or [] if aff.get("institution")]
    return {
        "openalex_id": short_id(a["id"]),
        "display_name": a.get("display_name"),
        "orcid": a.get("orcid"),
        "institutions": list(dict.fromkeys(i for i in insts if i))[:5],
        "works_count": a.get("works_count"),
        "cited_by_count": a.get("cited_by_count"),
        "h_index": (a.get("summary_stats") or {}).get("h_index"),
        "topics": [t.get("display_name") for t in (a.get("topics") or [])[:8]],
    }


def find_author(full_name: str, university: str, inst_id: str | None = None) -> dict:
    """{'author': summary} when unambiguous, else {'candidates': [...]}."""
    params = {"search": full_name, "per-page": 10}
    if inst_id:
        params["filter"] = f"affiliations.institution.id:{inst_id}"
    data = _openalex("authors", params) or {}
    results = [a for a in data.get("results", []) if same_person(full_name, a.get("display_name") or "")]
    if not results and inst_id:  # retry without the affiliation filter, then match institution by name
        return find_author(full_name, university, None)
    summaries = [_author_summary(a) for a in results]
    if inst_id:
        at_uni = summaries
    else:
        at_uni = [s for s in summaries if any(same_institution(i, university) for i in s["institutions"])]
    if len(at_uni) == 1:
        return {"author": at_uni[0]}
    if len(at_uni) > 1:  # split profiles of the same person are common; take the most productive
        at_uni.sort(key=lambda s: -(s["works_count"] or 0))
        if (at_uni[0]["works_count"] or 0) >= 3 * (at_uni[1]["works_count"] or 0):
            return {"author": at_uni[0], "note": f"{len(at_uni)} profiles; took the largest"}
        return {"candidates": at_uni[:5]}
    return {"candidates": summaries[:5]}


def get_author(openalex_id: str) -> dict | None:
    data = _openalex(f"authors/{openalex_id}", {})
    return _author_summary(data) if data else None


def _work(w: dict) -> dict:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    doi = w.get("doi")
    return {
        "title": (w.get("title") or "").strip(),
        "year": w.get("publication_year"),
        "venue": src.get("display_name"),
        "url": loc.get("landing_page_url") or doi or w.get("id"),
        "doi": doi,
        "abstract": abstract_text(w.get("abstract_inverted_index")),
        "cited_by": w.get("cited_by_count"),
        "source": "openalex",
    }


def recent_works(openalex_id: str, since_year: int, limit: int = 30) -> list[dict]:
    data = _openalex("works", {
        "filter": f"author.id:{openalex_id},from_publication_date:{since_year}-01-01",
        "sort": "publication_date:desc", "per-page": limit, "select": WORK_FIELDS,
    }) or {}
    return [_work(w) for w in data.get("results", []) if w.get("title")]


def latest_year(openalex_id: str) -> int | None:
    data = _openalex("works", {"filter": f"author.id:{openalex_id}", "sort": "publication_date:desc",
                               "per-page": 1, "select": "publication_year"}) or {}
    results = data.get("results") or []
    return results[0].get("publication_year") if results else None


# --------------------------------------------------------------------------- Semantic Scholar (fallback)

def _s2(path: str, params: dict) -> dict | None:
    headers = {"x-api-key": os.environ["S2_API_KEY"]} if os.environ.get("S2_API_KEY") else {}
    return _get_json(f"{S2}/{path}?{urllib.parse.urlencode(params)}", headers)


def s2_author(full_name: str, university: str) -> dict:
    data = _s2("author/search", {"query": full_name, "fields": "name,affiliations,paperCount,hIndex", "limit": 10}) or {}
    people = [a for a in data.get("data", []) if same_person(full_name, a.get("name") or "")]
    at_uni = [a for a in people if any(same_institution(x, university) for x in a.get("affiliations") or [])]
    pick = at_uni if at_uni else (people if len(people) == 1 else [])
    if len(pick) == 1:
        return {"author": {"s2_id": pick[0]["authorId"], "display_name": pick[0]["name"],
                           "h_index": pick[0].get("hIndex"), "works_count": pick[0].get("paperCount")}}
    return {"candidates": [{"s2_id": a["authorId"], "display_name": a["name"], "affiliations": a.get("affiliations")}
                           for a in people[:5]]}


def s2_recent_works(s2_id: str, since_year: int, limit: int = 50) -> list[dict]:
    data = _s2(f"author/{s2_id}/papers", {"fields": "title,year,venue,abstract,url,externalIds,citationCount",
                                           "limit": limit}) or {}
    out = []
    for p in data.get("data", []):
        if not p.get("title") or (p.get("year") or 0) < since_year:
            continue
        doi = (p.get("externalIds") or {}).get("DOI")
        out.append({"title": p["title"].strip(), "year": p.get("year"), "venue": p.get("venue") or None,
                    "url": p.get("url") or (f"https://doi.org/{doi}" if doi else None),
                    "doi": f"https://doi.org/{doi}" if doi else None, "abstract": p.get("abstract"),
                    "cited_by": p.get("citationCount"), "source": "s2"})
    out.sort(key=lambda p: -(p["year"] or 0))
    return out


# --------------------------------------------------------------------------- entry point

def lookup(full_name: str, university: str, inst_id: str | None = None, openalex_id: str | None = None,
           s2_id: str | None = None, years: int = 4) -> dict:
    """Resolve the author and pull recent works. Returns {source, author, works, last_pub_year} or {candidates}."""
    since = date.today().year - (years - 1)
    errors = []
    if not s2_id:
        try:
            if openalex_id:
                author = get_author(openalex_id)
                found = {"author": author} if author else {"candidates": []}
            else:
                found = find_author(full_name, university, inst_id)
            if "author" in found:
                aid = found["author"]["openalex_id"]
                works = recent_works(aid, since)
                last = works[0]["year"] if works else latest_year(aid)
                return {"source": "openalex", **found, "works": works, "last_pub_year": last}
            openalex_candidates = found["candidates"]
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            errors.append(f"openalex: {exc}")
            openalex_candidates = []
    else:
        openalex_candidates = []
    try:
        found = {"author": {"s2_id": s2_id}} if s2_id else s2_author(full_name, university)
        if "author" in found:
            works = s2_recent_works(found["author"]["s2_id"], since)
            return {"source": "s2", **found, "works": works, "last_pub_year": works[0]["year"] if works else None}
        s2_candidates = found["candidates"]
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        errors.append(f"s2: {exc}")
        s2_candidates = []
    return {"source": None, "candidates": {"openalex": openalex_candidates, "s2": s2_candidates}, "errors": errors,
            "hint": "Pick the right author from the homepage (Google Scholar/ORCID/DBLP links) and rerun with "
                    "--openalex-id or --s2-id, or pass publications in save-profile."}

