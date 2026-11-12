"""Score advertised PhD / research-MSc positions against the applicant, deterministically.

An advert has no publication record, so the score is term overlap on the ad text only. Adverts are
short, so terms in the *title* (what the PhD is actually about) count extra:
  score = min(100, 8 * weighted terms of the best area (whole ad) + 2 * second area + 12 * best-area terms in the title)
`relevant` needs score >= 48: e.g. "Doctoral Student in Human-in-the-Loop Autonomous Systems" (24 + 36 = 60),
or a body with about six weighted terms. It also needs funding (or unknown) and an open deadline.
"""
from datetime import date

from gradlead import match

RELEVANT = 48


def score_ad(title: str, description: str, applicant: dict | None = None) -> dict:
    applicant = applicant or match.load_applicant()
    text = f"{title}. {description or ''}"
    weighted = {}
    terms = {}
    for key, area in applicant["areas"].items():
        hits = match.term_hits(text, area["terms"])
        weighted[key] = sum(hits.values())
        terms[key] = sorted(hits, key=lambda t: -hits[t])
    in_title = {k: sum(match.term_hits(title, a["terms"]).values()) for k, a in applicant["areas"].items()}
    ranked = sorted(weighted, key=lambda k: (-(8 * weighted[k] + 12 * in_title[k]), k))
    best, second = ranked[0], ranked[1]
    score = min(100, 8 * weighted[best] + 2 * weighted[second] + 12 * in_title[best])
    return {"score": score, "primary_area": best if weighted[best] else None, "terms": terms[best][:10]}


def status_for(score: int, funded, deadline: str | None, today: date | None = None) -> str:
    today = today or date.today()
    if deadline:
        try:
            if date.fromisoformat(deadline[:10]) < today:
                return "expired"
        except ValueError:
            pass
    if funded is False or funded == 0:
        return "unfunded"
    return "relevant" if score >= RELEVANT else "weak"
