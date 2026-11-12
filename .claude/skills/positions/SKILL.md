---
name: positions
description: Find advertised funded PhD / research-MSc positions matching the applicant, link them to supervisors, and list deadlines. Usage /positions [--region R] [--count 15]
---

# Advertised positions

**Run everything in the foreground.** Launch subagents with `run_in_background: false`, and never background a Bash command (`verify` included; give it a long timeout instead). Wait for every result before the next stage. Don't end your turn "waiting" for something: a headless `claude -p` session exits when the turn ends, and the remaining stages never run.


Arguments: `$ARGUMENTS` → an optional `--region` (default: all five) and `--count` per region (default 15).

1. Run `python3 -m gradlead refresh-positions`. This marks adverts whose deadline has passed and re-scores the rest.
2. Launch one **`position-scout`** subagent per region **in a single message**. Pass each one only the region and the count. Order the regions Europe, China, Middle East, Canada, Australia, because Europe and Hong Kong advertise the most and have the earliest deadlines.
3. New supervisors linked from adverts start in `discovered`. Profile them next with `/profile` (they need papers and a validated email before drafting). For them the writer should mention the specific advert.
4. **Report the deadlines:** run `python3 -m gradlead positions --upcoming` and show a table sorted by deadline with these columns: days left, title, institution, degree, score/area, supervisor, professor status, URL. Flag anything due within 30 days. Then add the counts from `stats` → `positions`.

Use real numbers only. If a region had no relevant adverts, say so.
