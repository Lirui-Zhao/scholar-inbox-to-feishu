# scholar-inbox-to-feishu

> A [Claude Code](https://claude.com/claude-code) skill that turns your daily **[Scholar Inbox](https://www.scholar-inbox.com/)** recommendations into rich **Feishu / Lark** cloud documents — every day, automatically.
>
> 一个 Claude Code skill：每天把 **Scholar Inbox** 个性化推荐的 Top‑N 论文，逐篇做成**飞书云文档**（中文 storytelling 深度解读 + 图文交错 + 原文公式/表格/代码），并发生成、自带质量校验，最后由机器人把汇总卡片推送到你的飞书私聊。可挂成每天定点运行的定时任务。

**Pipeline:** `Scholar Inbox digest → dedup → N parallel sub‑agents (read PDF · find code · grab figures · write · push) → Feishu docs + daily index + DM card`

The skill is named `paper-daily`; this repo wraps it with setup docs, configuration, and a scheduler.

---

## Table of Contents

- [What it produces / 产出](#what-it-produces--产出)
- [How it works / 工作原理](#how-it-works--工作原理)
- [Prerequisites / 前置条件](#prerequisites--前置条件)
- [Install / 安装](#install--安装)
- [Update / 更新](#update--更新)
- [Configuration / 配置项](#configuration--配置项)
- [Usage / 使用](#usage--使用)
- [Scheduling / 定时任务](#scheduling--定时任务)
- [Security / 安全](#security--安全)
- [Acknowledgments / 致谢](#acknowledgments--致谢)
- [License](#license)

---

## What it produces / 产出

每天在你的飞书"我的空间 / `paper-daily` / `YYYY-MM-DD`/"下生成：

- **每篇一个深度解读文档**，硬指标（自动校验，不达标会触发一次修补）：
  - 中文 storytelling 行文 ≥ 3000 字、段落 ≥ 15
  - 真实配图 ≥ 3 张（**图文交错**，不是堆在末尾）
  - 引用论文原文公式 / Figure / Table 编号 ≥ 3 处（原生 LaTeX 渲染）
  - 有公开代码时嵌 ≥ 2 段代码并标 `文件:行号`
  - 至少 2 处局限（作者自述 + 独立判断）；无 AI 套话
  - **顶部横幅**：一键「返回今日论文索引」+「👍 去 Scholar Inbox 点赞」（点赞回流让推荐算法学你的口味）
  - meta 里显示**作者机构**与**社区热度**（👀 已读数 · 👍 点赞数，来自 Scholar Inbox）
- **一份当日索引文档**：Top‑N 表格（含机构、相关度、🔥热度）+ 每篇一句话简介 + 跳转链接。
- **一张飞书汇总卡片**推送到你的私聊（或指定群）。

> 输出语言是**中文**（这是本工具的产品定位：给中文研究者的高质量论文速读）。

## How it works / 工作原理

```
Scholar Inbox digest  (Top-N，按个性化相关度排序)
        │   scripts/scholar_inbox.py
        ▼
   去重 scripts/seen.py ──► _todo.json
        │
        ▼   workflows/build-docs.js   （Workflow 并发编排 N 个 sub-agent）
  ┌─ 每篇论文 ─────────────────────────────────────────────┐
  │ 下载 PDF → 找 GitHub 代码 → 多来源抓图(fetch_images.py) │
  │ → 写中文 storytelling DocxXML → 落本地 plan-JSON        │
  │ → 回放推进飞书文档 → 质量校验（不达标做一次有界修补）   │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  当日索引文档  +  飞书 DM 汇总卡片
```

主流程（`paper-daily/SKILL.md`）分 Round 0→5：环境/认证预检 → 飞书文件夹就绪 → 拉 digest → 去重 → **Workflow 并发建文档 + 校验** → 当日索引 + 卡片 → 总结。每篇先把内容组装成本地 `plan-JSON` 再回放推送，所以推送失败不会丢掉分析、可重试。方法论与 DocxXML 语法分别在 `references/paper-writeup-guide.md`、`references/feishu-docxml.md`。

> **当天 digest 全部已读过**（去重后无新论文）时不重复出文档，但仍会生成当日索引 + 发汇总卡片，每篇「深度阅读」链接**前指**到此前已建好的历史文档（Round 2H，由 `scripts/backfill_history.py` 从过往工作目录反查 doc_url / 中文标题 / 一句话简介）。

## Prerequisites / 前置条件

| 需要 | 说明 |
|---|---|
| **Claude Code** | 本质是 Claude Code skill（`/paper-daily`），并用其 Workflow 工具做并发编排 |
| **Node.js** (≥ 18) | 用来装飞书官方 CLI `@larksuite/cli` |
| **Python 3** | 脚本纯 stdlib；`Pillow` 可选（量图尺寸/去重，缺了也能跑） |
| **poppler-utils** | `pdfimages` / `pdftoppm`，抽取/渲染论文配图（Debian/Ubuntu: `apt-get install -y poppler-utils`；macOS: `brew install poppler`） |
| **Scholar Inbox 账号** | 提供每日个性化论文 digest |
| **飞书 / Lark 账号** | 文档写入个人空间、卡片推送私聊（需 docs/drive/im 权限） |

## Install / 安装

### 1. 克隆仓库，把 skill 装到 Claude Code

Claude Code 从 `~/.claude/skills/<name>` 发现 skill，所以要让它落在 `~/.claude/skills/paper-daily`——**必须是这个确切路径**（脚本与默认配置目录都假设它）。按你的角色二选一：

**A. 拷贝安装（推荐给使用者）**——装成一份独立快照，和仓库目录解耦：

```bash
git clone https://github.com/Lirui-Zhao/scholar-inbox-to-feishu.git
cd scholar-inbox-to-feishu
mkdir -p ~/.claude/skills
cp -r paper-daily ~/.claude/skills/paper-daily
```

**B. 软链接安装（推荐给改 skill 源码 / 跟进开发的人）**——skill 直接指向仓库，改一处即时生效，更新只需 `git pull`：

```bash
git clone https://github.com/Lirui-Zhao/scholar-inbox-to-feishu.git
cd scholar-inbox-to-feishu
mkdir -p ~/.claude/skills
ln -s "$PWD/paper-daily" ~/.claude/skills/paper-daily
```

> 两种装法日后如何拿仓库更新，见 [Update / 更新](#update--更新)。拷贝安装的同学建议留着这份 clone（更新更省事），删了也行——需要时重新 clone 即可。

### 2. 安装并授权飞书 CLI（已对 lark-cli v1.0.43 实测）

```bash
npm install -g @larksuite/cli                 # 1. 装官方 CLI
lark-cli config init --new                    # 2. 初始化 app（阻塞并输出验证 URL → 浏览器打开授权）
lark-cli auth login --domain docs,drive,im    # 3. 用户授权（device flow，再给一个验证 URL → 浏览器确认）
lark-cli auth status                          # 4. 校验：user.openId 非空，scope 含 docx:document / drive:drive / im:message.send_as_user
```

- **Headless / 无浏览器**：`lark-cli auth login --domain docs,drive,im --no-wait --json` 拿到 `verification_url`，在另一台设备打开确认后，再 `lark-cli auth login --device-code <device_code>` 完成。
- 用 `--domain docs,drive,im` 显式申请所需 scope（`--recommend` 可能漏掉 `im:message.send_as_user`）。
- Token 默认约 7 天过期，过期 / `needs_refresh` → `lark-cli auth login --refresh`（部分版本如 v1.0.43 无该 flag，改用 `lark-cli auth login --domain docs,drive,im` 重新授权）。
- （可选）`npx skills add larksuite/cli -g -y` 装官方 agent skill 增强提示——**非必需**，本 skill 已自带 `references/`。

### 3. 配置 Scholar Inbox 密钥

去哪拿密钥：你的 Scholar Inbox 登录邮件里的 **magic‑link**，形如
`https://www.scholar-inbox.com/login?sha_key=<40位十六进制>`（登录后浏览器地址栏也能看到）。

两种方式任选：

- **推荐**：首次运行 `/paper-daily`（或 `/paper-daily setup`），它会交互式问你这条 URL，并写入 `~/.claude/skills/paper-daily/config/.env`（自动 `chmod 600`）。
- **手动**：从模板建 `.env`：
  ```bash
  cp ~/.claude/skills/paper-daily/config/.env.example ~/.claude/skills/paper-daily/config/.env
  # 编辑，填入 SCHOLAR_INBOX_SHA_KEY=...，然后
  chmod 600 ~/.claude/skills/paper-daily/config/.env
  ```

## Update / 更新

本仓库发布新版 skill（修 bug / 加能力）后，怎么同步到你本机，取决于你当初用的装法。无论哪种，**你的密钥 `config/.env` 都不该被覆盖**——下面的命令都会保住它。

**装法 B（软链接）**——最省事，skill 本就指向仓库，`git pull` 即生效：

```bash
cd scholar-inbox-to-feishu     # 进到你当初 clone 的目录
git pull
```

`config/.env` 是 gitignore 的本地文件，`git pull` 不会碰它，更新后立即生效。

**装法 A（拷贝）**——先拉新版，再把代码覆盖到 skill 目录，唯独跳过你的密钥：

```bash
cd scholar-inbox-to-feishu     # 没留 clone 就先重新 git clone 再进来
git pull
# rsync 覆盖代码、清掉已删除的旧文件，但保留你的 .env
rsync -a --delete --exclude 'config/.env' paper-daily/ ~/.claude/skills/paper-daily/
```

> 更新只动 skill 代码：去重状态、每日工作目录默认都在仓库外（见 [Security / 安全](#security--安全)），不受影响。更新后想确认生效，跑一次 `/paper-daily --dry-run` 看能否正常拉到 digest 即可。

## Configuration / 配置项

密钥与接收者写在 `config/.env`（脚本会读）；运行路径 / 行为通过**环境变量**覆盖（脚本读 `os.environ`、SKILL 用 `${VAR:-默认}`）。全部带默认值：

| 变量 | 默认 | 作用 | 设在哪 |
|---|---|---|---|
| `SCHOLAR_INBOX_SHA_KEY` | （必填） | Scholar Inbox 鉴权 token | `.env` |
| `SCHOLAR_INBOX_LOGIN_URL` | — | 备选：含 `sha_key` 的 magic‑link（两者都给时 sha_key 优先） | `.env` |
| `FEISHU_RECEIVER` | 本人 open_id | 汇总卡片接收者：`ou_…`(用户私聊) 或 `oc_…`(群聊) | `.env` 或环境变量 |
| `PAPER_DAILY_STATE_DIR` | `~/.local/share/paper-daily` | 去重状态 / cookies / 飞书文件夹 token 缓存 | 环境变量 |
| `PAPER_DAILY_WORKDIR_ROOT` | `~/papers-daily` | 每日工作目录（PDF / 抓图 / plan‑JSON） | 环境变量 |
| `PAPER_DAILY_CONFIG_DIR` | `~/.claude/skills/paper-daily/config` | `.env` 所在目录 | 环境变量 |
| `FEISHU_ROOT_FOLDER` | `paper-daily` | 飞书云端根文件夹名 | 环境变量 |
| `PAPER_DAILY_LIMIT` | `8` | 每天处理篇数（CLI `--limit` 优先） | 环境变量 |
| `PAPER_DAILY_PARALLEL` | `4` | 并发提示（实际并发由 Workflow 自动上限 `min(16, 核数-2)`） | 环境变量 |

例：换工作目录与接收群聊 ——
```bash
export PAPER_DAILY_WORKDIR_ROOT=/data/papers
export FEISHU_RECEIVER=oc_xxxxxxxxxxxxxxxx
```

## Usage / 使用

在 Claude Code 里：

```
/paper-daily                    # 今日 Top 8，自动推飞书
/paper-daily --limit 3          # 只跑 Top 3（调试）
/paper-daily --date 05-27-2026  # 补跑某天（MM-DD-YYYY，Scholar Inbox 日期格式）
/paper-daily --parallel 2       # 并发提示（实际由 Workflow 自动 cap）
/paper-daily --no-feishu        # 跳过当日索引 doc + 卡片（每篇 doc 仍建）
/paper-daily --dry-run          # 只拉 digest 看今天推什么，不建文档
/paper-daily setup              # 重新配置 Scholar Inbox 密钥
/paper-daily https://arxiv.org/abs/2605.27817   # 单链接模式：只解析这一篇并推给你
```

**单链接模式 / single-link mode**：位置参数给一个 arxiv / 项目页 / PDF 链接，就只解析那一篇、生成一篇飞书 doc 推给你（不走 Scholar Inbox digest，归档到 `paper-daily/adhoc/`）。适合你在别处看到一篇想读的论文时随手丢进来。

> ⚠️ **已知限制 / known limitation**：对**超长（30+ 页）且全是矢量图**的论文（`pdfimages` 抽不到位图、需逐页渲染），单篇构建可能耗时很久甚至不收敛。这类论文建议走每日 digest 流程，或先手动准备好配图。常规长度（≤ ~20 页）的论文不受影响。
> For unusually long (30+ pages) papers whose figures are all vector graphics, single-paper build can be very slow or may not converge; prefer the daily digest flow for those.

> 首次请在**交互式会话**里先跑一次（完成 Scholar Inbox setup + 飞书授权），之后再挂定时任务。

## Scheduling / 定时任务

让它每天定点本地自动运行。提供一个 helper（基于 cron）：

```bash
# 启动：每天定点跑 /paper-daily（时间怎么挑、为什么别太早 → 见下「更新时间」）
bash ~/.claude/skills/paper-daily/scripts/schedule.sh install 12:00

# 取消
bash ~/.claude/skills/paper-daily/scripts/schedule.sh uninstall

# 查看当前任务
bash ~/.claude/skills/paper-daily/scripts/schedule.sh status
```

它会写一条带 `# paper-daily-cron` 标记的 crontab，内容是 `claude -p "/paper-daily"`（运行前先 best‑effort `lark-cli auth login --refresh`），日志写到 `$PAPER_DAILY_STATE_DIR/cron.log`。

- **前置**：需要系统有 cron。没有就先装：`sudo apt-get install -y cron && sudo service cron start`。
- **Claude 原生备选**：也可用 `/schedule` skill（`/schedule create --cron "0 8 * * *" --prompt "/paper-daily"`，配合其 list/delete）。注意 routine 可能在云端执行，若你要在**本地**无人值守跑（依赖本机的 lark-cli 授权），优先用上面的 cron 方式。
- ⚠️ **Token 过期**：飞书 token 约 7 天过期；cron 行已带 `--refresh` 做 best‑effort 续期，但完全过期仍需交互式重新 `lark-cli auth login`。建议定期人工跑一次确认授权有效。

### Update schedule / digest 更新时间

Scholar Inbox 的 digest 来自 **arXiv**，而 arXiv 的论文 announce 窗口是**周日至周四 20:00 美东（ET）**，所以**新 digest 只在工作日（周一–周五）产生，周六、周日没有新 digest**（节假日同理）。Scholar Inbox 在你请求一个没有 digest 的日期时会**静默回退**返回最近一期（不报错）。

本工具自带「陈旧 digest 守卫」：默认运行（不带 `--date`）时若发现服务端回退（拿到的论文集合与上次处理过的完全一致、但日期不同），会**自动静默跳过**——不重复建文档、不发卡片（周末、节假日、或当天 digest 尚未生成时都适用）。所以**周末挂着定时任务也不会刷屏**。

**建议的运行时间（含时区坑）**：把 cron 设在**新 digest 确定已生成之后**。arXiv 20:00 ET announce 后 Scholar Inbox 才会重算当天的 digest。注意时区换算：

- arXiv 20:00 ET ≈ **中国（UTC+8）次日早上 08:00**——也就是说，**中国早上 8 点正好赶上 arXiv 刚 announce、Scholar Inbox 还没重算**，这时候跑会拉到前一天的旧 digest（然后被守卫跳过）。
- 推荐设在**中国时区上午晚些 / 中午**（如 `schedule.sh install 12:00`，≈ 当天 ET 0–3 点），这时当天新 digest 已稳定可用。

周末/节假日即使触发也只会打印一行「仍是上一期，已跳过」，无副作用；所以是否限定只在工作日跑（cron `1-5`）随你，不是必须。

## Security / 安全

- **永远不要提交 `config/.env`**（含你的 Scholar Inbox sha_key）。仓库 `.gitignore` 已忽略 `**/config/.env` 与 `.env`。
- 运行态数据（cookies、seen 状态、飞书 token 缓存、每日工作目录）默认在仓库之外（`~/.local/share/paper-daily`、`~/papers-daily`），不会进版本库。
- 提交前可自查：`git ls-files | grep -i '\.env$'` 应为空。

## Acknowledgments / 致谢

This project was informed by the summary / approach in [zsyggg/paper-craft-skills](https://github.com/zsyggg/paper-craft-skills) — thanks!

本项目在整理思路时参考了 [zsyggg/paper-craft-skills](https://github.com/zsyggg/paper-craft-skills) 的总结，特此致谢。

## License

[**CC BY-NC 4.0**](./LICENSE) © 2026 Lirui Zhao — **非商用 / non-commercial use only**.

You may use, modify, and share this work **for non-commercial purposes**, with attribution. **Commercial use is not permitted.**
可自由使用、修改、分享，但**不得用于商业目的**，且需署名（Attribution-NonCommercial 4.0 International）。
