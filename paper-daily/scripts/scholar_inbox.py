#!/usr/bin/env python3
"""Minimal Scholar Inbox API client (stdlib only).

Subcommands:
  login                              one-time sha_key auth, persists cookies
  digest [--date MM-DD-YYYY]
         [--limit N]
         [--out FILE]                fetch today's (or given date's) digest as JSON

Config sources (in priority order):
  1. environment variables
  2. ~/.claude/skills/paper-daily/config/.env  (KEY=VALUE per line)

Required:
  SCHOLAR_INBOX_SHA_KEY              the hex token, OR
  SCHOLAR_INBOX_LOGIN_URL            full magic-link URL with ?sha_key=...

State:
  ~/.local/share/paper-daily/cookies.txt   LWP-format cookie jar
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.cookiejar import LWPCookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

API_BASE = "https://api.scholar-inbox.com"
LOGIN_TPL = "/api/login/{sha_key}/"
DIGEST = "/api/"

# Paths are configurable via env vars (see README "Configuration"); these are the defaults.
CONFIG_DIR = Path(os.environ.get("PAPER_DAILY_CONFIG_DIR")
                  or Path.home() / ".claude" / "skills" / "paper-daily" / "config")
ENV_FILE = CONFIG_DIR / ".env"
STATE_DIR = Path(os.environ.get("PAPER_DAILY_STATE_DIR")
                 or Path.home() / ".local" / "share" / "paper-daily")
COOKIE_FILE = STATE_DIR / "cookies.txt"

UA = "paper-daily/0.1 (+https://github.com/anthropics/claude-code)"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("SCHOLAR_INBOX_SHA_KEY", "SCHOLAR_INBOX_LOGIN_URL"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def resolve_sha_key(env: dict[str, str]) -> str:
    sha = env.get("SCHOLAR_INBOX_SHA_KEY")
    if sha:
        return sha.strip()
    url = env.get("SCHOLAR_INBOX_LOGIN_URL")
    if url:
        qs = parse_qs(urlparse(url).query)
        if qs.get("sha_key"):
            return qs["sha_key"][0]
    raise SystemExit(
        f"Missing SCHOLAR_INBOX_SHA_KEY (or SCHOLAR_INBOX_LOGIN_URL) — "
        f"populate {ENV_FILE}"
    )


def make_opener(jar: LWPCookieJar):
    return build_opener(HTTPCookieProcessor(jar))


def load_jar() -> LWPCookieJar:
    jar = LWPCookieJar(str(COOKIE_FILE))
    if COOKIE_FILE.exists():
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as e:  # pragma: no cover
            print(f"warn: failed to load cookies ({e}); will re-login", file=sys.stderr)
    return jar


def save_jar(jar: LWPCookieJar) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    jar.save(ignore_discard=True, ignore_expires=True)


def http_get(opener, path: str) -> tuple[int, bytes]:
    url = API_BASE + path
    req = Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, r.read()
    except HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except URLError as e:
        raise SystemExit(f"Network error contacting {url}: {e.reason}")


def cmd_login(env: dict[str, str]) -> None:
    sha = resolve_sha_key(env)
    jar = LWPCookieJar(str(COOKIE_FILE))
    status, body = http_get(make_opener(jar), LOGIN_TPL.format(sha_key=sha))
    if status >= 400:
        snippet = body[:300].decode("utf-8", "replace")
        raise SystemExit(f"Login failed: HTTP {status}\n{snippet}")
    # Server may return HTTP 200 with {"success": false, "reason": "..."} on bad sha_key.
    try:
        payload = json.loads(body)
        if isinstance(payload, dict) and payload.get("success") is False:
            reason = payload.get("reason", "(no reason given)")
            raise SystemExit(f"Login rejected by server: {reason}")
    except json.JSONDecodeError:
        pass  # non-JSON body (e.g. redirect) is acceptable as long as cookies got set
    if not list(jar):
        snippet = body[:200].decode("utf-8", "replace")
        raise SystemExit(
            "Login returned 2xx but no cookies were set. "
            f"Response body:\n{snippet}"
        )
    save_jar(jar)
    print(f"ok: logged in, {len(list(jar))} cookie(s) saved to {COOKIE_FILE}", file=sys.stderr)


def extract_paper_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("digest_df", "papers", "results", "items", "data"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    top = list(data.keys()) if isinstance(data, dict) else type(data).__name__
    raise SystemExit(f"Unexpected digest response shape; top-level: {top}")


def cmd_digest(env: dict[str, str], date: str | None, limit: int | None, out: str | None) -> None:
    jar = load_jar()
    if not list(jar):
        cmd_login(env)
        jar = load_jar()

    path = DIGEST + (f"?date={date}" if date else "")
    status, body = http_get(make_opener(jar), path)

    if status in (401, 403):
        print("cookies expired, re-authenticating…", file=sys.stderr)
        cmd_login(env)
        jar = load_jar()
        status, body = http_get(make_opener(jar), path)

    if status >= 400:
        snippet = body[:300].decode("utf-8", "replace")
        raise SystemExit(f"Digest fetch failed: HTTP {status}\n{snippet}")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        snippet = body[:300].decode("utf-8", "replace")
        raise SystemExit(f"Digest response was not JSON:\n{snippet}")

    papers = extract_paper_list(data)

    # Sort by ranking_score desc so "Top N" is genuinely the top N (the API may
    # not pre-sort). Stable sort preserves API order on ties; missing/None scores
    # sink to the end. A legitimate 0.0 is NOT treated as missing.
    def _score(p):
        v = p.get("ranking_score") if isinstance(p, dict) else None
        return v if isinstance(v, (int, float)) else float("-inf")

    papers = sorted(papers, key=_score, reverse=True)

    if limit is not None and limit > 0:
        papers = papers[:limit]

    rendered = json.dumps(papers, ensure_ascii=False, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(rendered)
        print(f"ok: wrote {len(papers)} papers to {out}", file=sys.stderr)
    else:
        print(rendered)


def main() -> None:
    p = argparse.ArgumentParser(description="Scholar Inbox CLI (minimal, stdlib-only)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Authenticate via sha_key (run once; cookies persist)")

    d = sub.add_parser("digest", help="Fetch today's (or a given date's) digest")
    d.add_argument("--date", help="MM-DD-YYYY (default: today, server-side)")
    d.add_argument("--limit", type=int, default=None, help="Truncate to top N papers")
    d.add_argument("--out", help="Write JSON to FILE (default: stdout)")

    args = p.parse_args()
    env = load_env()

    if args.cmd == "login":
        cmd_login(env)
    elif args.cmd == "digest":
        cmd_digest(env, args.date, args.limit, args.out)


if __name__ == "__main__":
    main()
