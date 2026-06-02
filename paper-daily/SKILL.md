---
name: paper-daily
description: |
  每日定时把 Scholar Inbox 推荐的 Top N 论文，逐篇做成飞书云文档（DocxXML 原生格式，
  storytelling 风格 + 图文交错），用 Workflow 编排并发加速、每篇带质量校验，机器人发汇总
  卡片到本人 DM。自带去重、文件夹按日期归档、首次运行交互式问 Scholar Inbox 密钥。
  方法论与 DocxXML 语法已抽到 references/，主 agent 只做编排。适合 /schedule routine 每日触发。
---

# Paper Daily — 每日论文深度解析 → 飞书云文档

⚠️ **生产级指令。你（主 agent）的职责：编排。** 拉今日 digest → 去重 → 用 Workflow 把每篇派给一个 sub-agent 做成飞书云文档（storytelling、含真实公式/图/表/代码、图文交错），归档到 `paper-daily/YYYY-MM-DD/` 文件夹（按需单篇归 `paper-daily/单篇精读/`）→ 建当日索引 doc → 发汇总卡片到本人 DM。**单篇文档的写法不在本文件，在 `references/paper-writeup-guide.md`，sub-agent 自己读。**

## 用户调用形态

```
/paper-daily                       # 今日 Top 8，自动推飞书
/paper-daily --limit 3             # Top 3（调试少跑几篇）
/paper-daily --date 05-27-2026     # 补跑某天（MM-DD-YYYY，Scholar Inbox 日期格式）
/paper-daily --parallel 2          # 并发提示（实际并发由 Workflow 自动 cap，见 Round 3）
/paper-daily --no-feishu           # 跳过 Round 4 索引 doc + 卡片（每篇 doc 仍建；调试索引/卡片用）
/paper-daily --dry-run             # 只拉 digest 看今天推什么，不跑 sub-agent
/paper-daily setup                 # 显式触发 Scholar Inbox 密钥配置
```

**参数解析**：`--limit N`（默认 8）、`--date MM-DD-YYYY`（默认今天）、`--parallel N`（默认 4，仅作 hint）、`--no-feishu`（跳过 Round 4）、`--dry-run`（跳过 Round 3+）、`setup`（子命令，与其他 flag 互斥）。

## 关键路径

| 用途 | 路径 |
|---|---|
| Scholar Inbox 密钥 | `~/.claude/skills/paper-daily/config/.env` |
| Scholar Inbox 脚本 | `~/.claude/skills/paper-daily/scripts/scholar_inbox.py` |
| 去重脚本 | `~/.claude/skills/paper-daily/scripts/seen.py` |
| 陈旧 digest 守卫 | `~/.claude/skills/paper-daily/scripts/digest_guard.py`（check / record） |
| 飞书卡片脚本 | `~/.claude/skills/paper-daily/scripts/feishu_push.py`（仅 send-card） |
| 图片抽取脚本 | `~/.claude/skills/paper-daily/scripts/fetch_images.py` |
| **单篇写作方法论** | `~/.claude/skills/paper-daily/references/paper-writeup-guide.md`（sub-agent 必读） |
| **DocxXML 语法 + lark-cli 食谱** | `~/.claude/skills/paper-daily/references/feishu-docxml.md`（主 agent + sub-agent 共用） |
| **Workflow 编排脚本** | `~/.claude/skills/paper-daily/workflows/build-docs.js` |
| 当日本地工作目录 | `~/papers-daily/YYYY-MM-DD/` |
| 去重状态 | `~/.local/share/paper-daily/seen.json` |
| 上期 digest 指纹（陈旧守卫） | `~/.local/share/paper-daily/last_digest.json` |
| 文件夹状态（飞书 token 缓存） | `~/.local/share/paper-daily/folder_state.json` |
| Scholar Inbox cookies | `~/.local/share/paper-daily/cookies.txt` |
| 飞书 docs/im skill | `~/.claude/skills/lark-doc/`、`~/.claude/skills/lark-im/` |

飞书环境准备、OAuth 授权、scope 说明 → 见 `references/feishu-docxml.md`。

## 配置项（环境变量，均有默认值，可覆盖）

下面各 Round 用这些变量；用户可在 shell / cron 里 `export` 覆盖。完整说明见仓库 README「Configuration」。

| 变量 | 默认 | 作用 |
|---|---|---|
| `PAPER_DAILY_STATE_DIR` | `~/.local/share/paper-daily` | seen.json / last_digest.json / cookies.txt / folder_state.json |
| `PAPER_DAILY_WORKDIR_ROOT` | `~/papers-daily` | 每日工作目录（PDF / 图 / plan-JSON） |
| `PAPER_DAILY_CONFIG_DIR` | `~/.claude/skills/paper-daily/config` | `.env` 所在 |
| `FEISHU_ROOT_FOLDER` | `paper-daily` | 飞书云端根文件夹名 |
| `PAPER_DAILY_LIMIT` / `PAPER_DAILY_PARALLEL` | `8` / `4` | 默认篇数 / 并发提示（CLI flag 优先） |

