---
name: find-profs
description: End-to-end supervisor search for one university - discover faculty, profile and score them, check emails, write drafts. Usage /find-profs <university> [count]
---

# Find professors (end to end)

**Run everything in the foreground.** Launch subagents with `run_in_background: false`, and never background a Bash command (`verify` included; give it a long timeout instead). Wait for every result before the next stage. Don't end your turn "waiting" for something: a headless `claude -p` session exits when the turn ends, and the remaining stages never run.


Arguments: `$ARGUMENTS` → a university (name or id) and an optional count (default 25).

Read `CLAUDE.md` first. Run the stages in order. Each stage persists its results, so a crash loses at most one batch.

1. **Discover**: follow `.claude/skills/discover/SKILL.md`. Skip it if the university is already marked discovered.
2. **Profile**: follow `.claude/skills/profile/SKILL.md` with `--university <id> --limit <count>`.
3. **Verify**: `python3 -m gradlead verify` checks 25 emails per call and takes under a minute. Run it in the foreground and repeat it until it reports `"remaining": 0`.
4. **Draft**: follow `.claude/skills/draft/SKILL.md` with `--university <id>`.
5. **Report** honest numbers in this order:
   - the funnel: discovered → profiled → strong/good matches → with confirmed email → drafted;
   - a short table of the top 5: name, title, score, area, hook paper, accepting-students signal;
   - the gaps: no_email, weak_match, ambiguous authors.

In headless runs (`claude -p`), finish without asking questions. Make reasonable choices and note them in the report. **Do not export here.** Export happens after a human reviews the drafts.
