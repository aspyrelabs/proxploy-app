#!/usr/bin/env bash
# Proxploy autonomous build loop. Each run advances one step:
#   phase N, step=plan    -> /superpowers:writing-plans   (Fable 5)  -> step=execute
#   phase N, step=execute -> /superpowers:executing-plans (Sonnet 5) -> phase N+1, step=plan
# State lives in buildlog.md's <!-- STATE: --> line. Fully unattended: no phase-gate
# pause, no git, no per-call budget cap (all chosen explicitly). Systemd won't
# double-start an already-running oneshot unit, so overlap is a non-issue.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
LOG="$DIR/buildlog.md"
STATEFILE="$DIR/.build-state"
mkdir -p "$DIR/logs"
RUNLOG="$DIR/logs/build-$(date +%F).log"
MAX_PHASES=$(grep -cE '^## Phase [0-9]+' "$DIR/docs/10-build-sequence.md")

[ -f "$LOG" ] || printf '# Proxploy Build Log\n\n<!-- STATE: phase=1 step=plan -->\n' > "$LOG"
[ -f "$STATEFILE" ] || : > "$STATEFILE"

STATE_LINE=$(grep -m1 '<!-- STATE:' "$LOG")
PHASE=$(echo "$STATE_LINE" | grep -oE 'phase=[0-9]+' | cut -d= -f2)
STEP=$(echo "$STATE_LINE" | grep -oE 'step=[a-z]+' | cut -d= -f2)

if [ "$PHASE" -gt "$MAX_PHASES" ]; then
  echo "$(date -Is) all $MAX_PHASES phases complete, disabling timer" >> "$RUNLOG"
  systemctl --user disable --now proxploy-build.timer >> "$RUNLOG" 2>&1 || true
  exit 0
fi

update_state() { sed -i "s/<!-- STATE:.*-->/<!-- STATE: phase=$1 step=$2 -->/" "$LOG"; }

append_log() { # $1 heading  $2 body
  local body truncated=""
  body="$2"
  if [ ${#body} -gt 4000 ]; then
    body="${body:0:4000}"
    truncated=$'\n\n_(truncated — full output in '"$RUNLOG"')_'
  fi
  printf '\n### %s — %s\n\n%s%s\n' "$(date -Is)" "$1" "$body" "$truncated" >> "$LOG"
}

run_claude() { # $1 model alias  $2 prompt  $3 label
  local model="$1" prompt="$2" label="$3" start elapsed rc outfile
  outfile=$(mktemp)
  {
    echo "=== $(date -Is) $label (model=$model) ==="
    echo "--- prompt ---"
    echo "$prompt"
    echo "--- response (stdout+stderr) ---"
  } >> "$RUNLOG"
  start=$(date +%s)
  timeout 4h claude -p "$prompt" \
    --model "$model" \
    --permission-mode bypassPermissions \
    --disallowedTools "Bash(rm -rf /*) Bash(git push --force*)" \
    > "$outfile" 2>&1
  rc=$?
  cat "$outfile" >> "$RUNLOG"
  elapsed=$(( $(date +%s) - start ))
  echo "--- end $label (exit=$rc, ${elapsed}s) ---" >> "$RUNLOG"
  cat "$outfile"
  rm -f "$outfile"
  return "$rc"
}

if [ "$STEP" = "plan" ]; then
  echo "$(date -Is) Phase $PHASE write-plan starting (fable)" >> "$RUNLOG"
  PROMPT="/superpowers:writing-plans Write the implementation plan for Phase $PHASE only, per docs/10-build-sequence.md, using docs/00 through docs/11 in this repo as the approved spec. This is a fully unattended headless run: no human is available to answer questions or approve checkpoints mid-run, so make the best-supported call yourself and proceed to a finished, saved plan file within this single turn. End your final message with a line of exactly this form: PLAN_FILE: <path to the plan file you wrote>"
  OUT=$(run_claude "fable" "$PROMPT" "Phase $PHASE write-plan"); RC=$?
  if [ "$RC" -ne 0 ]; then
    append_log "Phase $PHASE — write-plan FAILED (exit $RC)" "See $RUNLOG for details. Will retry next run."
    exit 1
  fi
  PLAN_FILE=$(echo "$OUT" | grep -oE 'PLAN_FILE: .*' | sed 's/PLAN_FILE: //' | tail -1 | xargs)
  if [ -z "$PLAN_FILE" ] || [ ! -f "$PLAN_FILE" ]; then
    append_log "Phase $PHASE — write-plan FAILED" "No valid PLAN_FILE reported. Tail of output:\n\n\`\`\`\n$(echo "$OUT" | tail -40)\n\`\`\`\n\nWill retry next run."
    exit 1
  fi
  echo "PLAN_FILE_PHASE_$PHASE=$PLAN_FILE" >> "$STATEFILE"
  append_log "Phase $PHASE — write-plan completed (fable-5)" "Plan: $PLAN_FILE"
  update_state "$PHASE" "execute"
  exit 0
fi

# STEP = execute
PLAN_FILE=$(grep "^PLAN_FILE_PHASE_$PHASE=" "$STATEFILE" | tail -1 | cut -d= -f2-)
if [ -z "$PLAN_FILE" ]; then
  append_log "Phase $PHASE — execute-plan FAILED" "No recorded plan file for this phase. Resetting to plan step."
  update_state "$PHASE" "plan"
  exit 1
fi
echo "$(date -Is) Phase $PHASE execute-plan starting (sonnet)" >> "$RUNLOG"
PROMPT="/superpowers:executing-plans Execute the plan at $PLAN_FILE in full. This is a fully unattended headless run: no human is available to answer questions or approve checkpoints mid-run, so treat every in-plan checkpoint as auto-approved and continue straight through to a fully built, working Phase $PHASE within this single turn. End your final message with a short summary of what was built and its test/verification status."
OUT=$(run_claude "sonnet" "$PROMPT" "Phase $PHASE execute-plan"); RC=$?
if [ "$RC" -ne 0 ]; then
  append_log "Phase $PHASE — execute-plan FAILED (exit $RC)" "See $RUNLOG for details. Will retry next run (plan step is not re-run)."
  exit 1
fi
append_log "Phase $PHASE — execute-plan completed (sonnet-5)" "$OUT"
update_state "$((PHASE + 1))" "plan"
exit 0
