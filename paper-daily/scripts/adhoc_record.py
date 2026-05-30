#!/usr/bin/env python3
"""adhoc_record.py — resolve an ad-hoc paper link into a minimal record.

For the `/paper-daily <url>` single-link mode: take an arXiv / PDF / project URL
and emit a one-element JSON array (to stdout) that is shape-compatible with the
Scholar Inbox digest records the sub-agent reads from `_todo.json`. The sub-agent
then downloads the PDF and writes the doc as usual.

Resolution:
  - arXiv (arxiv.org/abs|pdf/<id>, or a bare 2605.27817[v2]) → arxiv_id; also
    pulls title / authors / abstract from the arXiv Atom API (best-effort).
  - URL ending in .pdf → used as the PDF `url`.
  - anything else → treated as a `project_url` (sub-agent finds the PDF on it);
    best-effort page <title> as a title hint.

`paper_id` is always an int (arXiv id digits, else a stable hash of the URL) so it
satisfies downstream schemas and namespaces work files deterministically.

Fields total_read / total_likes / ranking_score are intentionally absent (no
Scholar Inbox record) → the doc omits the 热度 line for ad-hoc papers.

stdlib only (urllib), matching scholar_inbox.py.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

UA = "paper-daily-adhoc/1.0 (+https://github.com/)"
ARXIV_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


def _get(url: str, timeout: int = 30) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with build_opener().open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except (HTTPError, URLError, Exception) as e:  # noqa: BLE001 - best effort
        print(f"warn: fetch failed {url}: {repr(e)[:120]}", file=sys.stderr)
        return None


def _arxiv_id(url: str) -> str | None:
    # bare id or inside an arxiv url
    if "arxiv.org" in url or re.fullmatch(r"\s*\d{4}\.\d{4,5}(v\d+)?\s*", url):
        m = ARXIV_RE.search(url)
        if m:
            return m.group(1)  # drop version for stability
    return None


def _arxiv_meta(arxiv_id: str) -> dict:
    """Pull title/authors/abstract from the arXiv Atom API (best-effort)."""
    out: dict = {}
    # Use https so the request routes through HTTPS_PROXY when one is configured
    # (urllib only proxies http:// via http_proxy, which may be unset).
    body = _get(f"https://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1")
    if not body:
        return out
    try:
        import xml.etree.ElementTree as ET
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(body)
        entry = root.find("a:entry", ns)
        if entry is None:
            return out
        t = entry.find("a:title", ns)
        if t is not None and t.text:
            out["title"] = re.sub(r"\s+", " ", t.text).strip()
        s = entry.find("a:summary", ns)
        if s is not None and s.text:
            out["abstract"] = re.sub(r"\s+", " ", s.text).strip()
        names = [n.text.strip() for n in entry.findall("a:author/a:name", ns) if n.text]
        if names:
            out["authors"] = ", ".join(names)
    except Exception as e:  # noqa: BLE001
        print(f"warn: arxiv parse failed: {repr(e)[:120]}", file=sys.stderr)
    return out


def _page_title(url: str) -> str | None:
    body = _get(url, timeout=20)
    if not body:
        return None
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    if m:
        return html.unescape(re.sub(r"\s+", " ", m.group(1)).strip())[:200] or None
    return None


def build_record(url: str) -> dict:
    url = url.strip()
    rec: dict = {
        "title": "", "abstract": "", "authors": "", "affiliations": [],
        "arxiv_id": None, "url": "", "html_link": "", "project_url": "",
        "github_url": None, "source": "adhoc",
    }
    aid = _arxiv_id(url)
    if aid:
        rec["arxiv_id"] = aid
        rec["url"] = f"https://arxiv.org/pdf/{aid}"
        rec["html_link"] = f"https://arxiv.org/html/{aid}"
        rec["paper_id"] = int(aid.replace(".", ""))
        rec.update(_arxiv_meta(aid))
    elif url.lower().split("?")[0].endswith(".pdf"):
        rec["url"] = url
        rec["paper_id"] = int(hashlib.md5(url.encode()).hexdigest()[:9], 16)
    else:
        rec["project_url"] = url
        rec["paper_id"] = int(hashlib.md5(url.encode()).hexdigest()[:9], 16)
        t = _page_title(url)
        if t:
            rec["title"] = t
    return rec


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit("usage: adhoc_record.py <arxiv|pdf|project URL>")
    rec = build_record(sys.argv[1])
    # emit a 1-element array (shape used by _todo.json)
    print(json.dumps([rec], ensure_ascii=False, indent=2))
    print(
        f"ok: paper_id={rec['paper_id']} arxiv={rec['arxiv_id']} "
        f"title={'(from arxiv/page)' if rec['title'] else '(sub-agent will derive from PDF)'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
