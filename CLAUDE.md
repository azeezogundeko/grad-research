# Grad-school Professor Researcher

This repo is a Claude Code workspace that **finds and qualifies prospective PhD / research-MSc supervisors** for Azeez Ogundeko in Europe, the Middle East, Canada, Australia, China, Turkey and the USA, and writes a first-contact email for each strong match. Claude does the research: reading faculty directories, homepages and lab pages. The `gradlead` Python package does the bookkeeping: storage, dedupe, OpenAlex/Semantic Scholar lookups, **deterministic match scoring**, draft validation, email checks and the Quickly export. **Nothing is sent from here.** Sending happens in Quickly (`../Quickly`) after a human reviews the CSV.

## The applicant
`profile/applicant.json` is the only source of truth about Azeez. It holds the research areas with their matching vocabularies, the projects with the facts each one may claim, and the signature. Run `python3 -m gradlead applicant` to read it. **Never state anything about him that isn't in that file.** In brief:
- B.Sc. Electronics and Computer Engineering, LASU, First Class (4.59/5.0, 2024).
- Wants a funded **research MSc first** (thesis MSc, MPhil, research Master's), with a PhD also welcome, starting **September 2027**. **USA is the exception: PhD first** (US PhDs admit from a BSc; funded MS is rare).
- Research areas:
  - `speech`: low-resource African languages, ASR/TTS, code-switching, Nigerian Pidgin. Evidence: Vonative.
  - `trustworthy_llm`: grounded, citation-backed extraction; LLM proposes, rules decide. Evidence: Toyyib.
  - `hitl_agents`: graduated autonomy, escalation. Evidence: Sarah AI.
  - `multimodal`: real-time voice and vision. Evidence: InvigilX and Vonative.

## Pipeline
| Stage | Skill / agent | Persisted with |
|---|---|---|
| Load the university grid | — | `targets --sync` (reads `targets.txt`) |
| Find faculty | `/discover` → `faculty-discoverer` subagents | `add-profs` (`--done` closes the university) |
| **Advertised positions** | `/positions` → `position-scout` subagents (job boards, vacancy pages) | `add-positions` (scores, links supervisor, +20 boost), `positions --upcoming` |
| Profile + score | `/profile` → `professor-profiler` subagents | `scholar`, `save-profile` (scores in code) |
| Check emails | — | `verify` |
| Write emails | `/draft` → `outreach-writer` subagents | `save-draft` (validated in code) |
| Report / hand-off | `/status`, `/export` | `stats`, `export` |
| One university end to end | `/find-profs <university> [count]` | all of the above |
| **Many universities** | `/scale [--region R] [--parallel 8]` | `targets` shows progress |

Each professor's status is the work queue:
`discovered → matched | weak_match | inactive | no_email | unreachable | duplicate → drafted → exported`, plus `declined` (suppressed).

Score classes:
- `strong` is ≥75 and `good` is ≥55. Only these reach `matched` (score is from `match.py`).
- `inactive` means emeritus, moved, not faculty, or no paper in the last 3 years.
- `no_email` means no published address was found.

## The CLI
Run `python3 -m gradlead <command>` from the repo root. It prints JSON. JSON input is a file path or `-` for stdin. The DB is `data/grad.db` (override with `GRADLEAD_DB`).
```
init | applicant | funding COUNTRY | stats [--region R]
targets [--sync] [--region R] [--pending discover|profile|draft]
uni ID_OR_NAME | add-unis FILE | add-profs UNI_ID FILE [--directory-url URL] [--done] | discovered UNI_ID
crawl ID_OR_URL [--max-pages 6] [--max-chars 6000]          # local fetch, no search budget
search "QUERY" [--num 10] [--backend auto|searxng|serper] | providers   # free web search (SearXNG)
queue --status discovered|matched|... [--limit N] [--university ID] [--region R] [--min-score N]
show ID [--brief] | set-status ID STATUS [--note]
scholar ID [--openalex-id A…] [--s2-id …]                    # OpenAlex → recent papers, topics, h-index
save-profile ID FILE | rematch [ID] | save-draft ID FILE
drop-pubs ID [PUB_ID ...] [--source openalex|s2|homepage]   # remove same-name authors' papers, re-scores
verify [--professor ID] [--all] | suppress EMAIL_OR_DOMAIN [--reason]
add-positions FILE | positions [--status relevant|weak|expired|unfunded|all] [--region R] [--upcoming] | refresh-positions
export [--min-score 55] [--region R] [--max-per-university 3] [--dry-run] [--out PATH]
```
Write temporary JSON to `data/tmp/`, and **include the professor or university id in the file name** (`data/tmp/profile-42.json`). Many agents run in parallel. Piping to `-` avoids temp files.

## JSON contracts
Unknown means `null`, `false` or `"unknown"`. Never guess.

**add-profs** (`faculty-discoverer`), a list of:
`{full_name, title, department, lab_name, lab_url, homepage, profile_url, source_url, interests[], email, email_source_url}`
- `source_url` is required: the directory or page where you saw the person.
- `email` is accepted only together with `email_source_url`.

**save-profile** (`professor-profiler`):
```json
{
  "full_name": "Jane Doe", "title": "Assistant Professor", "department": "Computer Science",
  "lab_name": "Speech Lab", "lab_url": "https://…", "homepage": "https://…",
  "email": "jdoe@cs.uni.edu", "email_source_url": "https://… page where the address is shown",
  "research_interests": ["speech recognition", "low-resource languages"],
  "summary": "Two sentences on what the group works on now, in your words.",
  "accepting_students": "yes|no|unknown",
  "accepting_quote": "exact sentence from the page", "accepting_url": "https://…",
  "open_positions": [{"title": "PhD position in robust ASR", "degree": "PhD|MSc|RA", "funded": true,
                      "deadline": "2026-12-01", "url": "https://…"}],
  "status_flags": {"emeritus": false, "moved_to": null, "not_faculty": false},
  "publications": [{"title": "…", "year": 2026, "venue": "…", "url": "https://…"}],
  "pages_read": ["https://…"]
}
```
- `accepting_students` other than `unknown` needs both the exact quote and the URL, or the code downgrades it.
- `publications` are for papers you saw on the homepage that OpenAlex missed. Each one needs a `url`.
- If the person can't be found, or isn't real faculty there, send `{"unreachable": true, "reason": "…"}`.

**save-draft** (`outreach-writer`):
`{hook_publication_id, cv_project, programme, subject, body}`
- The code checks all of the following:
  - the hook is one of the professor's stored papers;
  - `cv_project` is a key in `applicant.json` and its name appears in the body;
  - the body is 100–190 words and greets the professor by surname;
  - there are no placeholders or banned phrases;
  - every number is backed by `applicant.json`, the hook paper, an open position or a plausible intake year.
- The body ends with a closing line such as "Best regards,". **The code appends the signature**, including the CV link.

**add-positions** (`position-scout`), a list of:
`{url, title, institution, country, degree, funded, deadline, supervisor, supervisor_homepage, source, description}`
- `url`, `title` and `description` (the advert's real text, which is scored) are required.
- `deadline` is `YYYY-MM-DD` or null.
- Status is `relevant` (score ≥48, funded or unknown, not expired), `weak`, `unfunded` or `expired`.
- A relevant advert's named supervisor is linked to an existing professor, or added as a new one in `discovered`. The advert joins their `open_positions`, which gives the +20 openings boost while it is open.

## Hard rules
1. **Public academic information only.** Faculty directories, personal and lab homepages, university news, Google Scholar / DBLP / OpenAlex / ORCID / arXiv / ACL Anthology. Don't log in anywhere. Don't bypass robots blocks or paywalls.
2. **Evidence-only, validated emails.** Save an address only if you saw it published on a homepage, a university page or the author block of their paper PDF (arXiv / ACL Anthology), and give `email_source_url`. `verify` re-fetches that page or PDF and only `confirmed` addresses (re-found there, domain has MX) are exported. Never construct one from a pattern. Undo obvious obfuscation such as `jdoe [at] uni [dot] edu`. If none is published, leave it null. `no_email` is an acceptable outcome.
3. **Never invent people, papers, positions or quotes.** Every professor needs a `source_url`. Every hook paper must exist in the store. Every "accepting students" claim needs an exact quote and its URL.
4. **Never misstate the applicant.** Use only `applicant.json` facts. No inflated claims, and no numbers that aren't there.
5. **Don't send anything.** No emails or forms. This repo only produces reviewed drafts and a CSV.
6. **Respect people's time.** Export caps at 3 professors per university by default. Honour `suppress` for anyone who declines or asks not to be contacted.
7. **Report honestly.** Give real counts from `stats` and `export`, including `no_email` and `weak_match`.

## Conventions
- **Who counts as relevant faculty:** people who can supervise (assistant, associate and full professors; lecturers and readers in the UK and Australia; tenure-track group leaders). Include postdocs only when the directory lists them as PIs. Relevant departments are CS, EE/ECE, informatics, AI institutes, and linguistics or speech groups when they do computational work.
- **Search:** use `python3 -m gradlead search "<query>"` (self-hosted SearXNG, Serper fallback; same services as `../researcher`, keys read from `.env` or `../researcher/.env`). It has no session budget. The WebSearch tool (about 200 searches per session) is the fallback. `python3 -m gradlead providers` shows what is configured.
- **Mailbox check:** when `REACHER_URL` is set, `verify` also asks our Reacher backend. A rejected mailbox becomes `invalid`; a deliverable one upgrades `unconfirmed` to `confirmed`. It only checks published addresses, never guesses.
- **Excluded countries:** `funding.EXCLUDED_COUNTRIES` (Israel). Targets, adverts and exports skip them.
- **Search budget:** Prefer `python3 -m gradlead crawl <url>`, which reads pages locally and uses no search budget, and use WebFetch when JS is needed. Rough costs: discovering a university ≈ 3–8 searches; profiling a professor ≈ 1–3 (`scholar` costs none).
- **China:** many faculty pages are Chinese-only. Read them anyway. Names may appear family-name first, and the code handles both orders.
- **Region-specific advice for drafts:** `python3 -m gradlead funding <country>`. Prefer a specific open position the profiler recorded over the general pattern.
- **Model: Claude Sonnet.** All three subagents set `model: sonnet`, and `scripts/run-batch.sh` defaults to `--model sonnet` (override with `CLAUDE_MODEL=opus`). For interactive runs, start the session with `claude --model sonnet`.
- **Subagents run in the foreground** (`run_in_background: false`), and every stage waits for them. Headless sessions kill background agents when they end. `scripts/run-batch.sh` also sets `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`.
- Tests: `python3 -m pytest -q`.

## Hand-off to Quickly
1. Set `links.cv_url` in `profile/applicant.json` to a hosted PDF. Export refuses to run without it.
2. Run `python3 -m gradlead verify`, then `python3 -m gradlead export --dry-run`. Export includes **confirmed emails only**; add `--email-status confirmed,unconfirmed` only after checking the unconfirmed ones yourself. Review the CSV by hand, then run the export without `--dry-run`. That marks the rows `exported`.
3. In Quickly, create a campaign with a **plain-text** sequence (`is_html` off). Turn open and click tracking off: university mail filters penalise it, and it isn't needed.
   - Step 1: subject `{{subject}}`, body `{{body}}`.
   - Step 2: no subject (replies in the same thread), body `{{followup_1_body}}`, wait **10 sending days** (~2 weeks).
   - Step 3: no subject, body `{{followup_2_body}}`, wait **10 more sending days**.
   - Quickly's "Use default 3-step sequence" sets these steps but with the B2B waits (3, 4): change both to 10.
   - `export` builds both follow-ups per professor from stored facts only (`export.followups`). Follow-up 1 names the hook paper and adds one new point: an advertised position, else a second matching project, and offers the CV and a one-page proposal. Follow-up 2 is a short last note asking for a colleague's name in the matched area.
   - Keep stop-on-reply on. Send on weekdays within the recipient's working hours. Each region has its own timezone, so use one campaign per region (`--region`).
4. Import the CSV at `POST /api/campaigns/{id}/leads/import` or through the UI. Every column becomes a `{{variable}}`.
5. When someone declines or asks not to be contacted, run `python3 -m gradlead suppress <email>`.
