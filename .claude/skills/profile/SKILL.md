---
name: profile
description: Profile discovered professors (OpenAlex papers, homepage email, recruiting signals) so the code can score the match. Usage /profile [--university ID] [--region R] [--limit 20]
---

# Profile professors

**Run everything in the foreground.** Launch subagents with `run_in_background: false`, and never background a Bash command (`verify` included; give it a long timeout instead). Wait for every result before the next stage. Don't end your turn "waiting" for something: a headless `claude -p` session exits when the turn ends, and the remaining stages never run.


Arguments: `$ARGUMENTS` → optional `--university`, `--region` and `--limit` (default 20).

1. Get the queue: `python3 -m gradlead queue --status discovered --limit <limit> [--university …] [--region …]`. Keep only the ids.
2. Split the ids into disjoint groups of 4. Launch up to 5 **`professor-profiler`** subagents **in a single message**, one group each, passing only ids.
3. Check new emails against their cited pages: `python3 -m gradlead verify` checks 25 emails per call and takes under a minute. Run it in the foreground and repeat it until it reports `"remaining": 0`.
4. Report from `python3 -m gradlead stats`: counts per status and match class, plus the top matches (`queue --status matched --limit 10`): name, university, score, area.
