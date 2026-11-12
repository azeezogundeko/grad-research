---
name: export
description: Produce the Quickly-ready CSV of reviewed drafts and explain the campaign setup. Usage /export [--region R] [--min-score 55] [--max-per-university 3]
---

# Export to Quickly

1. Run `python3 -m gradlead init`. If it doesn't show `cv_url_set: true`, stop and ask Azeez for the hosted CV link. It goes in `profile/applicant.json` → `links.cv_url`.
2. Run `python3 -m gradlead verify`. Emails marked `invalid` drop out automatically.
3. Run `python3 -m gradlead export $ARGUMENTS --dry-run --out exports/<date>-<region-or-all>-review.csv`. Summarise:
   - rows by region;
   - how many emails are unconfirmed;
   - the 3 lowest-scoring rows, with their subject lines.
4. **Ask before the final export.** It marks the rows `exported`, so they won't be exported again. Once confirmed, rerun without `--dry-run` and with `--out exports/<date>-<region>-quickly.csv`.
5. Remind him of the Quickly setup in `CLAUDE.md` → "Hand-off to Quickly":
   - a plain-text sequence using `{{subject}}` / `{{body}}`;
   - tracking off;
   - steps 2 and 3 with no subject, bodies `{{followup_1_body}}` / `{{followup_2_body}}`, each waiting 10 sending days (~2 weeks);
   - one campaign per region, for timezones.
