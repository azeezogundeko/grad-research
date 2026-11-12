---
name: status
description: Show the funnel - universities, professors per status, match classes, email checks, drafts. Usage /status [--region R]
---

Run `python3 -m gradlead stats $ARGUMENTS` and `python3 -m gradlead targets $ARGUMENTS`.

Summarise the results as a short table per region with these columns: universities done/total, professors, strong/good, drafted, exported, no_email.

Then list two queues:
- `queue --status matched --limit 10`: the next professors to draft.
- `queue --status drafted --limit 10`: drafts ready for review.

Use real numbers only.
