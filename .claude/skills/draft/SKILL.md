---
name: draft
description: Write validated first-contact emails for matched professors. Usage /draft [--university ID] [--region R] [--limit 20]
---

# Draft emails

**Run everything in the foreground.** Launch subagents with `run_in_background: false`, and never background a Bash command (`verify` included; give it a long timeout instead). Wait for every result before the next stage. Don't end your turn "waiting" for something: a headless `claude -p` session exits when the turn ends, and the remaining stages never run.


Arguments: `$ARGUMENTS` → optional `--university`, `--region` and `--limit` (default 20).

1. Run `python3 -m gradlead queue --status matched --limit <limit> [...]`. It returns the highest scores first.
2. Split the ids into disjoint groups of 5. Launch **`outreach-writer`** subagents in one message, passing only ids. They need no web access.
3. Spot-check two drafts with `python3 -m gradlead show <id>`. Read the full body. Check that the hook paper is real (open its URL) and that the claims match `applicant.json`. If a draft is generic or wrong, say so, then fix the writer prompt or re-draft.
4. Report how many were drafted and the subject lines of the first 5.
