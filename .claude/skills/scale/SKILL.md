---
name: scale
description: Run the supervisor and advertised-position search across many universities in parallel waves of subagents, driven by targets.txt and the store queue. Usage /scale [--region R] [--stages positions,discover,profile,draft] [--parallel 8]
---

# Scale: parallel waves across universities

**Run everything in the foreground.** Launch subagents with `run_in_background: false`, and never background a Bash command (`verify` included; give it a long timeout instead). Wait for every result before the next stage. Don't end your turn "waiting" for something: a headless `claude -p` session exits when the turn ends, and the remaining stages never run.


Arguments (`$ARGUMENTS`):
- `--region`: limit the run to one region (Europe, Middle East, Canada, Australia, China).
- `--stages`: which stages to run (default all four).
- `--parallel`: subagents per wave (default 8, max 10).

Read `CLAUDE.md` first. Only you, the main session, can launch subagents. Keep your context small: use the subagents' one-line returns and `gradlead` output, never their transcripts.

## Budget
A session has about 200 web searches. That covers about 25 university discoveries or about 100 profiles. `scholar` and `crawl` cost nothing, so push agents to use them. For the full grid, use several sessions: `PARALLEL=4 scripts/run-batch.sh`, or `/scale` again in a fresh session. The store is the queue, so nothing is lost between sessions.

## Loop
Run the **later stage first**. That turns professors into finished drafts instead of piling up names.

1. `python3 -m gradlead targets --sync [--region R]` for progress.
2. **Draft wave:** `queue --status matched --limit <parallel × 5>`. Give **`outreach-writer`** subagents disjoint groups of 5.
3. **Profile wave:** `queue --status discovered --limit <parallel × 4>`. Give **`professor-profiler`** subagents disjoint groups of 4. Then run `verify` repeatedly until it reports `"remaining": 0` (25 emails per call, under a minute each).
4. **Positions wave** (once per session): run `refresh-positions`, then launch one **`position-scout`** per region in `--region` (or all five). Supervisors it adds come back in the next profile wave.
5. **Discovery wave:** `targets --pending discover [--region R]`. Launch one **`faculty-discoverer`** per university. Go round-robin across regions so one region doesn't absorb the budget.
6. **Checkpoint** after every wave: run `python3 -m gradlead stats` and write a one-line note (e.g. "wave 3: +40 profs, 12 strong, 9 drafted").

Rules:
- Groups must be disjoint: never give the same id to two subagents.
- Pass **ids only**. The agents load the records themselves with `show` / `uni`.
- If a subagent reports a systematic problem (a parser miss, wrong matching vocabulary), fix it in `gradlead` or `profile/applicant.json`. Then run `python3 -m pytest -q` and `python3 -m gradlead rematch`, and continue.
- Stop launching web waves when budget errors appear. Finish with draft waves, which need no web.

## Finish
Report totals from `targets` and `stats`: professors by region, strong/good counts by area, no_email count and drafts ready. **Don't export.** The human reviews the drafts first (`/export`).
