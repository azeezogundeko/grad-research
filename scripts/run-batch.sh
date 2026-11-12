#!/usr/bin/env bash
# Run Claude Code headless over the university grid, several universities at a time.
# Adapted from researcher/scripts/run-batch.sh.
#
#   scripts/run-batch.sh                          # every university in targets.txt, 4 in parallel
#   PARALLEL=6 scripts/run-batch.sh               # 6 headless Claude processes at once
#   scripts/run-batch.sh targets.txt 5            # only the first 5 universities
#   FILTER="Canada|Hong Kong" scripts/run-batch.sh
#   STAGE=discover scripts/run-batch.sh           # one stage: discover | find-profs
#
# Each process works on its own university, so they never fight over professors. SQLite runs in
# WAL mode with a long busy timeout, so concurrent writers are safe. Re-running resumes from the
# store. Logs go to data/logs/. Needs the `claude` CLI on PATH, logged in. Nothing is exported or
# sent: review drafts afterwards with /status and /export.
# Stop or pause with scripts/stop-batch.sh (killing only this script leaves its sessions running).
set -euo pipefail
cd "$(dirname "$0")/.."

TARGETS_FILE="${1:-targets.txt}"
MAX_TARGETS="${2:-0}"
STAGE="${STAGE:-find-profs}"
PARALLEL="${PARALLEL:-4}"
FILTER="${FILTER:-}"
CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"   # Sonnet by default; override e.g. CLAUDE_MODEL=opus
MODEL_ARGS=()
[[ -n "${CLAUDE_MODEL:-}" ]] && MODEL_ARGS=(--model "$CLAUDE_MODEL")

# Optional free API keys (OPENALEX_API_KEY, OPENALEX_MAILTO, S2_API_KEY) live in .env.
# tr strips CRLF from Windows-edited files.
if [[ -f .env ]]; then set -a; . <(tr -d '\r' < .env); set +a; fi

# One batch at a time: a second copy would process the same universities twice.
LOCK="data/batch.lock"
mkdir -p data
if [[ -f "$LOCK" ]] && kill -0 "$(cat "$LOCK")" 2>/dev/null; then
  echo "A batch is already running (pid $(cat "$LOCK")). Stop it with scripts/stop-batch.sh first." >&2
  exit 1
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

# Headless sessions otherwise kill background subagents after 600s and exit early.
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0

mkdir -p data/logs data/tmp
python3 -m gradlead targets --sync --file "$TARGETS_FILE" >/dev/null

run_one() {
  local university="$1" count="$2"
  local slug log prompt
  slug="$(echo "$university" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9-')"
  log="data/logs/$(date +%Y%m%d-%H%M%S)-${slug}.log"
  case "$STAGE" in
    find-profs) prompt="/find-profs \"$university\" $count" ;;
    discover)   prompt="/discover \"$university\" $count" ;;
    *) echo "unknown STAGE=$STAGE" >&2; return 2 ;;
  esac
  echo "[$(date +%H:%M:%S)] start $prompt → $log"
  # Permissions come from .claude/settings.json. MSYS_NO_PATHCONV stops Git Bash rewriting the
  # leading /skill into a Windows path; </dev/null stops claude eating the loop's stdin.
  if MSYS_NO_PATHCONV=1 claude -p "$prompt" "${MODEL_ARGS[@]}" --output-format text </dev/null >"$log" 2>&1; then
    echo "[$(date +%H:%M:%S)] done  $university"
  else
    echo "[$(date +%H:%M:%S)] FAIL  $university (see $log)" >&2
  fi
}

n=0
while IFS='|' read -r country university count notes; do
  [[ -z "${country// }" || "$country" == \#* ]] && continue
  if [[ -n "$FILTER" ]] && ! echo "$country|$university" | grep -Eiq "$FILTER"; then continue; fi
  n=$((n + 1))
  if [[ "$MAX_TARGETS" -gt 0 && "$n" -gt "$MAX_TARGETS" ]]; then break; fi
  while [[ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]]; do wait -n || true; done
  run_one "$university" "${count:-20}" &
done < <(tr -d '\r' < "$TARGETS_FILE")
wait

python3 -m gradlead verify >/dev/null
python3 -m gradlead stats
