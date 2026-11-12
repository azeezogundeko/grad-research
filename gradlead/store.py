"""All reads/writes of the professor store. Claude judges; this module validates, dedupes and scores."""
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from gradlead import funding, match, verify
from gradlead.db import dumps, loads, log_run, now, row_to_dict
from gradlead.normalize import (email_domain, is_valid_email, last_name, name_key, same_person, seniority,
                                university_key, word_count)

STATUSES = ["discovered", "matched", "weak_match", "inactive", "no_email", "unreachable", "duplicate",
            "drafted", "exported", "declined"]
PROFILED = {"matched", "weak_match", "inactive", "no_email"}  # statuses rematch may move between
GOOD_EMAIL = ("confirmed",)
BODY_WORDS = (100, 190)
BANNED = ["hope this email finds you", "hope this finds you", "dear sir", "dear madam", "to whom it may concern",
          "esteemed", "i am writing to express my interest", "kindly", "humbly", "[insert", "lorem ipsum", "todo", "xxx"]
PLACEHOLDER = re.compile(r"\{\{|\}\}|\[[A-Z][A-Z _]+\]|<[A-Z][A-Z _]+>")


# --------------------------------------------------------------------------- universities

def add_universities(conn: sqlite3.Connection, records: list[dict]) -> dict:
    added, updated, ids = 0, 0, []
    for r in records:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        key = university_key(name)
        country = r.get("country")
        if funding.is_excluded(country):
            continue
        existing = conn.execute("SELECT * FROM universities WHERE name_key = ?", (key,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE universities SET country = COALESCE(?, country), region = COALESCE(?, region), "
                "city = COALESCE(?, city), goal = COALESCE(?, goal), notes = COALESCE(?, notes) WHERE id = ?",
                (country, funding.region(country) if country else None, r.get("city"), r.get("goal"),
                 r.get("notes"), existing["id"]))
            updated += 1
            ids.append(existing["id"])
        else:
            cur = conn.execute(
                "INSERT INTO universities (name, name_key, country, region, city, goal, notes, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, key, country, funding.region(country), r.get("city"), r.get("goal"), r.get("notes"), now()))
            added += 1
            ids.append(cur.lastrowid)
    conn.commit()
    return {"added": added, "updated": updated, "ids": ids}


def parse_targets(path: str | Path) -> list[dict]:
    """targets.txt lines: country|university|goal|notes (goal and notes optional, # comments)."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        parts += [""] * (4 - len(parts))
        country, name, goal, notes = parts[:4]
        out.append({"country": country, "name": name, "goal": int(goal) if goal.isdigit() else 25,
                    "notes": notes or None})
    return out


def find_university(conn, ref: str | int) -> dict | None:
    if isinstance(ref, int) or str(ref).isdigit():
        row = conn.execute("SELECT * FROM universities WHERE id = ?", (int(ref),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM universities WHERE name_key = ?", (university_key(str(ref)),)).fetchone()
    uni = row_to_dict(row)
    if uni:
        uni["directory_urls"] = loads(uni["directory_urls"], [])
        uni["funding"] = funding.info(uni["country"])
    return uni


def target_progress(conn, region: str | None = None, pending: str | None = None) -> list[dict]:
    rows = conn.execute("""
        SELECT u.id, u.name, u.country, u.region, u.goal, u.discovered_at,
               COUNT(p.id) AS professors,
               SUM(p.status = 'discovered') AS to_profile,
               SUM(p.status = 'matched') AS to_draft,
               SUM(p.status = 'drafted') AS drafted,
               SUM(p.status = 'exported') AS exported,
               SUM(p.status IN ('weak_match','inactive','no_email','unreachable','duplicate','declined')) AS dropped
        FROM universities u LEFT JOIN professors p ON p.university_id = u.id
        WHERE (? IS NULL OR u.region = ?)
        GROUP BY u.id ORDER BY u.region, u.name""", (region, region)).fetchall()
    out = []
    for r in rows:
        d = {k: (r[k] or 0) if k not in ("name", "country", "region", "discovered_at") else r[k] for k in r.keys()}
        d["to_discover"] = 0 if r["discovered_at"] else max(0, (r["goal"] or 0) - d["professors"])
        out.append(d)
    if pending:
        key = {"discover": "to_discover", "profile": "to_profile", "draft": "to_draft"}[pending]
        out = [d for d in out if d[key] > 0]
    return out


# --------------------------------------------------------------------------- professors

def add_professors(conn, university_id: int, records: list[dict], directory_url: str | None = None,
                   done: bool = False) -> dict:
    uni = find_university(conn, university_id)
    if not uni:
        raise ValueError(f"university {university_id} not found; run `targets --sync` or add-unis first")
    added, updated, skipped, ids = 0, 0, [], []
    for r in records:
        name = (r.get("full_name") or r.get("name") or "").strip()
        source = r.get("source_url") or r.get("profile_url") or r.get("homepage")
        if not name or not source:
            skipped.append({"name": name, "reason": "full_name and source_url are required"})
            continue
        email, email_src = _clean_email(r, skipped, name)
        key = name_key(name)
        existing = conn.execute("SELECT * FROM professors WHERE university_id = ? AND name_key = ?",
                                (university_id, key)).fetchone()
        fields = {
            "title": r.get("title"), "seniority": seniority(r.get("title")) if r.get("title") else None,
            "department": r.get("department"), "lab_name": r.get("lab_name"), "lab_url": r.get("lab_url"),
            "homepage": r.get("homepage"), "profile_url": r.get("profile_url"), "source_url": source,
            "interests": dumps(r["interests"]) if r.get("interests") else None,
            "email": email, "email_source_url": email_src, "email_status": "unchecked" if email else None,
        }
        if existing:  # fill gaps only; never overwrite what research already established
            sets = {k: v for k, v in fields.items() if v and not existing[k]}
            if sets:
                conn.execute(f"UPDATE professors SET {', '.join(f'{k} = ?' for k in sets)}, updated_at = ? WHERE id = ?",
                             (*sets.values(), now(), existing["id"]))
                updated += 1
            ids.append(existing["id"])
            continue
        cols = {"university_id": university_id, "full_name": name, "name_key": key, **fields,
                "status": "discovered", "created_at": now(), "updated_at": now()}
        cur = conn.execute(f"INSERT INTO professors ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           tuple(cols.values()))
        added += 1
        ids.append(cur.lastrowid)
    if directory_url:
        urls = list(dict.fromkeys(uni["directory_urls"] + [directory_url]))
        conn.execute("UPDATE universities SET directory_urls = ? WHERE id = ?", (dumps(urls), university_id))
    if done:
        conn.execute("UPDATE universities SET discovered_at = ? WHERE id = ?", (now(), university_id))
    log_run(conn, "add-profs", {"university_id": university_id, "added": added, "updated": updated})
    conn.commit()
    return {"university": uni["name"], "added": added, "updated": updated, "skipped": skipped, "ids": ids}


def _clean_email(r: dict, problems: list, name: str) -> tuple[str | None, str | None]:
    email = (r.get("email") or "").strip().lower() or None
    src = r.get("email_source_url")
    if email and not src:
        problems.append({"name": name, "reason": f"email {email} dropped: email_source_url is required"})
        return None, None
    if email and not is_valid_email(email):
        problems.append({"name": name, "reason": f"email {email} dropped: invalid syntax"})
        return None, None
    return email, src if email else None


def queue(conn, status: str, limit: int = 10, university_id: int | None = None, region: str | None = None,
          min_score: int | None = None) -> list[dict]:
    rows = conn.execute("""
        SELECT p.id, p.full_name, p.title, p.department, p.homepage, p.profile_url, p.email, p.email_status,
               u.id AS university_id, u.name AS university, u.country, u.region, m.score, m.primary_area
        FROM professors p JOIN universities u ON u.id = p.university_id
        LEFT JOIN matches m ON m.professor_id = p.id
        WHERE p.status = ? AND (? IS NULL OR p.university_id = ?) AND (? IS NULL OR u.region = ?)
          AND (? IS NULL OR m.score >= ?)
        ORDER BY COALESCE(m.score, 0) DESC, p.id LIMIT ?""",
        (status, university_id, university_id, region, region, min_score, min_score, limit)).fetchall()
    return [dict(r) for r in rows]


def _prof_row(conn, pid: int) -> dict:
    row = conn.execute("SELECT * FROM professors WHERE id = ?", (pid,)).fetchone()
    if not row:
        raise ValueError(f"professor {pid} not found")
    p = dict(row)
    p["interests"] = loads(p["interests"], [])
    p["topics"] = loads(p["topics"], [])
    return p


def _signals(conn, pid: int) -> dict:
    s = row_to_dict(conn.execute("SELECT * FROM signals WHERE professor_id = ?", (pid,)).fetchone()) or {}
    s["open_positions"] = loads(s.get("open_positions"), [])
    s["pages_read"] = loads(s.get("pages_read"), [])
    return s


def _publications(conn, pid: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM publications WHERE professor_id = ? ORDER BY COALESCE(year, 0) DESC, id", (pid,))]


def get_professor(conn, pid: int, brief: bool = False) -> dict:
    p = _prof_row(conn, pid)
    uni = find_university(conn, p["university_id"])
    p["university"] = {k: uni[k] for k in ("id", "name", "country", "region", "notes")}
    p["funding"] = uni["funding"]
    p["signals"] = _signals(conn, pid)
    pubs = _publications(conn, pid)
    m = row_to_dict(conn.execute("SELECT * FROM matches WHERE professor_id = ?", (pid,)).fetchone())
    if m:
        for k in ("areas", "breakdown", "matched_papers", "matched_projects"):
            m[k] = loads(m[k], {})
        if brief:
            m["areas"] = {k: {"score": v["score"], "terms": v["terms"][:8]} for k, v in m["areas"].items()}
    p["match"] = m
    hook_ids = (m or {}).get("matched_papers") or []
    if brief:  # what the outreach writer needs: hook candidates first, abstracts trimmed
        by_id = {x["id"]: x for x in pubs}
        hooks = [by_id[i] for i in hook_ids if i in by_id]
        rest = [x for x in pubs if x["id"] not in hook_ids][:5]
        p["publications"] = [{**{k: x[k] for k in ("id", "title", "year", "venue", "url")},
                              "abstract": (x["abstract"] or "")[:600], "hook_candidate": x["id"] in hook_ids}
                             for x in hooks + rest]
    else:
        p["publications"] = pubs
    d = row_to_dict(conn.execute("SELECT * FROM drafts WHERE professor_id = ?", (pid,)).fetchone())
    p["draft"] = d
    p["adverts"] = [dict(r) for r in conn.execute(
        "SELECT id, title, degree, funded, deadline, url, substr(description, 1, 1800) AS description "
        "FROM positions WHERE professor_id = ? AND status IN ('relevant', 'weak') ORDER BY deadline", (pid,))]
    return p


def set_status(conn, pid: int, status: str, note: str | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    _prof_row(conn, pid)
    conn.execute("UPDATE professors SET status = ?, status_note = COALESCE(?, status_note), updated_at = ? WHERE id = ?",
                 (status, note, now(), pid))
    conn.commit()
    return {"id": pid, "status": status}


def mark_university_discovered(conn, university_id: int) -> dict:
    conn.execute("UPDATE universities SET discovered_at = ? WHERE id = ?", (now(), university_id))
    conn.commit()
    return {"id": university_id, "discovered_at": now()}


# --------------------------------------------------------------------------- scholarly + profile

def _insert_publications(conn, pid: int, pubs: list[dict], source: str) -> int:
    n = 0
    for w in pubs:
        title = (w.get("title") or "").strip()
        if not title:
            continue
        cur = conn.execute(
            "INSERT INTO publications (professor_id, title, title_key, year, venue, url, doi, abstract, cited_by, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(professor_id, title_key) DO UPDATE SET "
            "abstract = COALESCE(publications.abstract, excluded.abstract), url = COALESCE(publications.url, excluded.url), "
            "venue = COALESCE(publications.venue, excluded.venue)",
            (pid, title, name_key(title), w.get("year"), w.get("venue"), w.get("url"), w.get("doi"),
             w.get("abstract"), w.get("cited_by"), w.get("source") or source))
        n += cur.rowcount
    return n


def save_scholar(conn, pid: int, result: dict) -> dict:
    """Persist a scholarly.lookup() result. Returns a compact summary for Claude."""
    prof = _prof_row(conn, pid)
    if not result.get("source"):
        return {"id": pid, "resolved": False, **{k: result.get(k) for k in ("candidates", "errors", "hint")}}
    author = result["author"]
    oa = author.get("openalex_id")
    if oa:
        dup = conn.execute("SELECT id, full_name FROM professors WHERE openalex_id = ? AND id != ?", (oa, pid)).fetchone()
        if dup:
            set_status(conn, pid, "duplicate", f"same OpenAlex author as #{dup['id']} {dup['full_name']}")
            return {"id": pid, "resolved": True, "duplicate_of": dup["id"]}
    conn.execute("UPDATE professors SET openalex_id = COALESCE(?, openalex_id), s2_id = COALESCE(?, s2_id), "
                 "topics = COALESCE(?, topics), updated_at = ? WHERE id = ?",
                 (oa, author.get("s2_id"), dumps(author["topics"]) if author.get("topics") else None, now(), pid))
    conn.execute(
        "INSERT INTO signals (professor_id, last_pub_year, works_count, cited_by_count, h_index) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(professor_id) DO UPDATE SET last_pub_year = excluded.last_pub_year, "
        "works_count = excluded.works_count, cited_by_count = excluded.cited_by_count, h_index = excluded.h_index",
        (pid, result.get("last_pub_year"), author.get("works_count"), author.get("cited_by_count"), author.get("h_index")))
    n = _insert_publications(conn, pid, result.get("works") or [], result["source"])
    conn.commit()
    return {"id": pid, "name": prof["full_name"], "resolved": True, "source": result["source"],
            "author": {k: author.get(k) for k in ("openalex_id", "s2_id", "display_name", "institutions", "h_index")},
            "note": result.get("note"), "recent_works": len(result.get("works") or []), "new_publications": n,
            "last_pub_year": result.get("last_pub_year"), "topics": (author.get("topics") or [])[:6],
            "titles": [w["title"] for w in (result.get("works") or [])[:8]]}


def save_profile(conn, pid: int, data: dict) -> dict:
    prof = _prof_row(conn, pid)
    if data.get("unreachable"):
        set_status(conn, pid, "unreachable", data.get("reason"))
        return {"id": pid, "status": "unreachable"}
    notes = []

    updates = {}
    new_name = (data.get("full_name") or "").strip()
    if new_name and new_name != prof["full_name"] and same_person(new_name, prof["full_name"]):
        updates["full_name"] = new_name
    for k in ("title", "department", "lab_name", "lab_url", "homepage", "summary"):
        if data.get(k):
            updates[k] = data[k]
    if data.get("title"):
        updates["seniority"] = seniority(data["title"])
    if data.get("research_interests"):
        updates["interests"] = dumps(data["research_interests"])

    if "email" in data:
        email, src = _clean_email(data, problems := [], prof["full_name"])
        notes += [p["reason"] for p in problems]
        if email and email != prof["email"]:
            updates.update(email=email, email_source_url=src, email_status="unchecked", email_detail=None)
        elif email and src and not prof["email_source_url"]:
            updates["email_source_url"] = src

    if updates:
        conn.execute(f"UPDATE professors SET {', '.join(f'{k} = ?' for k in updates)}, updated_at = ? WHERE id = ?",
                     (*updates.values(), now(), pid))

    accepting = (data.get("accepting_students") or "unknown").lower()
    if accepting not in ("yes", "no", "unknown"):
        accepting = "unknown"
    if accepting != "unknown" and not (data.get("accepting_quote") and data.get("accepting_url")):
        notes.append(f"accepting_students={accepting} downgraded to unknown: needs accepting_quote and accepting_url")
        accepting = "unknown"
    found = [p for p in data.get("open_positions") or [] if p.get("url") and p.get("title")]
    if len(found) < len(data.get("open_positions") or []):
        notes.append("open_positions without title+url were dropped")
    positions = merge_positions(_signals(conn, pid).get("open_positions") or [], found)  # keep ad-linked ones
    flags = data.get("status_flags") or {}
    conn.execute(
        "INSERT INTO signals (professor_id, accepting_students, accepting_quote, accepting_url, open_positions, emeritus, "
        "moved_to, not_faculty, pages_read, profiled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(professor_id) DO UPDATE SET accepting_students = excluded.accepting_students, "
        "accepting_quote = excluded.accepting_quote, accepting_url = excluded.accepting_url, "
        "open_positions = excluded.open_positions, emeritus = excluded.emeritus, moved_to = excluded.moved_to, "
        "not_faculty = excluded.not_faculty, pages_read = excluded.pages_read, profiled_at = excluded.profiled_at",
        (pid, accepting, data.get("accepting_quote") if accepting != "unknown" else None,
         data.get("accepting_url") if accepting != "unknown" else None, dumps(positions),
         int(bool(flags.get("emeritus"))), flags.get("moved_to"), int(bool(flags.get("not_faculty"))),
         dumps(data.get("pages_read") or []), now()))

    extra = [p for p in data.get("publications") or [] if p.get("title") and p.get("url")]
    _insert_publications(conn, pid, extra, "homepage")
    conn.commit()
    result = rematch(conn, pid)
    return {**result, "notes": notes}


def rematch(conn, pid: int, year: int | None = None) -> dict:
    prof = _prof_row(conn, pid)
    signals = _signals(conn, pid)
    if not signals.get("profiled_at"):
        return {"id": pid, "status": prof["status"], "skipped": "not profiled yet"}
    uni = find_university(conn, prof["university_id"])
    pubs = _publications(conn, pid)
    m = match.score_professor(prof, pubs, signals, uni["country"], year=year)
    conn.execute(
        "INSERT INTO matches (professor_id, score, classification, primary_area, areas, breakdown, matched_papers, "
        "matched_projects, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(professor_id) DO UPDATE SET "
        "score = excluded.score, classification = excluded.classification, primary_area = excluded.primary_area, "
        "areas = excluded.areas, breakdown = excluded.breakdown, matched_papers = excluded.matched_papers, "
        "matched_projects = excluded.matched_projects, updated_at = excluded.updated_at",
        (pid, m["score"], m["classification"], m["primary_area"], dumps(m["areas"]), dumps(m["breakdown"]),
         dumps(m["matched_papers"]), dumps(m["matched_projects"]), now()))
    status, note = prof["status"], None
    if prof["status"] in PROFILED or prof["status"] == "discovered":
        if prof["email"] and is_suppressed(conn, prof["email"]):
            status, note = "declined", "suppressed"
        elif m["inactive"]:
            status, note = "inactive", m["inactive"]
        elif not prof["email"] or prof["email_status"] == "invalid":
            status, note = "no_email", "no published email" if not prof["email"] else "email invalid"
        elif m["classification"] in ("strong", "good"):
            status = "matched"
        else:
            status = "weak_match"
        conn.execute("UPDATE professors SET status = ?, status_note = ?, updated_at = ? WHERE id = ?",
                     (status, note, now(), pid))
    conn.commit()
    return {"id": pid, "name": prof["full_name"], "status": status, "note": note, "score": m["score"],
            "classification": m["classification"], "primary_area": m["primary_area"],
            "breakdown": m["breakdown"], "hook_papers": m["matched_papers"][:3]}


def rematch_all(conn) -> dict:
    ids = [r["id"] for r in conn.execute("SELECT professor_id AS id FROM signals WHERE profiled_at IS NOT NULL")]
    results = [rematch(conn, i) for i in ids]
    by_status = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    return {"rematched": len(results), "by_status": by_status}


def drop_publications(conn, pid: int, pub_ids: list[int] | None = None, source: str | None = None) -> dict:
    """Remove papers wrongly attributed to a professor (same-name authors), then re-score.

    Pass publication ids, or a source ("s2", "openalex", "homepage") to drop everything from a bad lookup.
    A paper used as a draft's hook can't be dropped; re-draft first.
    """
    _prof_row(conn, pid)
    if not pub_ids and not source:
        raise ValueError("give publication ids or --source")
    where, params = "professor_id = ?", [pid]
    if pub_ids:
        where += f" AND id IN ({','.join('?' * len(pub_ids))})"
        params += pub_ids
    if source:
        where += " AND source = ?"
        params.append(source)
    hook = conn.execute(f"SELECT p.id FROM publications p JOIN drafts d ON d.hook_publication_id = p.id WHERE {where.replace('id IN', 'p.id IN').replace('professor_id', 'p.professor_id').replace('source =', 'p.source =')}", params).fetchall()
    if hook:
        raise ValueError(f"publication {[h[0] for h in hook]} is the hook of a saved draft; re-draft first")
    titles = [r[0] for r in conn.execute(f"SELECT title FROM publications WHERE {where}", params)]
    conn.execute(f"DELETE FROM publications WHERE {where}", params)
    last = conn.execute("SELECT MAX(year) FROM publications WHERE professor_id = ?", (pid,)).fetchone()[0]
    conn.execute("UPDATE signals SET last_pub_year = ? WHERE professor_id = ?", (last, pid))
    log_run(conn, "drop-pubs", {"professor_id": pid, "dropped": titles})
    conn.commit()
    return {"dropped": len(titles), "titles": titles[:10], "rematch": rematch(conn, pid)}


# --------------------------------------------------------------------------- drafts

def _allowed_numbers(applicant: dict, uni: dict, prof: dict, hook: dict | None, positions: list[dict],
                     programme: str) -> set[str]:
    """Every number a draft may state: from the CV, the hook paper, an open position, or a plausible intake year."""
    text = " ".join([json.dumps(applicant), uni["name"], prof.get("department") or "", programme or "",
                     (hook or {}).get("title") or "", (hook or {}).get("venue") or "", str((hook or {}).get("year") or ""),
                     json.dumps(positions)])
    this_year = date.today().year
    return set(re.findall(r"\d+(?:\.\d+)?", text)) | {str(y) for y in range(this_year - 1, this_year + 3)}


def validate_draft(conn, pid: int, d: dict, applicant: dict) -> tuple[list[str], dict]:
    errors = []
    prof = _prof_row(conn, pid)
    uni = find_university(conn, prof["university_id"])
    subject, body = (d.get("subject") or "").strip(), (d.get("body") or "").strip()
    hook = None
    if d.get("hook_publication_id") is not None:
        hook = row_to_dict(conn.execute("SELECT * FROM publications WHERE id = ? AND professor_id = ?",
                                        (d["hook_publication_id"], pid)).fetchone())
    if not hook:
        errors.append("hook_publication_id must be one of this professor's publications (see `show`)")
    project = applicant["projects"].get(d.get("cv_project") or "")
    if not project:
        errors.append(f"cv_project must be one of {sorted(applicant['projects'])}")
    elif project["name"].lower() not in body.lower():
        errors.append(f"body must name the project it uses ({project['name']})")
    if not 3 <= word_count(subject) <= 14:
        errors.append("subject must be 3-14 words")
    n = word_count(body)
    if not BODY_WORDS[0] <= n <= BODY_WORDS[1]:
        errors.append(f"body is {n} words; keep it {BODY_WORDS[0]}-{BODY_WORDS[1]} (signature is added by the code)")
    if last_name(prof["full_name"]).lower() not in body.lower():
        errors.append(f"greet the professor by name (expected '{last_name(prof['full_name'])}' in the body)")
    for text, label in ((subject, "subject"), (body, "body")):
        if PLACEHOLDER.search(text):
            errors.append(f"{label} contains a placeholder; the CV link is added by the signature")
        low = text.lower()
        errors += [f"{label} uses banned phrase '{b}'" for b in BANNED if b in low]
    positions = _signals(conn, pid).get("open_positions") or []
    allowed = _allowed_numbers(applicant, uni, prof, hook, positions, d.get("programme") or "")
    stray = sorted({x for x in re.findall(r"\d+(?:\.\d+)?", subject + " " + body) if x not in allowed})
    if stray:
        errors.append(f"numbers not backed by applicant.json, the hook paper or the position: {stray}")
    paras = [x for x in re.split(r"\n\s*\n", body) if x.strip()]
    middle = paras[1:-1]  # between the greeting and the closing line
    if len(middle) < 3:
        errors.append(f"body has {len(middle)} paragraph(s) between the greeting and 'Best regards,'; use 3: "
                      "the paper, your related project, then what you'd study + the ask (blank line between each)")
    elif max(word_count(x) for x in middle) > 80:
        errors.append("a paragraph is over 80 words; split it so each holds one idea")
    last_line = body.splitlines()[-1].lower() if body else ""
    if applicant["sign_off_name"].split()[0].lower() in last_line:
        errors.append("don't sign the body; end with a closing line like 'Best regards,' and the code adds the signature")
    return errors, {"hook": hook, "subject": subject, "body": body}


def save_draft(conn, pid: int, d: dict, applicant: dict | None = None) -> dict:
    applicant = applicant or match.load_applicant()
    prof = _prof_row(conn, pid)
    if prof["status"] not in ("matched", "drafted"):
        raise ValueError(f"professor {pid} is '{prof['status']}'; only matched professors get drafts")
    errors, ok = validate_draft(conn, pid, d, applicant)
    if errors:
        return {"id": pid, "saved": False, "errors": errors}
    body = ok["body"].rstrip() + "\n\n" + applicant["signature"]
    conn.execute(
        "INSERT INTO drafts (professor_id, hook_publication_id, cv_project, programme, subject, body, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(professor_id) DO UPDATE SET "
        "hook_publication_id = excluded.hook_publication_id, cv_project = excluded.cv_project, "
        "programme = excluded.programme, subject = excluded.subject, body = excluded.body, created_at = excluded.created_at",
        (pid, ok["hook"]["id"], d["cv_project"], d.get("programme"), ok["subject"], body, now()))
    conn.execute("UPDATE professors SET status = 'drafted', updated_at = ? WHERE id = ?", (now(), pid))
    conn.commit()
    return {"id": pid, "saved": True, "words": word_count(ok["body"]), "hook": ok["hook"]["title"]}


# --------------------------------------------------------------------------- verification, suppression

def verify_emails(conn, pid: int | None = None, pending: bool = True, limit: int = 200) -> dict:
    sql = "SELECT id, email, email_source_url, email_status FROM professors WHERE email IS NOT NULL"
    params: list = []
    if pid:
        sql += " AND id = ?"
        params.append(pid)
    elif pending:
        sql += " AND (email_status IS NULL OR email_status = 'unchecked')"
    rows = conn.execute(sql + " LIMIT ?", (*params, limit)).fetchall()
    counts: dict[str, int] = {}
    # Fetching source pages is the slow part: do it concurrently, then write results from this thread.
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda r: verify.verify(r["email"], r["email_source_url"]), rows))
    for r, v in zip(rows, results):
        if r["email_status"] == "confirmed" and v["status"] == "unconfirmed":
            # Already re-found on its page once; a page that is unreachable today is not counter-evidence.
            counts["kept_confirmed"] = counts.get("kept_confirmed", 0) + 1
            continue
        conn.execute("UPDATE professors SET email_status = ?, email_detail = ?, updated_at = ? WHERE id = ?",
                     (v["status"], v["detail"], now(), r["id"]))
        counts[v["status"]] = counts.get(v["status"], 0) + 1
        if "invalid" in (v["status"], r["email_status"]):  # entering or leaving invalid changes the pipeline status
            conn.commit()
            rematch(conn, r["id"])
    conn.commit()
    left = 0
    if not pid and pending:
        left = conn.execute("SELECT COUNT(*) FROM professors WHERE email IS NOT NULL AND "
                            "(email_status IS NULL OR email_status = 'unchecked')").fetchone()[0]
    return {"checked": len(rows), **counts, "remaining": left}


def suppress(conn, value: str, reason: str | None = None) -> dict:
    value = value.strip().lower()
    conn.execute("INSERT OR REPLACE INTO suppressions (value, reason, created_at) VALUES (?, ?, ?)", (value, reason, now()))
    cur = conn.execute("UPDATE professors SET status = 'declined', status_note = ?, updated_at = ? "
                       "WHERE lower(email) = ? OR lower(email) LIKE ?", (reason or "suppressed", now(), value, f"%@{value}"))
    conn.commit()
    return {"suppressed": value, "professors_declined": cur.rowcount}


def is_suppressed(conn, email: str) -> bool:
    email = email.lower()
    return conn.execute("SELECT 1 FROM suppressions WHERE value IN (?, ?)", (email, email_domain(email))).fetchone() is not None


# --------------------------------------------------------------------------- reporting

def stats(conn, region: str | None = None) -> dict:
    where, params = ("WHERE (? IS NULL OR u.region = ?)", (region, region))
    joins = "FROM professors p JOIN universities u ON u.id = p.university_id"
    base = f"{joins} {where}"
    mbase = f"{joins} JOIN matches m ON m.professor_id = p.id {where}"
    by_status = {r[0]: r[1] for r in conn.execute(f"SELECT p.status, COUNT(*) {base} GROUP BY p.status", params)}
    by_region = {r[0] or "?": r[1] for r in conn.execute(f"SELECT u.region, COUNT(*) {base} GROUP BY u.region", params)}
    by_class = {r[0]: r[1] for r in conn.execute(f"SELECT m.classification, COUNT(*) {mbase} GROUP BY m.classification", params)}
    by_area = {r[0] or "none": r[1] for r in conn.execute(
        f"SELECT m.primary_area, COUNT(*) {mbase} AND m.classification != 'weak' GROUP BY m.primary_area", params)}
    emails = {r[0] or "none": r[1] for r in conn.execute(f"SELECT p.email_status, COUNT(*) {base} GROUP BY p.email_status", params)}
    unis = conn.execute(f"SELECT COUNT(*) FROM universities u {where}", params).fetchone()[0]
    positions = {r[0]: r[1] for r in conn.execute(
        "SELECT status, COUNT(*) FROM positions WHERE (? IS NULL OR region = ?) GROUP BY status", params)}
    return {"universities": unis, "professors": sum(by_status.values()), "by_status": by_status, "by_region": by_region,
            "match_class": by_class, "good_matches_by_area": by_area, "email_status": emails, "positions": positions}


# --------------------------------------------------------------------------- advertised positions

def merge_positions(existing: list[dict], new: list[dict]) -> list[dict]:
    """Union by URL; newer fields win."""
    by_url = {p["url"]: p for p in existing if p.get("url")}
    for p in new:
        by_url[p["url"]] = {**by_url.get(p["url"], {}), **p}
    return list(by_url.values())


def _attach_position(conn, pid: int, pos: dict) -> None:
    current = _signals(conn, pid).get("open_positions") or []
    merged = merge_positions(current, [pos])
    conn.execute("INSERT INTO signals (professor_id, open_positions) VALUES (?, ?) ON CONFLICT(professor_id) "
                 "DO UPDATE SET open_positions = excluded.open_positions", (pid, dumps(merged)))


def _university_for(conn, institution: str | None, country: str | None) -> int | None:
    if not institution:
        return None
    from gradlead.scholarly import same_institution
    uni = find_university(conn, institution)
    if uni:
        return uni["id"]
    for row in conn.execute("SELECT id, name FROM universities"):
        if same_institution(row["name"], institution):
            return row["id"]
    return add_universities(conn, [{"name": institution, "country": country,
                                     "notes": "added from an advertised position"}])["ids"][0]


def _funded(value):
    if value in (True, 1, "yes", "true", "funded"):
        return 1
    if value in (False, 0, "no", "false", "unfunded"):
        return 0
    return None


def _link_position(conn, pos_id: int, pid: int | None, uid: int | None, supervisor: str | None,
                   homepage: str | None, status: str, entry: dict) -> tuple[int | None, bool]:
    """Attach an advert to its named supervisor: an existing professor first, else add them if the ad is relevant."""
    created = False
    if not pid and uid and supervisor and status in ("relevant", "weak"):
        for p in conn.execute("SELECT id, full_name FROM professors WHERE university_id = ?", (uid,)):
            if same_person(supervisor, p["full_name"]):
                pid = p["id"]
                break
        if not pid and status == "relevant":
            res = add_professors(conn, uid, [{"full_name": supervisor, "source_url": entry["url"], "homepage": homepage}])
            pid = res["ids"][0] if res["ids"] else None
            created = bool(res["added"])
    if pid and status in ("relevant", "weak"):
        conn.execute("UPDATE positions SET professor_id = ? WHERE id = ?", (pid, pos_id))
        _attach_position(conn, pid, entry)
        conn.commit()
        rematch(conn, pid)
    return pid, created


def add_positions(conn, records: list[dict], applicant: dict | None = None) -> dict:
    from gradlead import positions as pos_mod
    added, updated, linked, new_profs, problems, out = 0, 0, 0, 0, [], []
    for r in records:
        url, title, desc = (r.get("url") or "").strip(), (r.get("title") or "").strip(), (r.get("description") or "").strip()
        if not (url and title and desc):
            problems.append({"title": title, "reason": "url, title and description (the ad text) are required"})
            continue
        if funding.is_excluded(r.get("country")):
            problems.append({"title": title, "reason": f"{r.get('country')} is excluded (funding.EXCLUDED_COUNTRIES)"})
            continue
        deadline = (r.get("deadline") or "").strip() or None
        if deadline:
            try:
                deadline = date.fromisoformat(deadline[:10]).isoformat()
            except ValueError:
                problems.append({"title": title, "reason": f"deadline '{deadline}' is not YYYY-MM-DD; stored as unknown"})
                deadline = None
        funded = _funded(r.get("funded"))
        sc = pos_mod.score_ad(title, desc, applicant)
        status = pos_mod.status_for(sc["score"], funded, deadline)
        uid = _university_for(conn, r.get("institution"), r.get("country"))
        country = r.get("country") or (find_university(conn, uid) or {}).get("country") if uid else r.get("country")
        fields = {"title": title, "institution": r.get("institution"), "university_id": uid, "country": country,
                  "region": funding.region(country) if country else None, "degree": r.get("degree"),
                  "funded": funded, "deadline": deadline, "supervisor": r.get("supervisor"),
                  "description": desc[:4000], "source": r.get("source"), "score": sc["score"],
                  "primary_area": sc["primary_area"], "terms": dumps(sc["terms"]), "status": status}
        row = conn.execute("SELECT id, professor_id FROM positions WHERE url = ?", (url,)).fetchone()
        if row:
            conn.execute(f"UPDATE positions SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                         (*fields.values(), row["id"]))
            pos_id, pid = row["id"], row["professor_id"]
            updated += 1
        else:
            cols = {"url": url, **fields, "created_at": now()}
            pos_id = conn.execute(f"INSERT INTO positions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  tuple(cols.values())).lastrowid
            pid = None
            added += 1

        pid, created = _link_position(conn, pos_id, pid, uid, r.get("supervisor"), r.get("supervisor_homepage"), status,
                                      {"title": title, "degree": r.get("degree") or "", "funded": bool(funded),
                                       "deadline": deadline, "url": url})
        linked += bool(pid and status in ("relevant", "weak"))
        new_profs += created
        out.append({"id": pos_id, "title": title[:80], "score": sc["score"], "area": sc["primary_area"],
                    "status": status, "deadline": deadline, "professor_id": pid})
    log_run(conn, "add-positions", {"added": added, "updated": updated, "linked": linked})
    conn.commit()
    return {"added": added, "updated": updated, "linked_to_professors": linked, "new_professors": new_profs,
            "problems": problems, "positions": out}


def list_positions(conn, status: str | None = "relevant", region: str | None = None, upcoming: bool = False,
                   limit: int = 50) -> list[dict]:
    rows = conn.execute("""
        SELECT p.id, p.title, p.institution, p.country, p.region, p.degree, p.funded, p.deadline, p.supervisor,
               p.professor_id, p.score, p.primary_area, p.status, p.url, pr.status AS professor_status
        FROM positions p LEFT JOIN professors pr ON pr.id = p.professor_id
        WHERE (? IS NULL OR p.status = ?) AND (? IS NULL OR p.region = ?)
          AND (? = 0 OR (p.deadline IS NOT NULL AND p.deadline >= ?))
        ORDER BY p.deadline IS NULL, p.deadline, p.score DESC LIMIT ?""",
        (status, status, region, region, int(upcoming), date.today().isoformat(), limit)).fetchall()
    today = date.today()
    out = []
    for r in rows:
        d = dict(r)
        d["days_left"] = (date.fromisoformat(d["deadline"]) - today).days if d["deadline"] else None
        out.append(d)
    return out


def refresh_positions(conn) -> dict:
    """Re-apply scoring and expiry (run daily or after editing applicant.json)."""
    from gradlead import positions as pos_mod
    counts: dict[str, int] = {}
    linked = new_profs = 0
    for r in conn.execute("SELECT * FROM positions").fetchall():
        sc = pos_mod.score_ad(r["title"], r["description"])
        st = pos_mod.status_for(sc["score"], r["funded"], r["deadline"])
        conn.execute("UPDATE positions SET score = ?, primary_area = ?, terms = ?, status = ? WHERE id = ?",
                     (sc["score"], sc["primary_area"], dumps(sc["terms"]), st, r["id"]))
        counts[st] = counts.get(st, 0) + 1
        if not r["professor_id"] and st == "relevant":
            pid, created = _link_position(conn, r["id"], None, r["university_id"], r["supervisor"], None, st,
                                          {"title": r["title"], "degree": r["degree"] or "", "funded": bool(r["funded"]),
                                           "deadline": r["deadline"], "url": r["url"]})
            linked += bool(pid)
            new_profs += created
    conn.commit()
    return {"positions": sum(counts.values()), **counts, "newly_linked": linked, "new_professors": new_profs}
