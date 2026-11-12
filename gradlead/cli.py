"""`python3 -m gradlead <command>`: every command prints JSON so Claude can read the result.

JSON inputs are a file path or `-` for stdin.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from gradlead import crawl, export, funding, match, providers, scholarly, store
from gradlead.db import ROOT, connect, db_path, log_run


def _read_json(path: str):
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def _print(obj) -> None:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def cmd_init(args, conn):
    applicant = match.load_applicant()
    return {"db": str(db_path()), "ok": True, "applicant": applicant["name"],
            "cv_url_set": bool(applicant["links"].get("cv_url")), "crawler": crawl.engine()}


def cmd_targets(args, conn):
    if args.sync:
        store.add_universities(conn, store.parse_targets(args.file))
    rows = store.target_progress(conn, args.region, args.pending)
    keys = ("goal", "professors", "to_discover", "to_profile", "to_draft", "drafted", "exported", "dropped")
    return {"totals": {k: sum(r[k] for r in rows) for k in keys}, "universities": rows[: args.limit] if args.limit else rows}


def cmd_add_unis(args, conn):
    data = _read_json(args.file)
    return store.add_universities(conn, data if isinstance(data, list) else [data])


def cmd_uni(args, conn):
    return store.find_university(conn, args.ref) or {"error": "not found"}


def cmd_add_profs(args, conn):
    data = _read_json(args.file)
    records = data.get("professors", data) if isinstance(data, dict) else data
    return store.add_professors(conn, args.university_id, records, args.directory_url, args.done)


def cmd_discovered(args, conn):
    return store.mark_university_discovered(conn, args.university_id)


def cmd_search(args, conn):
    results = providers.web_search(args.query, args.num, args.backend)
    if results is None:
        return {"error": "no search API configured (SEARXNG_URL or SERPER_API_KEY); use the WebSearch tool instead"}
    return results


def cmd_providers(args, conn):
    return providers.status()


def cmd_crawl(args, conn):
    url = args.target
    if url.isdigit():
        prof = store.get_professor(conn, int(url))
        url = prof.get("homepage") or prof.get("lab_url") or prof.get("profile_url")
        if not url:
            return {"error": "professor has no homepage or profile URL; search for it first"}
    return crawl.crawl(url, args.max_pages, args.max_chars)


def cmd_queue(args, conn):
    return store.queue(conn, args.status, args.limit, args.university, args.region, args.min_score)


def cmd_show(args, conn):
    return store.get_professor(conn, args.professor_id, brief=args.brief)


def cmd_set_status(args, conn):
    return store.set_status(conn, args.professor_id, args.status, args.note)


def cmd_scholar(args, conn):
    prof = store.get_professor(conn, args.professor_id)
    uni = store.find_university(conn, prof["university_id"])
    inst = uni.get("openalex_id")
    if not inst and not args.openalex_id and not args.s2_id:
        try:
            inst = scholarly.institution_id(uni["name"])
        except OSError:
            inst = None
        if inst:
            conn.execute("UPDATE universities SET openalex_id = ? WHERE id = ?", (inst, uni["id"]))
            conn.commit()
    result = scholarly.lookup(prof["full_name"], uni["name"], inst, args.openalex_id or prof.get("openalex_id"),
                              args.s2_id, years=args.years)
    return store.save_scholar(conn, args.professor_id, result)


def cmd_save_profile(args, conn):
    return store.save_profile(conn, args.professor_id, _read_json(args.file))


def cmd_drop_pubs(args, conn):
    return store.drop_publications(conn, args.professor_id, args.publication_ids or None, args.source)


def cmd_rematch(args, conn):
    return store.rematch(conn, args.professor_id) if args.professor_id else store.rematch_all(conn)


def cmd_save_draft(args, conn):
    return store.save_draft(conn, args.professor_id, _read_json(args.file))


def cmd_applicant(args, conn):
    a = match.load_applicant()
    return {"name": a["name"], "sign_off_name": a["sign_off_name"], "credential": a["credential"],
            "seeking": a["seeking"], "areas": {k: v["label"] for k, v in a["areas"].items()},
            "projects": {k: {"name": p["name"], "url": p["url"], "areas": p["areas"], "facts": p["facts"]}
                         for k, p in a["projects"].items()},
            "other_facts": a["other_facts"], "signature_appended": a["signature"]}


def cmd_funding(args, conn):
    return funding.info(args.country)


def cmd_verify(args, conn):
    return store.verify_emails(conn, args.professor, pending=not args.all, limit=args.limit)


def cmd_suppress(args, conn):
    return store.suppress(conn, args.value, args.reason)


def cmd_add_positions(args, conn):
    data = _read_json(args.file)
    return store.add_positions(conn, data.get("positions", data) if isinstance(data, dict) else data)


def cmd_positions(args, conn):
    status = None if args.status == "all" else args.status
    return store.list_positions(conn, status, args.region, args.upcoming, args.limit)


def cmd_refresh_positions(args, conn):
    return store.refresh_positions(conn)


def cmd_stats(args, conn):
    return store.stats(conn, args.region)


def cmd_export(args, conn):
    statuses = tuple(args.email_status.split(","))
    records = export.rows(conn, min_score=args.min_score, region=args.region, country=args.country,
                          email_statuses=statuses, max_per_university=args.max_per_university,
                          include_exported=args.include_exported,
                          count_prior_exports=not args.per_batch_cap)
    out = Path(args.out) if args.out else ROOT / "exports" / f"{date.today()}-quickly.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(export.to_csv(records), encoding="utf-8")
    if not args.dry_run:
        export.mark_exported(conn, [r["professor_id"] for r in records])
        log_run(conn, "export", {"file": str(out), "rows": len(records)})
        conn.commit()
    by_region: dict[str, int] = {}
    for r in records:
        by_region[r["region"]] = by_region.get(r["region"], 0) + 1
    return {"file": str(out), "rows": len(records), "by_region": by_region, "marked_exported": not args.dry_run,
            "unconfirmed_emails": sum(1 for r in records if r["email_status"] == "unconfirmed")}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gradlead", description="Grad-school professor research store")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database, check applicant profile").set_defaults(fn=cmd_init)

    s = sub.add_parser("targets", help="progress per university (--sync loads targets.txt first)")
    s.add_argument("--sync", action="store_true")
    s.add_argument("--file", default=str(ROOT / "targets.txt"))
    s.add_argument("--region", choices=["Europe", "Middle East", "Canada", "Australia", "China", "Turkey", "USA"])
    s.add_argument("--pending", choices=["discover", "profile", "draft"])
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_targets)

    s = sub.add_parser("add-unis", help="add universities: JSON list of {name, country, city, goal, notes}")
    s.add_argument("file")
    s.set_defaults(fn=cmd_add_unis)

    s = sub.add_parser("uni", help="one university by id or name, with funding rules")
    s.add_argument("ref")
    s.set_defaults(fn=cmd_uni)

    s = sub.add_parser("add-profs", help="add faculty found in a directory (dedupe by name per university)")
    s.add_argument("university_id", type=int)
    s.add_argument("file")
    s.add_argument("--directory-url")
    s.add_argument("--done", action="store_true", help="mark this university's discovery finished")
    s.set_defaults(fn=cmd_add_profs)

    s = sub.add_parser("discovered", help="mark a university's faculty discovery finished")
    s.add_argument("university_id", type=int)
    s.set_defaults(fn=cmd_discovered)

    s = sub.add_parser("search", help="web results via self-hosted SearXNG (SEARXNG_URL), else Serper; no session budget")
    s.add_argument("query")
    s.add_argument("--num", type=int, default=10)
    s.add_argument("--backend", choices=["auto", "searxng", "serper"], default="auto")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("providers", help="which search / mailbox-check services are configured")
    s.set_defaults(fn=cmd_providers)

    s = sub.add_parser("crawl", help="read a homepage/directory locally (crawl4ai if installed, else urllib)")
    s.add_argument("target", help="professor id or URL")
    s.add_argument("--max-pages", type=int, default=6)
    s.add_argument("--max-chars", type=int, default=crawl.MAX_CHARS_PER_PAGE)
    s.set_defaults(fn=cmd_crawl)

    s = sub.add_parser("queue", help="next professors at a pipeline stage")
    s.add_argument("--status", default="discovered", choices=store.STATUSES)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--university", type=int)
    s.add_argument("--region")
    s.add_argument("--min-score", type=int)
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("show", help="everything known about a professor")
    s.add_argument("professor_id", type=int)
    s.add_argument("--brief", action="store_true", help="writer view: hook candidates first, abstracts trimmed")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("set-status")
    s.add_argument("professor_id", type=int)
    s.add_argument("status", choices=store.STATUSES)
    s.add_argument("--note")
    s.set_defaults(fn=cmd_set_status)

    s = sub.add_parser("scholar", help="resolve author on OpenAlex (fallback Semantic Scholar) and store recent papers")
    s.add_argument("professor_id", type=int)
    s.add_argument("--openalex-id", help="A… id when the name is ambiguous")
    s.add_argument("--s2-id", help="Semantic Scholar author id")
    s.add_argument("--years", type=int, default=4)
    s.set_defaults(fn=cmd_scholar)

    s = sub.add_parser("save-profile", help="store homepage research, then score the match")
    s.add_argument("professor_id", type=int)
    s.add_argument("file")
    s.set_defaults(fn=cmd_save_profile)

    s = sub.add_parser("drop-pubs", help="remove papers wrongly attributed to a professor, then re-score")
    s.add_argument("professor_id", type=int)
    s.add_argument("publication_ids", type=int, nargs="*")
    s.add_argument("--source", choices=["openalex", "s2", "homepage"], help="drop everything from one lookup source")
    s.set_defaults(fn=cmd_drop_pubs)

    s = sub.add_parser("rematch", help="re-score one professor, or everyone profiled")
    s.add_argument("professor_id", type=int, nargs="?")
    s.set_defaults(fn=cmd_rematch)

    s = sub.add_parser("save-draft", help="validate and store a first-contact email draft")
    s.add_argument("professor_id", type=int)
    s.add_argument("file")
    s.set_defaults(fn=cmd_save_draft)

    sub.add_parser("applicant", help="CV facts the writer may use").set_defaults(fn=cmd_applicant)

    s = sub.add_parser("funding", help="admission/funding pattern for a country")
    s.add_argument("country")
    s.set_defaults(fn=cmd_funding)

    s = sub.add_parser("verify", help="check emails: MX + present on the cited page")
    s.add_argument("--professor", type=int)
    s.add_argument("--all", action="store_true", help="re-check already checked emails")
    s.add_argument("--limit", type=int, default=25, help="emails per call; small so one call stays well under a minute")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("suppress", help="do-not-contact an email or domain (e.g. after a decline)")
    s.add_argument("value")
    s.add_argument("--reason")
    s.set_defaults(fn=cmd_suppress)

    s = sub.add_parser("add-positions", help="save advertised PhD/MSc positions; scores them and links supervisors")
    s.add_argument("file")
    s.set_defaults(fn=cmd_add_positions)

    s = sub.add_parser("positions", help="advertised positions, soonest deadline first")
    s.add_argument("--status", default="relevant", choices=["relevant", "weak", "expired", "unfunded", "all"])
    s.add_argument("--region")
    s.add_argument("--upcoming", action="store_true", help="only positions with a future deadline")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_positions)

    sub.add_parser("refresh-positions", help="re-score positions and mark expired ones").set_defaults(
        fn=cmd_refresh_positions)

    s = sub.add_parser("stats", help="funnel counts")
    s.add_argument("--region")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("export", help="write the Quickly-ready CSV and mark rows exported")
    s.add_argument("--min-score", type=int, default=match.GOOD)
    s.add_argument("--region")
    s.add_argument("--country")
    s.add_argument("--email-status", default="confirmed", help="add ,unconfirmed to include emails the code could not re-find on their source")
    s.add_argument("--max-per-university", type=int, default=3)
    s.add_argument("--include-exported", action="store_true")
    s.add_argument("--per-batch-cap", action="store_true",
                   help="apply --max-per-university to this batch only (by default earlier exports count toward it)")
    s.add_argument("--dry-run", action="store_true", help="write the file without marking rows exported")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_export)
    return p


def main(argv: list[str] | None = None) -> int:
    providers.load_env()
    args = build_parser().parse_args(argv)
    conn = connect()
    try:
        _print(args.fn(args, conn))
        return 0
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        _print({"error": str(exc)})
        return 1
    finally:
        conn.close()
