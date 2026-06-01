#!/usr/bin/env python3
"""Stale-digest guard.

Scholar Inbox is downstream of arXiv (announces Sun-Thu 20:00 ET), so a fresh
digest only exists Mon-Fri. On a dateless day (weekend / holiday / before today's
digest has regenerated) the API SILENTLY re-serves the most recent digest. This
guard detects that by fingerprinting the full set of paper_ids: if the same set
comes back on a different calendar day than the one we last *processed*, it's a
stale fallback and the caller should skip (no re-built docs / cards).

State file: ~/.local/share/paper-daily/last_digest.json
  { "date": "YYYY-MM-DD", "fingerprint": "<sha256hex>", "paper_ids": [...], "n": N }
  — the last digest we actually processed.

The fingerprint JSON consumed here is produced by `scholar_inbox.py digest --fp-out`.

Subcommands:
  check  --fp FILE --date YYYY-MM-DD [--auto-skip]
         Exit 0  → proceed (not stale / explicit backfill / first run / fail-safe)
         Exit 10 → stale AND --auto-skip given → caller should silently skip
  record --fp FILE --date YYYY-MM-DD
         Persist this digest as "last processed". Call only when actually proceeding.

Fail-safe: any unreadable/corrupt input exits 0 (the guard must never block a run).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# State dir is configurable via PAPER_DAILY_STATE_DIR (see README "Configuration").
STATE_DIR = Path(os.environ.get("PAPER_DAILY_STATE_DIR")
                 or Path.home() / ".local" / "share" / "paper-daily")
LAST_FILE = STATE_DIR / "last_digest.json"

PROCEED = 0   # not stale, or explicit --date, or first run, or fail-safe
SKIP = 10     # stale + --auto-skip → caller should skip silently


def load_fp(path: str) -> dict:
    """Read the fingerprint JSON written by scholar_inbox.py --fp-out."""
    try:
        d = json.loads(Path(path).read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_last() -> dict:
    if not LAST_FILE.exists():
        return {}
    try:
        d = json.loads(LAST_FILE.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}  # corrupted → treat as no state → fail-safe (not stale)


def write_last(date: str, cur: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LAST_FILE.write_text(json.dumps({
        "date": date,
        "fingerprint": cur.get("fingerprint", ""),
        "paper_ids": cur.get("paper_ids", []),
        "n": cur.get("n", len(cur.get("paper_ids", []))),
    }, ensure_ascii=False, indent=2))


def cmd_check(fp_path: str, date: str, auto_skip: bool) -> int:
    cur = load_fp(fp_path)
    if not cur.get("fingerprint"):
        print(f"warn: no usable fingerprint at {fp_path}; proceeding (fail-safe)", file=sys.stderr)
        return PROCEED

    last = load_last()
    stale = (bool(last)
             and last.get("fingerprint") == cur["fingerprint"]
             and last.get("date") != date)

    if not stale:
        if not last:
            print("info: no prior digest recorded (first run); proceeding", file=sys.stderr)
        elif last.get("fingerprint") == cur["fingerprint"]:
            print(f"info: same digest as today's earlier run ({date}); proceeding (retry)", file=sys.stderr)
        else:
            print("info: new digest; proceeding", file=sys.stderr)
        return PROCEED

    # stale: same paper set as a digest we processed on a different day
    if auto_skip:
        print(f"stale: digest fingerprint matches the one processed on {last.get('date')} "
              f"(now {date}); likely weekend/holiday or today's digest not yet generated → auto-skip",
              file=sys.stderr)
        return SKIP
    print(f"note: served digest looks stale (same set as {last.get('date')}); "
          f"processing anyway (explicit --date)", file=sys.stderr)
    return PROCEED


def cmd_record(fp_path: str, date: str) -> int:
    cur = load_fp(fp_path)
    if not cur.get("fingerprint"):
        print(f"warn: no usable fingerprint at {fp_path}; not recording", file=sys.stderr)
        return PROCEED
    write_last(date, cur)
    print(f"ok: recorded digest for {date} ({cur.get('n', '?')} ids) to {LAST_FILE}", file=sys.stderr)
    return PROCEED


def main() -> None:
    p = argparse.ArgumentParser(description="paper-daily stale-digest guard")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="Decide whether the fetched digest is a stale fallback")
    c.add_argument("--fp", required=True, help="Fingerprint JSON from scholar_inbox.py --fp-out")
    c.add_argument("--date", required=True, help="Archive date YYYY-MM-DD (today, or --date day)")
    c.add_argument("--auto-skip", action="store_true",
                   help="Return exit 10 on a stale digest (default run, no --date)")

    r = sub.add_parser("record", help="Persist this digest as last-processed")
    r.add_argument("--fp", required=True, help="Fingerprint JSON from scholar_inbox.py --fp-out")
    r.add_argument("--date", required=True, help="Archive date YYYY-MM-DD")

    args = p.parse_args()
    if args.cmd == "check":
        sys.exit(cmd_check(args.fp, args.date, args.auto_skip))
    elif args.cmd == "record":
        sys.exit(cmd_record(args.fp, args.date))


if __name__ == "__main__":
    main()
