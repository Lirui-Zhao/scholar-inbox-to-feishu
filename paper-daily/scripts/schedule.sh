#!/usr/bin/env bash
# paper-daily scheduler — install / uninstall / status a LOCAL daily cron job that
# runs the `/paper-daily` skill headlessly via the Claude Code CLI (`claude -p`).
#
#   schedule.sh install [HH:MM]   # default 08:00
#   schedule.sh uninstall
#   schedule.sh status
#
# The cron line is tagged with "# paper-daily-cron" so uninstall/status can find it.
# Before each run it does a best-effort `lark-cli auth login --refresh` (the Feishu
# token expires after ~7 days; a fully-expired token still needs interactive re-auth).
#
# Requires: cron (crontab) + the Claude Code CLI (`claude`). On this skill's defaults
# the log goes to $PAPER_DAILY_STATE_DIR/cron.log.
set -euo pipefail

TAG="# paper-daily-cron"
STATE_DIR="${PAPER_DAILY_STATE_DIR:-$HOME/.local/share/paper-daily}"
LOG="$STATE_DIR/cron.log"

usage() {
  cat <<'EOF'
Usage:
  schedule.sh install [HH:MM]   Install a daily job (default 08:00) running /paper-daily
  schedule.sh uninstall         Remove the paper-daily cron job
  schedule.sh status            Show the current paper-daily cron job (if any)

Honors $PAPER_DAILY_STATE_DIR for the log location.
EOF
}

need_crontab() {
  if ! command -v crontab >/dev/null 2>&1; then
    echo "ERROR: 'crontab' not found — cron is not installed/enabled." >&2
    echo "  Debian/Ubuntu: sudo apt-get install -y cron && sudo service cron start" >&2
    echo "  Or use the Claude-native '/schedule' routine instead." >&2
    exit 1
  fi
}

cmd_install() {
  need_crontab
  local hhmm="${1:-08:00}"
  local hh="${hhmm%%:*}" mm="${hhmm##*:}"
  if ! [[ "$hh" =~ ^[0-9]{1,2}$ && "$mm" =~ ^[0-9]{1,2}$ ]]; then
    echo "ERROR: bad time '$hhmm' — expected HH:MM (e.g. 08:00)." >&2; exit 1
  fi
  if ! (( 10#$hh < 24 && 10#$mm < 60 )); then
    echo "ERROR: bad time '$hhmm' — hour 0-23, minute 0-59." >&2; exit 1
  fi

  local claude_bin lark_bin
  claude_bin="$(command -v claude || true)"
  if [[ -z "$claude_bin" ]]; then
    echo "ERROR: 'claude' (Claude Code CLI) not found in PATH." >&2; exit 1
  fi
  lark_bin="$(command -v lark-cli || echo lark-cli)"

  mkdir -p "$STATE_DIR"
  # $HOME is expanded by cron at run time; claude/lark/log paths are baked in now.
  local line="$mm $hh * * * cd \"\$HOME\" && \"$lark_bin\" auth login --refresh >/dev/null 2>&1; \"$claude_bin\" -p \"/paper-daily\" >> \"$LOG\" 2>&1 $TAG"

  local current
  current="$(crontab -l 2>/dev/null | grep -v -F "$TAG" || true)"
  printf '%s\n%s\n' "$current" "$line" | sed '/^[[:space:]]*$/d' | crontab -
  echo "Installed daily paper-daily job at $(printf '%02d:%02d' "$((10#$hh))" "$((10#$mm))"):"
  crontab -l | grep -F "$TAG"
  echo "Logs → $LOG"
}

cmd_uninstall() {
  need_crontab
  if crontab -l 2>/dev/null | grep -q -F "$TAG"; then
    crontab -l 2>/dev/null | grep -v -F "$TAG" | sed '/^[[:space:]]*$/d' | crontab -
    echo "Removed paper-daily cron job."
  else
    echo "No paper-daily cron job found."
  fi
}

cmd_status() {
  need_crontab
  if crontab -l 2>/dev/null | grep -q -F "$TAG"; then
    crontab -l 2>/dev/null | grep -F "$TAG"
  else
    echo "No paper-daily cron job installed."
  fi
}

case "${1:-}" in
  install)   shift || true; cmd_install "${1:-08:00}" ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *)         usage; exit 1 ;;
esac
