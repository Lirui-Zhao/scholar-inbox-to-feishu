#!/usr/bin/env python3
"""backfill_history.py — paper-daily「全 seen」当天的历史反查。

当某天 digest 经去重后 _todo.json 为空（这一批论文此前都已建过飞书深读文档），
我们不重复出文档，但仍要生成当日索引 + 发汇总卡片，并让每篇的「深度阅读」链接
*前指* 到既有的历史文档。本脚本就负责把 digest 里每篇的历史 doc_url / 中文标题 /
一句话总结从过往的 ~/papers-daily/<别的日期>/ 反查出来。

每个 paper_id 的反查来源（优先级从高到低）：
  doc_url : 历史 _feishu_records.json  →  _token_<pid>.json
  title   : 历史 _feishu_records.json 的中文标题  →  _docx_plan_<pid>.json 首块 <title>  →  digest 原 title
  summary : _docx_plan_<pid>.json 首块「一句话总结」callout（可空）
  score   : 取自 *今天的* digest（ranking_score），不取历史
多个历史日期都建过同一篇时，取**日期最新**的那次（YYYY-MM-DD 目录名字典序 = 时间序）。

用法：
  python3 backfill_history.py --digest <digest.json> --out <history_records.json> [--exclude-date YYYY-MM-DD]
  cat digest.json | python3 backfill_history.py --out history_records.json   # digest 也可走 stdin

输出（JSON 数组，保持 digest 原顺序，即 ranking 降序）：
  [{paper_id, title, score, doc_url, summary, source_date, found, fallback_url}, ...]
  - found=true  : doc_url 是合法历史飞书文档链接，索引/卡片直接用它
  - found=false : doc_url 为空（历史目录可能被清理）；fallback_url 给出 digest 里的原文链接
                  （项目页/PDF/arXiv/GitHub），调用方可降级指向原文并标注「(原文)」
"""
import sys
import os
import re
import json
import glob
import argparse

WORKDIR_ROOT = os.environ.get("PAPER_DAILY_WORKDIR_ROOT", os.path.expanduser("~/papers-daily"))

# 租户无关：docx / docs / wiki 三种都算合法飞书文档链接
DOC_URL_RE = re.compile(r"^https://[^/]+\.feishu\.(?:cn|com)/(?:docx|docs|wiki)/")
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_doc_url(u):
    return isinstance(u, str) and bool(DOC_URL_RE.match(u))


def _strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _date_dirs(exclude_date):
    """所有形如 YYYY-MM-DD 的历史工作目录，按日期升序（旧→新），排除 exclude_date。"""
    out = []
    for p in sorted(glob.glob(os.path.join(WORKDIR_ROOT, "*"))):
        name = os.path.basename(p)
        if not DATE_DIR_RE.match(name):
            continue
        if exclude_date and name == exclude_date:
            continue
        if os.path.isdir(p):
            out.append((name, p))
    return out


def _scan_history(exclude_date):
    """扫历史目录，返回 pid(str) -> {doc_url,title,summary,source_date}。日期新者覆盖旧者。"""
    table = {}

    def put(pid, **kv):
        pid = str(pid)
        rec = table.setdefault(pid, {"doc_url": "", "title": "", "summary": "", "source_date": ""})
        for k, v in kv.items():
            if v:  # 只用非空值覆盖
                rec[k] = v

    for date_name, d in _date_dirs(exclude_date):  # 升序遍历 → 新日期自然覆盖旧的
        # 1) _feishu_records.json：一次拿到多篇的中文标题 + doc_url（最可靠）
        fr = os.path.join(d, "_feishu_records.json")
        if os.path.isfile(fr):
            try:
                for r in json.load(open(fr, encoding="utf-8")):
                    if r.get("is_index"):
                        continue
                    if _valid_doc_url(r.get("doc_url", "")):
                        put(r["paper_id"], doc_url=r["doc_url"], title=r.get("title", ""), source_date=date_name)
            except Exception:
                pass
        # 2) _token_<pid>.json：doc_url 兜底
        for tf in glob.glob(os.path.join(d, "_token_*.json")):
            try:
                t = json.load(open(tf, encoding="utf-8"))
                if _valid_doc_url(t.get("doc_url", "")):
                    put(t["paper_id"], doc_url=t["doc_url"], source_date=date_name)
            except Exception:
                pass
        # 3) _docx_plan_<pid>.json 首块：中文 <title> + 一句话总结（title/summary 兜底）
        for pf in glob.glob(os.path.join(d, "_docx_plan_*.json")):
            m_pid = re.search(r"_docx_plan_(\d+)\.json$", pf)
            if not m_pid:
                continue
            pid = m_pid.group(1)
            try:
                blocks = json.load(open(pf, encoding="utf-8"))
                c0 = blocks[0]["content"] if blocks and isinstance(blocks[0], dict) else ""
            except Exception:
                continue
            mt = re.search(r"<title>(.*?)</title>", c0, re.S)
            ms = re.search(r"一句话总结</b>\s*[：:]\s*(.*?)</p>", c0, re.S)
            kv = {"source_date": date_name}
            if mt:
                kv["title"] = _strip_tags(mt.group(1))
            if ms:
                kv["summary"] = _strip_tags(ms.group(1))
            put(pid, **kv)
    return table


def _fallback_url(p):
    for k in ("project_url", "url", "html_link", "github_url"):
        v = p.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return ""


def main():
    ap = argparse.ArgumentParser(description="paper-daily 历史反查（全 seen 当天用）")
    ap.add_argument("--digest", help="digest JSON 数组路径；省略则从 stdin 读")
    ap.add_argument("--out", help="输出路径；省略则打印到 stdout")
    ap.add_argument("--exclude-date", default="", help="排除的日期目录（通常是今天，避免自引用）")
    args = ap.parse_args()

    raw = open(args.digest, encoding="utf-8").read() if args.digest else sys.stdin.read()
    digest = json.loads(raw)
    if not isinstance(digest, list):
        sys.exit("digest 必须是 JSON 数组")

    table = _scan_history(args.exclude_date)

    out = []
    for p in digest:
        pid = p.get("paper_id")
        hit = table.get(str(pid), {})
        doc_url = hit.get("doc_url", "")
        found = _valid_doc_url(doc_url)
        score = p.get("ranking_score")
        out.append({
            "paper_id": pid,
            "title": hit.get("title") or p.get("title") or "",
            "score": round(score, 3) if isinstance(score, (int, float)) else None,
            "doc_url": doc_url if found else "",
            "summary": hit.get("summary", ""),
            "source_date": hit.get("source_date", ""),
            "found": found,
            "fallback_url": _fallback_url(p),
        })

    payload = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload)
        n_found = sum(1 for r in out if r["found"])
        print(f"ok: {n_found}/{len(out)} papers backfilled from history -> {args.out}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
