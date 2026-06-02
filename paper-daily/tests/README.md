# tests

纯 stdlib `unittest`，覆盖 `scripts/` 里的几个无副作用脚本逻辑。无需网络、无需 lark-cli/飞书授权、无需 PIL。

```bash
# 从仓库根目录跑：
python3 -m unittest discover -s paper-daily/tests -v
```

- `test_feishu_push.py` —— `build_card` 把机构 + 热度渲进卡片（与索引同步）、字段缺失时降级、INDEX 行不带 score/meta。
- `test_digest_guard.py` —— 陈旧 digest 守卫的 check/record 退出码（首次 / 同日重试 / 异日陈旧+auto-skip / 显式 date / 新指纹）。
- `test_backfill_history.py` —— 历史反查透传 digest 的 `affiliations`/`total_read`/`total_likes`，并正确命中/兜底历史 doc_url。

脚本目录名带连字符（`paper-daily`）不能当包 import，故测试用 `importlib` 按文件路径加载、或直接以子进程跑 CLI（依赖目录通过 `PAPER_DAILY_STATE_DIR` / `PAPER_DAILY_WORKDIR_ROOT` 指到临时目录）。
