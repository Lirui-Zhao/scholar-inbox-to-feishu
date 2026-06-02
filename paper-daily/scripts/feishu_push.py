#!/usr/bin/env python3
"""Send paper-daily 汇总卡片到飞书 DM / 群聊（via 官方 lark-cli）。

仅一个子命令：

  send-card --date YYYY-MM-DD --records-json <FILE> [--receiver <ID>]
      读取 records JSON（list of {paper_id, title, score, doc_url,
      affiliations?, total_read?, total_likes?}），构造 Feishu interactive
      card，调 lark-cli im +messages-send 发出。每篇标题下展示「机构 + 热度」
      一行（与当日索引文档同步），字段缺失（如单链接模式）则自动省略。
      receiver 默认 = `lark-cli auth status` 里的本人 open_id；
      也可显式指定 ou_xxx（user DM）或 oc_xxx（群聊）。

Hard requirement: `lark-cli auth login --scope "im:message.send_as_user"` 完成过。

历史：
  - 2026-05-28 早：feishu_push.py 初版有 upload 子命令，走 drive +import HTML→docx。
    实测排版崩、公式乱码、图导不进。
  - 2026-05-28 晚：sub-agent 改成直接构造 DocxXML，HTML 路径废弃，本脚本的 upload 删除。
    保留 send-card —— 推完文档后仍要发汇总卡片。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

LARK_CLI = "lark-cli"

# .env location is configurable via PAPER_DAILY_CONFIG_DIR (see README "Configuration").
CONFIG_DIR = Path(os.environ.get("PAPER_DAILY_CONFIG_DIR")
                  or Path.home() / ".claude" / "skills" / "paper-daily" / "config")


def env_receiver() -> str | None:
    """Resolve FEISHU_RECEIVER from environment, then from the .env file."""
    v = os.environ.get("FEISHU_RECEIVER")
    if v and v.strip():
        return v.strip()
    envf = CONFIG_DIR / ".env"
    if envf.exists():
        for raw in envf.read_text().splitlines():
            line = raw.strip()
            if line.startswith("#") or not line.startswith("FEISHU_RECEIVER="):
                continue
            return line.partition("=")[2].strip().strip('"').strip("'") or None
    return None


def extract_json(text: str) -> dict:
    """lark-cli stdout 含日志/进度行，定位第一个 '{' 用 raw_decode。"""
    idx = text.find("{")
    if idx < 0:
        raise ValueError(f"no JSON in output:\n{text[-500:]}")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[idx:])
    return obj


def run_lark(args: list[str]) -> dict:
    p = subprocess.run([LARK_CLI] + args, capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout)[-600:]
        raise SystemExit(f"lark-cli {' '.join(args[:3])}… failed (exit {p.returncode}):\n{tail}")
    try:
        return extract_json(p.stdout)
    except ValueError as e:
        raise SystemExit(f"lark-cli {' '.join(args[:3])}… returned no JSON:\n{e}")


def get_self_open_id() -> str:
    p = subprocess.run([LARK_CLI, "auth", "status"], capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"lark-cli auth status failed: {p.stderr.strip()}")
    data = json.loads(p.stdout)
    open_id = data.get("identities", {}).get("user", {}).get("openId")
    if not open_id:
        raise SystemExit("no user openId in `lark-cli auth status`; run `lark-cli auth login` first")
    return open_id


def _fmt_affiliations(aff) -> str:
    """机构缩写（与索引文档表格同口径）：list 取前 1-2 个、顿号连接、>2 追加「 等」；
    str 原样；空 → ''。"""
    if not aff:
        return ""
    if isinstance(aff, str):
        items = [aff.strip()] if aff.strip() else []
    else:
        items = [str(a).strip() for a in aff if str(a).strip()]
    if not items:
        return ""
    head = "、".join(items[:2])
    return f"{head} 等" if len(items) > 2 else head


def _meta_line(r: dict) -> str:
    """卡片每篇标题下的「机构 + 热度」单行，与当日索引文档的机构/🔥热度列同步。

    机构空则省机构块；total_read / total_likes 仅在为 int 时各自加入；
    全部缺失（如单链接模式）返回 '' → 调用方不渲染该行。
    """
    parts: list[str] = []
    inst = _fmt_affiliations(r.get("affiliations"))
    if inst:
        parts.append(f"🏛 {inst}")
    heat = []
    read, likes = r.get("total_read"), r.get("total_likes")
    if isinstance(read, int) and not isinstance(read, bool):
        heat.append(f"👀 {read}")
    if isinstance(likes, int) and not isinstance(likes, bool):
        heat.append(f"👍 {likes}")
    if heat:
        parts.append(" · ".join(heat))
    return "　·　".join(parts)


def build_card(date_str: str, records: list[dict]) -> dict:
    """构造飞书 interactive card.

    Record 字段：
      paper_id:     int | "INDEX"
      title:        str
      doc_url:      str
      score:        float (paper 才有；INDEX 不显示 score)
      is_index:     bool (可选；paper_id == "INDEX" 也视为 is_index)
      affiliations: list[str] | str (可选；机构，缩写后上卡片)
      total_read:   int (可选；👀 已读数)
      total_likes:  int (可选；👍 点赞数)
    """
    # is_index 排除在 paper 计数外
    paper_count = sum(
        1 for r in records
        if not (r.get("is_index") or r.get("paper_id") == "INDEX")
    )

    elements: list[dict] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"今天共 **{paper_count}** 篇，按相关性排序。",
            },
        },
        {"tag": "hr"},
    ]
    for i, r in enumerate(records):
        is_index = r.get("is_index") or r.get("paper_id") == "INDEX"
        title = r.get("title", "(no title)").strip()
        doc_url = r.get("doc_url", "")
        if is_index:
            # INDEX 条目：纯 title + 链接，没有 score / 机构 / 热度 / paper_id
            content_md = f"**{title}**\n📖 [打开]({doc_url})"
        else:
            score = float(r.get("score", 0))
            meta = _meta_line(r)   # 机构 + 热度，与索引同步；缺字段则为空
            head = f"**[{score:.3f}] {title}**"
            content_md = (f"{head}\n{meta}\n📖 [打开]({doc_url})" if meta
                          else f"{head}\n📖 [打开]({doc_url})")
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": content_md},
        })
        if i < len(records) - 1:
            elements.append({"tag": "hr"})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📚 {date_str} · 今日论文 {paper_count} 篇",
            },
            "template": "blue",
        },
        "elements": elements,
    }


def cmd_send_card(args: argparse.Namespace) -> None:
    receiver = args.receiver or env_receiver() or get_self_open_id()

    records_path = Path(args.records_json)
    if not records_path.is_file():
        raise SystemExit(f"records file not found: {records_path}")
    records = json.loads(records_path.read_text())
    if not isinstance(records, list) or not records:
        raise SystemExit("records JSON must be a non-empty list")

    card = build_card(args.date, records)

    if receiver.startswith("oc_"):
        target = ["--chat-id", receiver]
    elif receiver.startswith("ou_"):
        target = ["--user-id", receiver]
    else:
        raise SystemExit(f"receiver must start with oc_ (chat) or ou_ (user): {receiver}")

    result = run_lark([
        "im", "+messages-send",
        *target,
        "--msg-type", "interactive",
        "--content", json.dumps(card, ensure_ascii=False),
        "--as", "user",
    ])

    if not result.get("ok"):
        raise SystemExit(f"send failed:\n{json.dumps(result, ensure_ascii=False)[:500]}")

    msg_id = result.get("data", {}).get("message_id", "?")
    print(f"ok: card sent to {receiver}, message_id={msg_id}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Send paper-daily 汇总卡片到飞书（via lark-cli）"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("send-card", help="Send daily summary card to Feishu user/chat")
    sc.add_argument("--date", required=True, help="YYYY-MM-DD")
    sc.add_argument("--records-json", required=True,
                    help="list[{paper_id, title, score, doc_url, affiliations?, "
                         "total_read?, total_likes?}] 的 JSON 文件")
    sc.add_argument("--receiver", help="ou_xxx (user) 或 oc_xxx (chat); 默认 = 本人 open_id")

    args = p.parse_args()
    if args.cmd == "send-card":
        cmd_send_card(args)


if __name__ == "__main__":
    main()
