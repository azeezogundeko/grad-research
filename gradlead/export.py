"""Quickly-ready CSV: one row per drafted professor.

Quickly's CSV import (POST /api/campaigns/{id}/leads/import) needs an `email` column, treats `name` as
reserved, and turns every other column into a `{{variable}}`. A plain-text sequence whose step 1 is
subject `{{subject}}` / body `{{body}}` therefore sends each draft exactly as written.

Each row also carries two no-reply follow-ups (`followup_1_body`, `followup_2_body`), built here from stored
facts only: the hook paper, an advertised position, a second matching project from applicant.json and the
research-area label. They go as same-thread replies (no subject), 10 sending days (~2 weeks) apart.
"""
import csv
import io
import json
import re

from gradlead import funding, match
from gradlead.normalize import first_name, last_name

COLUMNS = ["email", "name", "first_name", "salutation", "title", "university", "department", "country", "region",
           "subject", "body", "followup_1_body", "followup_2_body", "hook_paper", "hook_paper_url", "match_area", "match_score", "accepting_students",
           "position_url", "email_status", "email_source_url", "professor_id"]


def salutation(full_name: str, seniority: str | None) -> str:
    prefix = "Prof." if seniority in ("early", "mid", "senior") else "Dr."
    return f"{prefix} {last_name(full_name)}"


def rows(conn, min_score: int = 55, region: str | None = None, country: str | None = None,
         email_statuses: tuple[str, ...] = ("confirmed",), max_per_university: int = 3,
         include_exported: bool = False, applicant: dict | None = None,
         count_prior_exports: bool = True) -> list[dict]:
    applicant = applicant or match.load_applicant()
    cv_url = (applicant.get("links") or {}).get("cv_url")
    if not cv_url:
        raise ValueError("set links.cv_url in profile/applicant.json (hosted PDF of your CV) before exporting")
    statuses = ("drafted", "exported") if include_exported else ("drafted",)
    q = f"""
        SELECT p.*, u.name AS university, u.country, u.region, m.score, m.primary_area,
               m.matched_projects, d.cv_project, d.subject, d.body, pub.title AS hook_title, pub.url AS hook_url,
               s.accepting_students, s.open_positions
        FROM professors p
        JOIN universities u ON u.id = p.university_id
        JOIN drafts d ON d.professor_id = p.id
        JOIN matches m ON m.professor_id = p.id
        LEFT JOIN publications pub ON pub.id = d.hook_publication_id
        LEFT JOIN signals s ON s.professor_id = p.id
        WHERE p.status IN ({','.join('?' * len(statuses))}) AND m.score >= ?
          AND (? IS NULL OR u.region = ?) AND (? IS NULL OR lower(u.country) = lower(?))
          AND COALESCE(s.accepting_students, 'unknown') != 'no'
          AND p.email_status IN ({','.join('?' * len(email_statuses))})
          AND NOT EXISTS (SELECT 1 FROM suppressions x WHERE x.value = lower(p.email)
                          OR x.value = lower(substr(p.email, instr(p.email, '@') + 1)))
        ORDER BY m.score DESC, p.id"""
    params = (*statuses, min_score, region, region, country, country, *email_statuses)
    per_uni: dict[int, int] = {}
    if count_prior_exports and not include_exported:
        # Professors emailed in earlier batches count toward the per-university cap.
        for uid, n in conn.execute("SELECT university_id, COUNT(*) FROM professors WHERE status = 'exported' "
                                   "GROUP BY university_id"):
            per_uni[uid] = n
    out = []
    for r in conn.execute(q, params).fetchall():
        if funding.is_excluded(r["country"]) or per_uni.get(r["university_id"], 0) >= max_per_university:
            continue
        if not well_formatted(r["body"], applicant):  # one long block: re-draft before sending
            continue
        per_uni[r["university_id"]] = per_uni.get(r["university_id"], 0) + 1
        positions = json.loads(r["open_positions"] or "[]")
        fu1, fu2 = followups(r, positions, applicant, cv_url)
        out.append({
            "email": r["email"], "name": r["full_name"], "first_name": first_name(r["full_name"]),
            "salutation": salutation(r["full_name"], r["seniority"]), "title": r["title"] or "",
            "university": r["university"], "department": r["department"] or "", "country": r["country"] or "",
            "region": r["region"] or "", "subject": r["subject"], "body": r["body"].replace("{{cv_url}}", cv_url),
            "followup_1_body": fu1, "followup_2_body": fu2,
            "hook_paper": r["hook_title"] or "", "hook_paper_url": r["hook_url"] or "",
            "match_area": r["primary_area"] or "", "match_score": r["score"],
            "accepting_students": r["accepting_students"] or "unknown",
            "position_url": positions[0]["url"] if positions else "", "email_status": r["email_status"],
            "email_source_url": r["email_source_url"] or "", "professor_id": r["id"],
        })
    return out


