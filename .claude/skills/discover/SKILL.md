---
name: discover
description: Find relevant supervising faculty at one university and save them to the store. Usage /discover <university name or id> [count]
---

# Discover faculty

**Run everything in the foreground.** Launch subagents with `run_in_background: false`, and never background a Bash command (`verify` included; give it a long timeout instead). Wait for every result before the next stage. Don't end your turn "waiting" for something: a headless `claude -p` session exits when the turn ends, and the remaining stages never run.


Arguments: `$ARGUMENTS` → a university (name or id) and an optional count N (default: the university's goal, else 25).

1. Run `python3 -m gradlead targets --sync` so `targets.txt` is loaded, then `python3 -m gradlead uni "<university>"`.
   If the university isn't there, add it with `add-unis` (`[{"name","country","notes"}]`), then look it up again.
2. If `targets --pending discover` doesn't list this university, discovery is already done. Report that and stop.
3. Launch one **`faculty-discoverer`** subagent with the university id and N. For a very large university (Toronto, Tsinghua, ETH, Edinburgh), launch two in one message instead: one for CS/informatics, one for EE/speech/linguistics groups.
4. Report: `added`, the areas seen, and the directories used.
