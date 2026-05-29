#!/usr/bin/env python3
"""Track which papers have already been analyzed (dedup state).

State file: ~/.local/share/paper-daily/seen.json  (sorted JSON array of strings)

Subcommands:
  filter --id-key KEY        stdin: JSON paper list → stdout: same list minus already-seen
  add ID [ID ...]            mark one or more IDs as seen
  list                       print all seen IDs (one per line)
  clear                      wipe state (asks no confirmation; intended for testing)
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
SEEN_FILE = STATE_DIR / "seen.json"


def load() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def write(s: set[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(s), indent=2))


def cmd_filter(id_key: str) -> None:
    seen = load()
    papers = json.load(sys.stdin)
    if not isinstance(papers, list):
        raise SystemExit("filter expects a JSON array on stdin")
    kept = [p for p in papers if str(p.get(id_key, "")).strip() and str(p[id_key]) not in seen]
    json.dump(kept, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"info: {len(papers) - len(kept)}/{len(papers)} already seen", file=sys.stderr)


def cmd_add(ids: list[str]) -> None:
    cur = load()
    new = {i.strip() for i in ids if i.strip()}
    cur |= new
    write(cur)
    print(f"ok: added {len(new)} id(s); total seen = {len(cur)}", file=sys.stderr)


def cmd_list() -> None:
    for x in sorted(load()):
        print(x)


def cmd_clear() -> None:
    if SEEN_FILE.exists():
        SEEN_FILE.unlink()
    print("ok: seen state cleared", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description="paper-daily dedup state")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("filter", help="Drop already-seen papers from stdin JSON list")
    f.add_argument("--id-key", required=True, help="Field on each paper holding its ID")

    a = sub.add_parser("add", help="Mark IDs as seen")
    a.add_argument("ids", nargs="+")

    sub.add_parser("list", help="Print all seen IDs")
    sub.add_parser("clear", help="Wipe state (testing only)")

    args = p.parse_args()
    if args.cmd == "filter":
        cmd_filter(args.id_key)
    elif args.cmd == "add":
        cmd_add(args.ids)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "clear":
        cmd_clear()


if __name__ == "__main__":
    main()