def well_formatted(body: str, applicant: dict) -> bool:
    """At least 3 paragraphs between greeting and closing, none over 80 words (same rule as save-draft)."""
    core = body.split("\n\n" + applicant.get("signature", "\0"))[0]
    paras = [p for p in re.split(r"\n\s*\n", core) if p.strip()][1:-1]
    return len(paras) >= 3 and max(len(p.split()) for p in paras) <= 80


def _hook_ref(title: str) -> str:
    """'your paper “PingPong”': the short name before a colon when there is one, else the full title."""
    title = (title or "").replace("^{\\circ}", "°").replace("$", "").strip().rstrip(".")
    title = re.sub(r"\s+", " ", re.sub(r"\\[a-zA-Z]+|[{}]", "", title))
    if not title:
        return "your recent work"
    head = title.split(":", 1)[0].strip()
    if ":" in title and 1 <= len(head.split()) <= 8:
        title = head
    return f"your paper “{title}”"


def _project_line(project: dict) -> str:
    """One sentence of evidence from a project's first fact, e.g. 'at Toyyib, I designed a pipeline …'."""
    fact = project["facts"][0].rstrip(".")
    if project["name"].lower() in fact.lower():
        return f"I {fact}."
    if fact.split()[0].endswith("ing"):
        return f"at {project['name']}, I'm currently {fact}."
    return f"at {project['name']}, I {fact}."


def followups(r, positions: list[dict], applicant: dict, cv_url: str) -> tuple[str, str]:
    """Follow-up 1 (~2 weeks after the first email) adds one new, true point; follow-up 2 (~2 weeks later) is a
    short last note asking for a pointer to a colleague. Built only from stored facts, so nothing is invented."""
    greeting = f"Dear {salutation(r['full_name'], r['seniority'])},"
    sign = f"Best regards,\n{applicant['sign_off_name']}"
    seeking = applicant.get("seeking") or {}
    year = seeking.get("intake") or seeking.get("intake_year") or 2027  # e.g. "September 2027"
    open_pos = [p for p in positions if p.get("title")]
    others = [k for k in json.loads(r["matched_projects"] or "[]")
              if k != r["cv_project"] and k in applicant["projects"]]
    if open_pos:
        new_point = (f"I also saw the advertised {open_pos[0]['title'].strip().rstrip('.')} and would be glad to "
                     "apply formally if you think my background fits.")
    elif others:
        new_point = "One more piece of related work: " + _project_line(applicant["projects"][others[0]])
    else:
        new_point = "I'd be glad to shape my research direction around your group's current projects."
    if funding.region(r["country"]) == "USA":  # US: PhD first, funded MS as the alternative
        ask = (f"Would you consider me for a funded PhD place in your group for {str(year).replace('September', 'Fall')}, "
               "or a funded MS if that fits better?")
    else:
        ask = f"Would you consider me for a research MSc place in your group for {year}, or a PhD if that fits better?"
    fu1 = (f"{greeting}\n\nI'm writing again in case my earlier note about {_hook_ref(r['hook_title'])} got buried. "
           f"{new_point}\n\nMy CV is here: {cv_url}. I can also send a one-page research proposal if that would "
           f"help. {ask}\n\n{sign}")
    area = (applicant.get("areas") or {}).get(r["primary_area"] or "", {}).get("label") or "my research area"
    fu2 = (f"{greeting}\n\nThis is my last note, as I don't want to crowd your inbox. If you aren't taking students "
           f"for {year}, I'd be grateful for the name of a colleague working on {area} who might be. "
           f"Either way, thank you for your time.\n\n{sign}")
    return fu1, fu2


def _quickly_safe(value):
    """Straight double quotes become curly ones: Quickly's CSV sniffer can misread escaped quotes."""
    if not isinstance(value, str):
        return value
    return re.sub(r'"([^"\n]*)"', "“\\1”", value).replace('"', "”")


def to_csv(records: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows({k: _quickly_safe(v) for k, v in rec.items()} for rec in records)
    return buf.getvalue()


def mark_exported(conn, ids: list[int]) -> None:
    conn.executemany("UPDATE professors SET status = 'exported' WHERE id = ? AND status = 'drafted'", [(i,) for i in ids])
    conn.commit()
