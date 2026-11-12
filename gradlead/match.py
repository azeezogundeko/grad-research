"""Deterministic professor-applicant fit scoring. No LLM: the same evidence always gives the same score.

Components (capped at 100):
  overlap     0-60  weighted research-term hits between the professor's recent work and an applicant area,
                    plus papers that hit the area; the best area counts fully, the second adds a quarter
  recency     0-15  last publication year
  openings   -25..20 open funded position +20, published "accepting students" +15, "not accepting" -25
  seniority   0-10  early-career faculty most often need students; non-supervisors score low
  region      0-5   how much contacting a supervisor first matters there (funding.py)

Classes: strong >= 75, good >= 55, weak below. Inactive professors (emeritus, moved, not faculty,
or no publication in the last three years when the record is known) are flagged regardless of score.
"""
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from gradlead import funding
from gradlead.normalize import seniority as seniority_of

APPLICANT = Path(__file__).resolve().parent.parent / "profile" / "applicant.json"
STRONG, GOOD = 75, 55
SENIORITY_POINTS = {"early": 10, "mid": 9, "senior": 7, "unknown": 5, "non_supervisor": 2, "emeritus": 0}
RECENT_YEARS = 4  # papers from (year - 3) onward count as recent


@lru_cache(maxsize=4)
def load_applicant(path: str | None = None) -> dict:
    return json.loads(Path(path or APPLICANT).read_text(encoding="utf-8"))


@lru_cache(maxsize=4096)
def _term_re(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", re.I)


def term_hits(text: str, terms: dict[str, int]) -> dict[str, int]:
    return {t: w for t, w in terms.items() if _term_re(t).search(text or "")}


def paper_text(p: dict) -> str:
    return f"{p.get('title') or ''}. {p.get('abstract') or ''}"


def recent(pubs: list[dict], year: int) -> list[dict]:
    return [p for p in pubs if (p.get("year") or 0) >= year - (RECENT_YEARS - 1)]


def area_scores(prof: dict, pubs: list[dict], applicant: dict, year: int) -> dict:
    """Per area: weighted distinct terms over all recent evidence, plus papers that clearly hit the area."""
    rec = recent(pubs, year)
    profile_text = " ".join([
        " ".join(prof.get("interests") or []), prof.get("summary") or "", " ".join(prof.get("topics") or []),
    ])
    corpus = profile_text + " " + " ".join(paper_text(p) for p in rec)
    out = {}
    for key, area in applicant["areas"].items():
        terms = area["terms"]
        hits = term_hits(corpus, terms)
        papers = []
        for p in rec:
            ph = term_hits(paper_text(p), terms)
            weight = sum(ph.values())
            if weight >= 3 or (weight >= 2 and max(ph.values()) >= 2):
                papers.append((max(ph.values()), weight, p.get("year") or 0, p.get("id"), sorted(ph)))
        papers.sort(key=lambda x: (-x[0], -x[1], -x[2]))  # most specific term first (code-switching > speech)
        weighted = sum(hits.values())
        raw = 4 * weighted + 5 * len(papers)  # uncapped: breaks ties between areas that all hit the cap
        score = min(60, 4 * weighted + 5 * min(len(papers), 4))
        out[key] = {"score": score, "raw": raw, "terms": sorted(hits, key=lambda t: -hits[t]),
                    "papers": [{"id": pid, "terms": terms_} for _, _, _, pid, terms_ in papers[:5]]}
    return out


def recency_points(last_pub_year: int | None, year: int) -> int:
    if not last_pub_year:
        return 0
    gap = year - last_pub_year
    return 15 if gap <= 1 else 10 if gap == 2 else 5 if gap == 3 else 0


def _open(p: dict, today: date | None = None) -> bool:
    try:
        return not p.get("deadline") or date.fromisoformat(str(p["deadline"])[:10]) >= (today or date.today())
    except ValueError:
        return True


STUDENT_ROLES = {"phd", "msc", "mphil", "ms", "master", "masters", "ra", "research assistant", "research assistantship"}


def _student_role(degree: str | None) -> bool:
    """'PhD', 'PhD/RA', 'Research Assistant', '' (unspecified) count; 'postdoc' does not."""
    parts = [x.strip() for x in re.split(r"[/,;&|]|and|or", (degree or "").lower()) if x.strip()]
    return not parts or any(x in STUDENT_ROLES for x in parts)


def openings_points(signals: dict) -> int:
    positions = [p for p in signals.get("open_positions") or [] if _open(p)]
    if any(p.get("funded") and _student_role(p.get("degree")) for p in positions):
        return 20
    accepting = (signals.get("accepting_students") or "unknown").lower()
    return 15 if accepting == "yes" else -25 if accepting == "no" else 0


def inactive_reason(prof: dict, signals: dict, year: int) -> str | None:
    if signals.get("emeritus") or seniority_of(prof.get("title")) == "emeritus":
        return "emeritus"
    if signals.get("moved_to"):
        return f"moved to {signals['moved_to']}"
    if signals.get("not_faculty"):
        return "not faculty / cannot supervise"
    last = signals.get("last_pub_year")
    if last and last < year - (RECENT_YEARS - 1):
        return f"no publication since {last}"
    return None


def classify(score: int) -> str:
    return "strong" if score >= STRONG else "good" if score >= GOOD else "weak"


def score_professor(prof: dict, pubs: list[dict], signals: dict, country: str | None,
                    applicant: dict | None = None, year: int | None = None) -> dict:
    applicant = applicant or load_applicant()
    year = year or date.today().year
    areas = area_scores(prof, pubs, applicant, year)
    ranked = sorted(areas, key=lambda k: (-areas[k]["score"], -areas[k].get("raw", 0)))
    best, second = ranked[0], ranked[1] if len(ranked) > 1 else None
    overlap = min(60, areas[best]["score"] + (areas[second]["score"] // 4 if second else 0))
    last_pub = signals.get("last_pub_year") or max((p.get("year") or 0 for p in pubs), default=0) or None
    seniority = seniority_of(prof.get("title"))
    breakdown = {
        "overlap": overlap,
        "recency": recency_points(last_pub, year),
        "openings": openings_points(signals),
        "seniority": SENIORITY_POINTS[seniority],
        "region": funding.region_points(country),
    }
    if areas[best]["score"] == 0:  # no research overlap at all: nothing else should lift it
        breakdown = {k: (v if k == "overlap" else min(v, 0)) for k, v in breakdown.items()}
    score = max(0, min(100, sum(breakdown.values())))

    # Hooks: papers matching the primary area first, then the secondary area.
    hooks = [p["id"] for p in areas[best]["papers"]]
    if second:
        hooks += [p["id"] for p in areas[second]["papers"] if p["id"] not in hooks]
    projects = [k for k, p in applicant["projects"].items() if best in p["areas"]]
    if second and areas[second]["score"] >= 20:
        projects += [k for k, p in applicant["projects"].items() if second in p["areas"] and k not in projects]

    return {
        "score": score,
        "classification": classify(score),
        "primary_area": best if areas[best]["score"] > 0 else None,
        "areas": areas,
        "breakdown": {**breakdown, "seniority_class": seniority, "last_pub_year": last_pub},
        "matched_papers": hooks[:6],
        "matched_projects": projects,
        "inactive": inactive_reason(prof, {**signals, "last_pub_year": last_pub}, year),
    }