脚本（`scholar_inbox.py` / `seen.py` / `digest_guard.py` / `feishu_push.py`）已读 `PAPER_DAILY_STATE_DIR` / `PAPER_DAILY_CONFIG_DIR` / `FEISHU_RECEIVER`；本 SKILL 的 bash 用 `${VAR:-默认}` 形式。

## 单链接模式（`/paper-daily <url>`）

当位置参数是一个 http(s) 链接（arxiv / 项目页 / PDF）时，**跳过 Scholar Inbox**（不走 Round 1/2/2.5 与 Round 4 索引），只解析这一篇并推给用户。

> **「单篇精读」= 按需单篇**（你手动 `/paper-daily <url>` 点的单篇），区别于每日批量；统一放在根夹下的固定子夹 `${FEISHU_ROOT_FOLDER:-paper-daily}/单篇精读`，不再用 adhoc / 时间戳命名。

1. **预检 + 文件夹**：照 Round 0 预检；确保根文件夹存在（用 [Round 0.5 的幂等「确保根夹」逻辑](#ensure-root-folder)——校验缓存/按名查重后复用，找不到才建），并建/复用一个**固定**的单篇子文件夹 `${FEISHU_ROOT_FOLDER:-paper-daily}/单篇精读`——token 缓存到 `folder_state.json` 顶层的 `single_folder_token`（复用规则：非空且 `lark-cli drive files list` 校验有效则用；否则在根夹里找 `name==单篇精读` 的 folder，找到复用、没有才 `lark-cli drive +create-folder --name "单篇精读" --folder-token <root_token>` 建）。
2. **解析链接成记录**：
   ```bash
   WORKDIR=${PAPER_DAILY_WORKDIR_ROOT:-$HOME/papers-daily}/adhoc   # 本地临时目录，对应云端的「单篇精读」夹；保留原名即可
   mkdir -p "$WORKDIR"
   python3 ~/.claude/skills/paper-daily/scripts/adhoc_record.py '<url>' > "$WORKDIR/_todo.json"
   ```
   （arxiv 自动取标题/作者/摘要；其它来源标题留空，sub-agent 从 PDF 提取。`paper_id` 为脚本生成的稳定 int。）
3. **建文档**：用 `build-docs.js` 跑这 1 篇，`args.indexDocUrl: ""`（无返回索引、**仍有点赞链接**），`dateFolderToken` = 单篇精读 子文件夹 token（`single_folder_token`），`workdir` = 上面的 adhoc 目录，`papers` = `[{paper_id, title}]`。**不读/不写 seen.json**（显式按需请求）；幂等 `_token_{paper_id}.json` 防重复建。Workflow 不可用则手动单个 Agent（briefing 同 Round 3.4，INDEX_URL 留空）。
4. **推送**：从返回里取成功那篇，构造**单条** records（无 INDEX 条目）跑 `feishu_push.py send-card`，并把 `doc_url` 回给用户；失败直接报原因。

> 单链接模式没有 digest 的热度字段，doc 顶部仍有「去 Scholar Inbox 点赞」链接，但 meta 不显示 👀/👍 热度。

---

## 强制工作流

### Round 0：环境自检 + 首次 setup ⛔

**0a. 依赖 + 认证预检**（fail-fast，给修复指引）：

```bash
for t in pdfimages pdftoppm lark-cli; do command -v $t >/dev/null || echo "⚠️ 缺 $t"; done
python3 -c "import urllib.request, json, subprocess" || echo "⚠️ python3 stdlib 异常"
python3 -c "import PIL" 2>/dev/null || echo "ℹ️ 无 PIL（fetch_images 仍可跑，只是不量尺寸/去重）"

# 飞书认证（缺 lark-cli 时自动跳过此块）
command -v lark-cli >/dev/null && lark-cli auth status > /tmp/_lark_auth.json 2>/dev/null && python3 - <<'PY'
import json
try: d = json.load(open("/tmp/_lark_auth.json"))
except Exception as e: print("⚠️ 无法解析 auth status:", e); raise SystemExit
oid = d.get("identities", {}).get("user", {}).get("openId")
print("openId:", "OK" if oid else "⚠️ 空 → lark-cli auth login --domain docs,drive,im")
blob = json.dumps(d)   # 容错：整 blob 里找 scope 子串，不假设字段名
for s in ("im:message.send_as_user", "docx:document", "drive:drive"):
    print(f"  scope {s}:", "OK" if s in blob else "⚠️ 缺 → auth login --domain docs,drive,im")
PY
```

- 缺 `pdfimages`/`pdftoppm`（poppler）→ 提示装 poppler-utils（影响抓图，非致命）。
- 缺 `lark-cli` 或 openId 空 / scope 缺 / 过期 → 提示 `lark-cli auth login --domain docs,drive,im`（过期可试 `--refresh`，部分版本如 v1.0.43 无此 flag 则直接重登）。
- 字段读不到只 warn 不硬挂——auth status 输出格式可能随版本变。

**0b. Scholar Inbox 密钥**：

```bash
test -f ~/.claude/skills/paper-daily/config/.env && echo present || echo missing
```

- `setup` 子命令 → 无视已有 .env 重新进交互式 setup。
- .env 存在 → 跳到 Round 0.5。
- .env 缺失（首次）：① `AskUserQuestion` 问用户粘贴 Scholar Inbox 登录 URL；② 写入 .env + `chmod 600`；③ 跑 `python3 scholar_inbox.py login` 验证；rejected 则删 .env 再问，最多 2 次重试。

### Round 0.5：飞书文件夹就绪 ⛔

读 `${PAPER_DAILY_STATE_DIR:-~/.local/share/paper-daily}/folder_state.json`。核心原则：**校验缓存 token 是否仍有效 + 云端按名查重后复用，找不到才建**——状态文件一旦丢失/重置，绝不盲目再建一个同名根夹。

1. **不存在** → 创建空 `{"paper_daily_root_token": "", "single_folder_token": "", "date_folders": {}}`。

2. <a name="ensure-root-folder"></a>**确保根夹（幂等）**——这套逻辑单链接模式也会复用：
   a. `paper_daily_root_token` **非空** → 先校验它仍有效（被删/进回收站则失效）：
      ```bash
      lark-cli drive files list --params "{\"folder_token\":\"$ROOT_TOKEN\"}"
      # 解析：从 stdout 第一个 `{` 截取再 json.loads（前面可能有 [WARN] proxy 行）；勿 2>&1。
      # 报错 / 查不到 → 视作失效，当作空处理（往下走 b）。
      ```
   b. **失效或为空** → 先在**云盘根**（`folder_token` 传空串 `""`）列子项，找 `type=="folder"` 且 `name==${FEISHU_ROOT_FOLDER:-paper-daily}` 的：
      ```bash
      lark-cli drive files list --params '{"folder_token":""}'
      # 同样从第一个 `{` 截取再 json.loads；结果在 data.files[]（每项有 name/token/type）。
      ```
      · **恰好 1 个** → 复用其 `token`，写回 `paper_daily_root_token`（**不要新建**）；
      · **>1 个** → 告警并停下，提示用户「云端有多个同名根夹（`${FEISHU_ROOT_FOLDER:-paper-daily}`），请先整顿/合并后再跑」（绝不盲目再建第 N 个）；
      · **0 个** → 才新建：`lark-cli drive +create-folder --name "${FEISHU_ROOT_FOLDER:-paper-daily}"`，解析 `data.folder_token` 写回。

3. **确保当日日期子夹（幂等）**：先 list 根夹子项，若已存在 `type=="folder"` 且 `name==YYYY-MM-DD` 的 → 复用其 `token` 写回 `date_folders["YYYY-MM-DD"]`；**否则才建** `lark-cli drive +create-folder --name "YYYY-MM-DD" --folder-token <root_token>`，写回。杜绝重复日期夹。

4. 最终 `DATE_FOLDER_TOKEN` = 当日日期夹 token，供 Round 3 / Round 4 用。

### Round 1：拉取 digest ⛔

```bash
DATE=$(date +%F)                                              # 归档日期（--date 仅改 digest 拉取日，不改归档日，可按需对齐）
WORKDIR=${PAPER_DAILY_WORKDIR_ROOT:-$HOME/papers-daily}/$DATE
mkdir -p "$WORKDIR"
LIMIT=${LIMIT:-${PAPER_DAILY_LIMIT:-8}}                        # CLI --limit 优先，其次 env，默认 8

python3 ~/.claude/skills/paper-daily/scripts/scholar_inbox.py digest \
    --limit "$LIMIT" \
    {如果传了 --date：加 --date MM-DD-YYYY} \
    --out "$WORKDIR/_digest.json" \
    --fp-out "$WORKDIR/_digest_fp.json"        # 全量 digest 指纹，供 Round 1.6 守卫
```

脚本已按 `ranking_score` 降序排序再截断，所以 "Top N" 名副其实。读 `_digest.json` 给用户打印简短列表（标题 / 分数 / id）。

### Round 1.5：识别每篇论文的来源 ⛔

digest 每个对象**必有**：`paper_id`(int)、`title`、`abstract`、`authors`、`affiliations`、`ranking_score`、`display_venue`、`url`、`source`。**可能 None**：`arxiv_id`（CVPR 等会议爬虫源常为 None）、`github_url`、`project_url`。

### Round 1.6：陈旧 digest 守卫（防周末/节假日/过早重复）⛔

Scholar Inbox 上游是 arXiv（announce 窗口周日–周四 20:00 ET），所以**新 digest 只在工作日（周一–周五）产生，周六周日没有**。请求一个没有 digest 的日期时，Scholar Inbox 会**静默回退**返回最近一期（不报错）。若不识别，周末会把周五那期当「全 seen」再发一遍卡片（连刷 3 天重复）。

用 digest 指纹（全量 `paper_id` 集合的 sha256，由 Round 1 的 `--fp-out` 写出）对比上次**真正处理过**的那期：

```bash
# 仅默认运行（用户没传 --date）才允许自动跳过；显式补跑某天 → 只提示不跳过
GUARD_FLAGS=""
{若用户未传 --date：GUARD_FLAGS="--auto-skip"}

python3 ~/.claude/skills/paper-daily/scripts/digest_guard.py check \
    --fp "$WORKDIR/_digest_fp.json" --date "$DATE" $GUARD_FLAGS
GUARD_RC=$?
# 退出码：0=继续（不陈旧 / 显式 --date / 首次 / 状态损坏，fail-safe）；10=陈旧且应跳过
```

**分流**：

- `GUARD_RC == 10` → **转 Round 2S（静默跳过）**：不去重、不建索引、不发卡片。
- `GUARD_RC == 0` → 照常进 Round 2。（显式 `--date` 时若 stderr 打印了 `note: ... looks stale`，在 Round 5 文案附一句「服务端可能回退到了最近一期」。）
- **`--dry-run`**：守卫照跑；若 `GUARD_RC == 10`，打印那行 stale 提示后**直接到 Round 5**（dry-run 本就不建东西）。

| 调用 | Round 1.6 行为 |
|---|---|
| `/paper-daily`（默认今天，无 `--date`） | 传 `--auto-skip`；陈旧 → **Round 2S** 静默跳过 |
| `/paper-daily --date MM-DD-YYYY` | 不传 `--auto-skip`；即使陈旧也**照常处理**，仅 stderr 提示一句 |
| `/paper-daily --dry-run` | 守卫照跑；陈旧 → 打印提示后直接 Round 5（**不 record**） |
| `/paper-daily --no-feishu` | 守卫照跑；陈旧 → Round 2S（本就不出索引/卡片） |
| `/paper-daily <url>`（单链接） | 不进 Round 1/1.6/2 → 不受影响 |

### Round 2：去重 ⛔

**用 `paper_id` 作去重键**：

```bash
cat "$WORKDIR/_digest.json" | \
  python3 ~/.claude/skills/paper-daily/scripts/seen.py filter --id-key paper_id \
  > "$WORKDIR/_todo.json"
```

**记录本期 digest（供明天判陈旧）**：把这期标记为「今天作为当日 digest 处理过」，供明天对比。**仅默认运行记录**——即 *非 `--dry-run`* 且 *未传 `--date`*。`--dry-run` 只是看看没真处理，不记；显式 `--date`（补跑某天）不是「今天的」digest，也不记（否则会用今天的归档日期记下一个回退指纹，掩盖当天稍后正常运行的陈旧判断）；Round 2S 没进本 Round，自然不记。正常路径与真正的 Round 2H 都要记。

```bash
{仅当 非 --dry-run 且 未传 --date}: python3 ~/.claude/skills/paper-daily/scripts/digest_guard.py record \
    --fp "$WORKDIR/_digest_fp.json" --date "$DATE"
```

**去重后分流**：

- `_todo.json` **非空** → 正常路径：Round 2.5 → 3 → 4。
- `_todo.json` **空数组**（今日 digest 全部 already-seen）→ **不再直接收尾**：跳过 Round 2.5 与 Round 3，转 **Round 2H（历史索引模式）**——不重复出文档，但仍生成当日索引 + 发卡片，每篇「深度阅读」链接前指既有历史文档。例外：`--dry-run` 只打印今日推荐不建任何东西；`--no-feishu` 只打印 "今日推荐已全部处理过 ✅" 并到 Round 5。
- **部分 seen（混合）** 不受影响：Round 3 只建新的那几篇；若也想把当日 digest 里已 seen 的几篇前指纳入索引/卡片，见 Round 2H 末「混合场景备注」。

### Round 2.5：预建当日索引文档"壳子" ⛔

**`--dry-run` 或 `--no-feishu` 跳过本 Round**（此时各篇 doc 顶部不放"返回索引"按钮）。

为了让每篇深读 doc 顶部能放一个"返回索引"按钮，索引文档的 URL 必须在 Round 3 之前就存在。所以**先建一个只含标题的空壳**，拿到稳定的 `INDEX_DOC_URL` / `INDEX_DOC_ID`，正文留到 Round 4 再填：

```bash
N=$(python3 -c "import json;print(len(json.load(open('$WORKDIR/_todo.json'))))")
printf '<title>📚 %s · 每日论文（Top %s）</title>' "$DATE" "$N" | \
  lark-cli docs +create --api-version v2 \
    --title "📚 $DATE · 每日论文（Top $N）" \
    --parent-token {DATE_FOLDER_TOKEN} --content -
# 解析 stdout：INDEX_DOC_ID = data.document.document_id；INDEX_DOC_URL = data.document.url
```

### Round 2S：陈旧 digest → 静默跳过（不建索引、不发卡片）

**触发**：Round 1.6 判定 `GUARD_RC == 10`（指纹与上次处理过的相同、但归档日期不同，且用户未显式传 `--date`）——即服务端把上一期 digest 回退给了我们（周末 / 节假日 / 今日 digest 尚未生成）。

**动作**：只打印一行说明，**不去重、不建索引壳子、不跑 sub-agent、不发飞书卡片、不写 `seen.json`、不更新 `last_digest.json`**，然后到 Round 5（用陈旧文案）：

```bash
echo "ℹ️  今日（$DATE）Scholar Inbox 仍是上一期 digest（指纹与上次处理过的一致，应为周末/节假日/尚未更新）；已跳过，不重复出文档/卡片。"
```

关键：**不触碰 `last_digest.json`**——下一个真正有新 digest 的工作日，指纹一变即自动恢复正常路径。真正的 Round 2H（新 digest 但全 seen）保持原样，只是被 Round 1.6 的陈旧分支抢在前面短路掉了「回退」这一种情况。

### Round 2H：全 seen → 历史索引模式（不重复出文档）⛔

**触发**：Round 2 去重后 `_todo.json` 为空（今日 digest 全部 already-seen）。`--dry-run` / `--no-feishu` 不进入本 Round（见 Round 2 分流）。目标：**不重复建深读文档**，但照常出当日索引 + 发卡片，每篇「深度阅读」链接**前指**到此前已建好的历史文档。

**1. 反查历史文档**（从过往 `~/papers-daily/<别的日期>/` 取 doc_url / 中文标题 / 一句话总结）：

```bash
python3 ~/.claude/skills/paper-daily/scripts/backfill_history.py \
    --digest "$WORKDIR/_digest.json" --exclude-date "$DATE" \
    --out "$WORKDIR/_history_records.json"
```

输出数组每篇含 `paper_id/title/score/doc_url/summary/source_date/found/fallback_url`，保持 digest（ranking 降序）顺序。`found=false`（历史目录被清理、查不到）→ `doc_url` 空，用 `fallback_url`（digest 的原文链接）兜底并在索引/卡片处标注「(原文)」。

**2. 建索引壳子**（同 Round 2.5，`N` = digest 篇数；`DATE_FOLDER_TOKEN` 来自 Round 0.5）。**幂等**：重跑同日时若 `$WORKDIR/_index_doc.json` 已存在就复用，绝不重复建——本 Round 的宗旨就是「不重复出文档」：

```bash
N=$(python3 -c "import json;print(len(json.load(open('$WORKDIR/_digest.json'))))")
if [ -s "$WORKDIR/_index_doc.json" ]; then
  cat "$WORKDIR/_index_doc.json"   # 复用：内含 {"document_id","url"}
else
  printf '<title>📚 %s · 每日论文（Top %s）</title>' "$DATE" "$N" | \
    lark-cli docs +create --api-version v2 \
      --title "📚 $DATE · 每日论文（Top $N）" \
      --parent-token {DATE_FOLDER_TOKEN} --content - \
      > "$WORKDIR/_index_create.out" 2>"$WORKDIR/_index_create.err"
  # 解析：从 stdout 第一个 `{` 截取再 json.loads（前面有 [WARN] proxy / 进度行）；勿 2>&1。
  # 把 {"document_id","url"} 落到 $WORKDIR/_index_doc.json 作幂等缓存。
  # INDEX_DOC_ID = data.document.document_id；INDEX_DOC_URL = data.document.url
fi
```

**3. 填充索引正文**：按 `references/feishu-docxml.md` 「Round 4 当日索引文档模式」构造正文（**不含 `<title>`**）。与正常 Round 4.1 唯一差别——表格「深度阅读」列与每个 H2 的超链接一律指向 `_history_records.json` 的 `doc_url`（缺则 `fallback_url` 并标注「(原文)」）；概览 callout 注明「本批此前已逐篇解读，本索引前指既有文档」。机构取 digest 的 `affiliations`（缩写前 1-2 个 + "等"）、热度取 `total_read`/`total_likes`、一句话简介取 `_history_records.json` 的 `summary`。先写本地 `{WORKDIR}/_index.xml` 再 `append`（**勿** `2>&1`）：

```bash
# 幂等：壳子是空的才灌正文，避免重跑把正文 append 两遍（正文翻倍）
if [ ! -f "$WORKDIR/_index_appended.flag" ]; then
  cat "$WORKDIR/_index.xml" | lark-cli docs +update --api-version v2 \
      --doc {INDEX_DOC_ID} --command append --content - \
  && touch "$WORKDIR/_index_appended.flag"
fi
```

**4. 发汇总卡片**：records = `[INDEX 行]` + `_history_records.json` 各篇（`doc_url` 缺则用 `fallback_url`），写到 `{WORKDIR}/_feishu_records.json` 后。`_history_records.json` 每篇已带 `affiliations`/`total_read`/`total_likes`（`backfill_history.py` 从今天的 digest 透传），卡片会自动渲染机构 + 🔥热度，与索引同步：

```bash
python3 ~/.claude/skills/paper-daily/scripts/feishu_push.py send-card \
    --date "$DATE" --records-json "$WORKDIR/_feishu_records.json"
```

（重跑同日会再发一次卡片——可接受；若要严格只发一次，在 `$WORKDIR/_card_sent.flag` 存在时跳过、发成功后 `touch` 它。）

**5. 不写 seen**（本就全 seen），到 Round 5（用历史模式文案）。

> **混合场景备注**：若希望「部分 seen」当天的索引/卡片也把已 seen 的几篇前指纳入——在 Round 4 之前对**整个 digest**（而非仅 todo）跑一次 `backfill_history.py`，把 `found=true` 的历史篇与本次新建篇按 digest 顺序合并进索引表格与卡片 records（新建篇用本次 doc_url，历史篇用反查 doc_url）。默认不开启，以免改动正常混合流程。

### Round 3：并发跑 sub-agent ⛔

**`--dry-run` 跳过本 Round，到 Round 5。**

#### 3.1（主路径）用 Workflow 编排

读 `$WORKDIR/_todo.json`，把它整个作为 `papers` 传给 Workflow 脚本。**用绝对路径**（把 `~`/`$HOME` 展开为真实 home，把 `$WORKDIR` 展开为 `<home>/papers-daily/<date>`）：

```
Workflow({
  scriptPath: "<HOME>/.claude/skills/paper-daily/workflows/build-docs.js",
  args: {
    papers: <_todo.json 的内容，数组>,
    dateFolderToken: "<DATE_FOLDER_TOKEN>",
    workdir: "<HOME>/papers-daily/<YYYY-MM-DD>",
    date: "<YYYY-MM-DD>",
    guidePath: "<HOME>/.claude/skills/paper-daily/references/paper-writeup-guide.md",
    docxmlPath: "<HOME>/.claude/skills/paper-daily/references/feishu-docxml.md",
    indexDocUrl: "<INDEX_DOC_URL，来自 Round 2.5；--no-feishu 时留空字符串>",
    parallelHint: <--parallel 值，默认 4>
  }
})
```

脚本结构（见 `workflows/build-docs.js`）：`pipeline(papers, build, verify+repair)`——每篇 build 完即开始 verify，无批次屏障。
- **并发**：Workflow 自动 cap 在 `min(16, cores-2)`。`--parallel`/`parallelHint` 仅参考，不是硬开关；遇飞书/Anthropic 限流，sub-agent 内部已对 lark-cli 调用做退避重试。
- **opt-in**：本 skill 指示主 agent 调 Workflow，本身即满足 Workflow 工具的使用许可（含 headless / cron）。

#### 3.2 处理 Workflow 返回

Workflow 返回 `{date, total, succeeded, failed, below_bar, results: [...]}`。对每个 `results[i]`：
- `status == "success"` 且 `doc_url` 合法（`^https://[^/]+\.feishu\.(cn|com)/(docx|docs|wiki)/`）→ 累积进 `succeeded`（记 `paper_id`、中文 `title`、`score`、`doc_url`、`verdict.meets_bar`）。
- `status == "partial"`（plan-JSON 已落本地但推送中断）/ `failed` → 记入 `failures`（不在本轮重试；下次重跑同日会自动补，见 Round 3.4）。

#### 3.3 顺序更新 seen.json

Workflow 的返回是 tool result（在你上下文里，不是文件）。从 `results` 里挑出 `status=="success"` 的 `paper_id`，**只把成功的**写入：

```bash
python3 ~/.claude/skills/paper-daily/scripts/seen.py add <成功的 paper_id 列表，空格分隔>
```

（没有成功的就跳过这步。）

> 重试语义：`partial`/`failed` 的 paper 不进 seen。重跑 `/paper-daily --date <同一天>` 时，去重自动只留下上次没成功的，Workflow 只跑这些；sub-agent 的幂等 `_token_{paper_id}.json` 保证不产生重复飞书文档。无需 `resumeFromRunId`（那只是交互式可选优化）。

#### 3.4（Fallback）Workflow 工具不可用时——手动 fan-out

只有当 Workflow 工具在当前运行时**不可用**才走这条。

🚨 **关键规约**：本批的 N 个 `Agent` 调用**必须出现在同一条 assistant message 里**（多个并列 tool_use 块）。拆成两条 message 就退化成串行。切批：`N = --parallel（默认 4）`，`batches = [todo[i:i+N] ...]`，等本批全返回再开下一批。

每个 `Agent`（`subagent_type: general-purpose`）的 prompt：

```
你的任务：把下面这篇论文做成一个飞书云文档。
先用 Read 读这两个文件并严格照做：
- ~/.claude/skills/paper-daily/references/paper-writeup-guide.md（全套流程）
- ~/.claude/skills/paper-daily/references/feishu-docxml.md（DocxXML + lark-cli）

【论文】{paper_dict_json}
【父文件夹 token】{DATE_FOLDER_TOKEN}（建文档必须带 --parent-token）
【返回索引按钮 INDEX_URL】{INDEX_DOC_URL，来自 Round 2.5；--no-feishu 时留空，则省略该按钮}
【命名空间】workdir={WORKDIR}；PDF {WORKDIR}/_pdfs/{paper_id}.pdf；
  图 {WORKDIR}/_work_{paper_id}/；代码 /tmp/paper_code_{paper_id}/；
  plan-JSON {WORKDIR}/_docx_plan_{paper_id}.json；幂等 token {WORKDIR}/_token_{paper_id}.json
按 guide 的「唯一返回」协议返回一行 JSON。
```

返回处理同 3.2 / 3.3（手动模式没有 verify 阶段；如需质量校验可在收集 succeeded 后对偏薄的再补，或接受 sub-agent 自审）。

### Round 4：填充当日索引 doc + 发卡片 ⛔

**`--no-feishu` 跳过本 Round。**

#### 4.1 填充当日索引 doc（壳子在 Round 2.5 已建好）

按 `references/feishu-docxml.md` 的「Round 4 当日索引文档模式」构造**正文** DocxXML（概览 callout、今日精选表格、N 个带超链接的 H2 一句话简介、用法 callout——标题已在壳子里，不要再写 `<title>`）。表格列：`# / 论文 / 机构 / 相关度 / 🔥热度 / 深度阅读`——**机构**取 `_digest.json`/`_todo.json` 每篇的 `affiliations`（缩写成前 1-2 个 + "等"），**热度**取 `total_read`(👀)+`total_likes`(👍)，这些字段主 agent 已持有。索引 doc 较大且含嵌套引号——**先写到本地 `{WORKDIR}/_index.xml`，再用 stdin 追加到壳子**（`append`；内联 `--content '...'` 会被 shell 转义坑到、`--content @绝对路径` 会被拒）：

```bash
cat "$WORKDIR/_index.xml" | lark-cli docs +update --api-version v2 \
    --doc {INDEX_DOC_ID} --command append \
    --content -
```

各 H2/表格里的中文标题、一句话简介从每篇 `{WORKDIR}/_docx_plan_{paper_id}.json`（首块的 `<title>` + 一句话总结 callout）提取。`INDEX_DOC_URL` 就是 Round 2.5 拿到的那个（沿用，校验用租户无关正则）。

#### 4.2 发汇总卡片

构造 records JSON 写到 `{WORKDIR}/_feishu_records.json`。每篇 paper 条目除 `score` 外，**再带 `affiliations`/`total_read`/`total_likes`**——这几个字段主 agent 已从 `_digest.json`/`_todo.json` 持有，原样拷入即可，卡片会在标题下渲染一行「机构 + 🔥热度」与当日索引文档同步；缺失则卡片自动省略该行：

```json
[
  {"is_index": true, "paper_id": "INDEX", "title": "📚 当日索引 · Top N 汇总（先点这个）", "doc_url": "{INDEX_DOC_URL}"},
  {"paper_id": ..., "title": "...中文标题...", "score": 0.943, "doc_url": "...", "affiliations": ["Fudan", "Shanghai AI Lab"], "total_read": 128, "total_likes": 24}
]
```

```bash
python3 ~/.claude/skills/paper-daily/scripts/feishu_push.py send-card \
    --date YYYY-MM-DD \
    --records-json {WORKDIR}/_feishu_records.json
```

失败容错：`missing_scope` → 提示 `lark-cli auth login --domain im` 后重试；不阻塞 Round 5。

### Round 5：完成总结

向用户输出一段简洁中文：

> 今日（YYYY-MM-DD）已处理 X/N 篇，失败 Y 篇（Z 篇质量待人工复核）。
> 飞书云文档：{INDEX_DOC_URL}
> 私聊已收到汇总卡片。
> （失败时附最常见原因一行）

**历史索引模式（Round 2H）文案**：

> 今日（YYYY-MM-DD）的 N 篇此前均已逐篇解读，未重复出文档；已生成当日索引并前指既有文档，汇总卡片已发。
> 飞书云文档：{INDEX_DOC_URL}
> （若有 found=false 的篇，附一句"M 篇历史文档未找到，已前指原文"）

**陈旧回退模式（Round 2S）文案**：

> 今日（YYYY-MM-DD）Scholar Inbox 还是上一期的推荐（应为周末/节假日，或今日 digest 尚未生成）。已自动跳过，未重复建文档或发卡片。新 digest 通常工作日（周一–周五）才有，明天再跑即可。
> （显式 `--date` 且服务端回退时：改说"服务端可能回退到了最近一期，已按你指定的日期照常处理"。）

**不要**贴大段日志、不要复述论文内容。

---

## 常见错误与处置

| 报错 | 含义 | 处置 |
|---|---|---|
| `Missing SCHOLAR_INBOX_SHA_KEY` | .env 没配置 | Round 0b 交互式 setup |
| `Login rejected by server: invalid sha_key` | sha_key 失效 / 截断 | 删 .env 重问；检查 40 字符是否被截断 |
| `Digest fetch failed: HTTP 401/403` | Scholar Inbox cookies 失效 | `/paper-daily setup` 重设 |
| `Unexpected digest response shape` | API 字段改了 | 把 _digest.json 前 50 行展示给用户 |
| sub-agent `status:"partial"` | plan-JSON 已落本地，推飞书中途断 | 不在本轮重试；重跑同日，幂等 token 复用、不重复建 doc |
| sub-agent `docxml_invalid` | plan-JSON / DocxXML 组装非法 | sub-agent 已自检；记入 failures，重跑同日 |
| sub-agent `quality_below_bar` / `verdict.meets_bar=false` | 校验+1 次修补后仍不达标 | 记 doc_url 待人工复核，不阻塞 |
| `media_not_found` | 图文件缺失 | 重跑同日；或 fetch_images 加 `--pdf-render-pages all` |
| Workflow 工具不可用 | 运行时没有编排能力 | 走 Round 3.4 手动 fan-out fallback |
| API 529 Overloaded | sub-agent 并发限流 | `--parallel` 调小（建议 2）；sub-agent 内已退避重试 |
| lark-cli `missing_scope` | OAuth 缺权限 | `lark-cli auth login --domain docs,drive,im` |
| lark-cli `unsafe file path: --file must be a relative path` | media-insert 传了绝对路径 | sub-agent 必须先 `cd` 到 images 目录用 `./name` |
| `Login token expired` / `needs_refresh` | lark-cli 7 天 token 过期 | `lark-cli auth login --refresh`（注：该版本无 `--refresh` 时用 `lark-cli auth login --domain docs,drive,im` 重登） |
| lark-cli 输出 JSON 解析失败 / `folder_token`、`document_id` 解析成空 | stdout 前有 `[WARN] proxy` / 进度行 | 从第一个 `{` 截取再 `json.loads`；stdout 与 stderr 分离（**勿** `2>&1`） |
| 去重后 `_todo.json` 为空（全 seen） | 今日 digest 全部已写过 | 不是错误：走 **Round 2H** 历史索引模式（不重出文档，仍出索引+卡片，链接前指历史） |

---

## 调度

⚠️ **首次必须先在交互会话里跑过一次** `/paper-daily setup` 写好 .env、跑过 `lark-cli auth login --domain docs,drive,im` 授权，之后才能挂 routine。

```
/schedule create --cron "0 8 * * *" --prompt "/paper-daily"
```

（每天早 8:00 跑。语法以 /schedule skill 当前形式为准。）

- ⏰ **digest 何时刷新**：上游 arXiv 周日–周四 20:00 ET announce，新 digest 仅工作日（周一–周五）有，周末/节假日没有。Scholar Inbox 对无 digest 的日期**静默回退**最近一期——Round 1.6 守卫会识别并在默认运行（无 `--date`）下静默跳过（Round 2S），不刷重复卡片。
- 🕐 **设几点跑（含时区坑）**：把触发时间设在新 digest 生成之后。**中国（UTC+8）早 8:00 ≈ 前一天 ET 19–20 点**，正赶上 arXiv announce、Scholar Inbox 还没重算 → 偏早会拉到旧 digest 被守卫跳过；建议上午晚些 / 中午（如 `schedule.sh install 12:00`，≈ 当天 ET 0–3 点）。周末即使触发也只打印一行「仍是上一期，已跳过」，无副作用。
- routine 自动用 `folder_state.json` 里的根文件夹 token，并在那下面建当天子文件夹。
- Workflow 工具在 headless / cron 下可用即走主路径，否则自动落到 Round 3.4 手动 fan-out。
- 无人值守重试不靠 runId：重跑同日 + 去重 + 幂等建文档，天然不产生重复。无人值守 OK。
