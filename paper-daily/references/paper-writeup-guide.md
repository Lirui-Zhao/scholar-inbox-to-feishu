# Paper Write-up Guide —— 一篇论文 → 一个飞书云文档

> 这是 **paper-daily** 子任务的唯一方法论真相源。每个处理单篇论文的 sub-agent 都读这份文件，严格照做。
> DocxXML 语法、lark-cli 命令细节在 `references/feishu-docxml.md`，本文不再重复。

你的任务：把**一篇**论文做成**一个**飞书云文档。流程是
**读 PDF → 搜代码 → 抓图 → 内部分析 → storytelling 风格写作 → 组装成本地 plan-JSON → 回放推进飞书（图文交错）→ 自审 → 返回一行 JSON。**

## 必读文件

- **必读**：`~/.claude/skills/paper-daily/references/feishu-docxml.md` —— DocxXML 语法 + lark-cli 食谱（核心；已对 lark-cli v1.0.43 实测验证：`docs +create/+update/+media-insert/+fetch`、`drive +create-folder`、`im +messages-send` 全部可用）。

不确定某个 flag 时，直接 `lark-cli docs +create --help`（注意建文档/更新要带 `--api-version v2`；`+media-insert` 反而**不要**带 `--api-version`）。

- **可选参考**（仅当本机装了 lark-doc v2 agent skill 时；没装也完全不影响，上面那份够用）：
  `~/.claude/skills/lark-doc/SKILL.md`、`references/lark-doc-create.md`、`lark-doc-update.md`、`lark-doc-media-insert.md`。

---

## Phase 1：拿到论文素材（不要跳）

### 1.1 读 PDF 全文（**必须本地化**）

⚠️ **关键规约**：不管来源是什么，**都必须**先把 PDF 落到本地 `{workdir}/_pdfs/{paper_id}.pdf`，再用 Read 工具读。**禁止**只读 arxiv html / 网页直链做分析——会导致抓图/插图阶段没本地素材、不可复现、链接失效就断。

PDF 下载（按论文字段分支）：

| paper 字段 | 下载命令 |
|---|---|
| `arxiv_id` 非空 | `curl -fL --max-time 90 -o {workdir}/_pdfs/{paper_id}.pdf 'https://arxiv.org/pdf/{arxiv_id}'` |
| 否则 `url` 以 `.pdf` 结尾 | `curl -fL --max-time 90 -o {workdir}/_pdfs/{paper_id}.pdf '<paper.url>'` |
| 其他 | 返回 `{"status":"failed","stage":"unsupported_source", ...}` |

下载后用 Read **分多次读完整篇**（每次 5–6 页），不要只看 abstract。12–20 页都要读到，包括 References 段（找代码链接）。

可选辅助：arxiv 有 html 版（`https://arxiv.org/html/<arxiv_id>`）时可**同时**读，用于公式 / Figure 编号交叉核对。但**主分析必须基于本地 PDF**。

### 1.2 搜 GitHub 代码（关键步骤，不能跳）

1. **先翻 PDF**：作者常把 github 链接放在页脚 / Introduction 末 / Abstract 末 / Conclusion / Footnote。
2. **没找到则搜 GitHub**：用标题核心名词 + 主作者名（`gh search repos` 或 WebFetch GitHub 搜索页）。
3. **找到了**：
   - `git clone --depth 1 <repo> /tmp/paper_code_{paper_id}/`
   - 读 README + 核心源码（model.py / main.py / train.py 这类）
   - 找 **≥ 2 处** "论文方法 ↔ 代码具体函数/类" 对应
   - 在方法详解段嵌 ≥ 2 段代码（每段 ≤ 30 行），标 `文件路径:行号`
   - 记下 clone 是否成功（成功 → Phase 1.3 才加 `--repo`）
4. **找不到**：meta-info 段写"代码：未公开"，正文里也说明"本文未提供公开代码"。

### 1.3 抓配图（**必须本地化** + **多来源**）

⚠️ **关键规约**：所有插图**必须**走"本地素材 → fetch_images.py 抽出 → `+media-insert --file ./local.png`"。**禁止**在 DocxXML 里用 `<img href="https://...">` 网络 URL——会绕过过滤、链接失效断图、无法在 manifest 里复核。

pdfimages 抽不到矢量架构图（matplotlib/TikZ），所以**默认多来源**，按可用性条件传参：

```bash
cd {workdir}
python3 ~/.claude/skills/paper-daily/scripts/fetch_images.py \
    --out _work_{paper_id} \
    --pdf _pdfs/{paper_id}.pdf \
    {arxiv_id 非空时：--arxiv {arxiv_id}} \
    {clone 成功时：--repo /tmp/paper_code_{paper_id}} \
    {有 project_url 时：--page {project_url}}
```

- arxiv html 给的是干净栅格图；repo 的 `assets/` 常含架构总图；三源 md5 自动去重。
- 抽出的图很少（<3）或缺关键架构图（被 pdfimages 跳过的矢量图）→ 加 `--pdf-render-pages "1,3,5"`（按论文图所在页）或 `--pdf-render-pages all` 整页渲染兜底。

**挑 3–5 张关键图**（**必读** `_work_{paper_id}/images/manifest.json` 后挑）：
- ✅ 优先：方法/架构总图 + 最有说服力的结果图/表 + 帮助理解的流程/定性图
- ❌ 剔除：作者头像 / 机构 logo / 装饰图 / 重复图

### 1.4 内部深度分析（不展示给读者，是写作前的准备）

自问 5 问：
1. **核心创新**：做了什么别人没做的？（1–3 个，每个一句话）
2. **方法细节**：输入 → 处理 → 输出 → 为什么更好（每个创新点画清这条线）
3. **关键实验**：哪个结果最有说服力？为什么？
4. **论文弱点**：作者自述 + 你的独立判断
5. **代码对应**：每个 component 对应哪个文件/函数（如有代码）

---

## Phase 2：Storytelling 风格写作

### 硬指标（缺一不可）

| 项 | 阈值 |
|---|---|
| 中文字数 | ≥ 3000 |
| `<p>` 段落 | ≥ 15 |
| 引用论文原文（公式 / Figure / Table 编号） | ≥ 3 处 |
| 生动类比/比喻 | ≥ 2 个 |
| 真实配图（图文交错插入） | ≥ 3 张 |
| 结尾金句 callout | 1 句 |
| 代码段（如该论文有公开 github） | ≥ 2 段，标 `文件路径:行号` |
| 指出局限 | ≥ 2 处（作者自述 + 你的判断） |

### Outline（写作内部框架，不是 H1 字面量）

1. **开场钩子**：反常识/共鸣场景，**不要直接讲技术** —— 2–3 段
2. **现有方法瓶颈**：现有逻辑 + 瓶颈，用简单例子说明 —— 3–4 段
3. **核心洞察**：论文最关键的发现 + 一个类比强化 —— 1–2 段
4. **方法详解**（全文最重）：分步展开 + 类比 + 引用原文公式 ≥3 处 + 新旧对比表 + 代码段（如有） —— 5–8 段
5. **实验**：最有说服力的结果 + 数据可感知化 + 关键对比表 —— 3–4 段
6. **深层意义**：技术 / 产业 / 方法学三角度 —— 2–3 段
7. **局限**：作者自述 + 你的判断 —— 1–2 段
8. **收束**：回到开头闭环 —— 1 段
9. **金句**：一句话让人记住并转述（独立 callout，无 H1） —— 1 句

### ⚠️ H1 规则（全 skill 只在这里讲一次，自审时回到这条）

每个 section 的 H1 必须是下面两种**之一**：

✅ **内容话题词**（这一节讲什么内容）：方法详解 / 实验效果 / 实验 / 局限 / 总结 / 结论 / 深层意义 / 核心洞察 / 研究背景 / 为什么会这样 / 讨论 / 预备知识 / 开场 / 故事的起点

✅ **paper-specific 实质标题**（从论文具体概念/数字/瓶颈提炼，8–20 字）：
- "为什么 MAE 学不会 3D 一致性"
- "Plücker 射线 + MoDE：两条骨架"
- "Libero 92.2% 与 Mv-Bench 20 个点的领先"

❌ **禁用"修辞功能词"**——描述这节在文章结构里扮演什么角色的元标签：

| 错误 H1 | 错在哪 |
|---|---|
| "钩子开头" / "钩子" / "开场白" / "序言" | 描述这是 hook 的功能，不是开场讲什么 |
| "收束 + 金句" / "尾声 + 金句" | 收束 OK，金句不要进 H1（金句应是 callout，本就无 H1） |
| "1 · 方法详解" / "2 · 实验" | 不要数字编号前缀（这是 outline 标记，不是标题的一部分） |

**判断法**：把 H1 念出来，能不能让读者知道"这节讲什么"？"方法详解"✓、"30 度的难题"✓、"钩子开头"✗（只知道是个 hook）。

**开场段也要有 H1**：用内容话题词（如"开场"/"故事的起点"）或 paper-specific 实质标题，**不能**用"钩子开头"字面量。

### 写法要求

- 多用"你"和读者对话（"你猜怎么着""你有没有想过"）
- 段落短：一段不超过 4 句话
- 技术词出现时**立刻**给"人话解释"
- 数据可感知化（"15 斤荔枝"而不只是"15 斤"）
- ❌ **禁用 AI 套话**：深入探讨 / 至关重要 / 值得注意的是 / 通过本研究 / 综上所述 / 在本文中 / 进一步研究 / 具有重要意义

---

## Phase 3：组装 plan-JSON（先落本地）→ 回放推进飞书（图文交错）

⚠️ **核心架构**：不要边想边直接 push。**先**把全文组装成本地 plan-JSON，**再**机械回放进飞书。好处：推送失败不丢分析、可重试、便于自审。

### 3.1 组装本地 plan-JSON

把全文拆成**有序块数组**，写到 `{workdir}/_docx_plan_{paper_id}.json`。每块是 `xml` 或 `fig`：

```json
[
  {"type":"xml","content":"<title>中文标题</title><callout emoji=\"📚\" background-color=\"light-blue\" border-color=\"blue\"><p>👉 <a href=\"{INDEX_URL}\">返回今日论文索引</a></p></callout><callout emoji=\"💡\" background-color=\"light-yellow\" border-color=\"yellow\"><p><b>一句话总结</b>：（100 字内）</p></callout><p><b>作者</b>: ...<br/><b>机构</b>: ...<br/><b>论文</b>: <a href=\"{PDF_URL}\">论文 PDF</a><br/><b>代码</b>: 未公开（或 GitHub URL）</p>"},
  {"type":"xml","content":"<h1>开场 H1</h1><p>...反常识场景...</p><p>...</p><p>...</p>"},
  {"type":"xml","content":"<h1>现有方法的瓶颈</h1><p>...</p>"},
  {"type":"xml","content":"<h1>核心洞察</h1><p>...用 <latex>核心公式</latex>...类比...</p>"},
  {"type":"fig","file":"./fig2_architecture.png","caption":"Figure 2. ...（中文图注，点明对应正文哪个点）"},
  {"type":"xml","content":"<h1>方法详解</h1><p>...</p><pre lang=\"python\" caption=\"model.py:42\"><code>...转义后的代码...</code></pre>"},
  {"type":"xml","content":"<h1>实验</h1>...<table>...</table>..."},
  {"type":"fig","file":"./fig3_results.png","caption":"Figure 3. ..."},
  {"type":"xml","content":"<h1>深层意义</h1><p>...</p><h1>局限</h1><p>...</p>"},
  {"type":"xml","content":"<callout emoji=\"✨\" background-color=\"light-purple\" border-color=\"purple\"><p>{金句}</p></callout>"}
]
```

要点：
- **顶部"返回索引"按钮**：`{INDEX_URL}` 用 briefing 里给你的 INDEX_URL（紧跟 `<title>` 之后、在一句话总结之前，确保在文档最顶部）。briefing 未提供 INDEX_URL（如 `--no-feishu`）时，**省略**这个 callout。
- **图文交错顺序 = 数组顺序**。把 `fig` 块放在它要解释的正文块**后面**，不要全堆末尾。
- `content` 是合法 DocxXML 片段（`< > &` 在代码块里要转义）。meta-info 段**不要**写 venue / 年份 / paper_id。
- `fig.file` 是相对 `_work_{paper_id}/images/` 的路径（如 `./fig2_architecture.png`）。
- **组装完先自检 plan-JSON**：`python3 -c "import json,sys;json.load(open(sys.argv[1]))" {workdir}/_docx_plan_{paper_id}.json` 必须 parse 通过；否则修到能 parse 再 push。

### 3.2 回放 plan-JSON → 飞书（幂等 + 重试）

**① 幂等建文档**：先看 `{workdir}/_token_{paper_id}.json` 是否存在。
- 存在 → 读出里面的 `doc_id` / `doc_token` / `doc_url`，**跳过创建**，直接进 ②（这是重试路径，避免重复文档）。
- 不存在 → `lark-cli docs +create --api-version v2 --title "{中文标题}" --parent-token {DATE_FOLDER_TOKEN} --content '<plan-JSON 第 0 块即 title+总结+meta 的 content>'`，解析 stdout 拿 `document_id` / `url`，**立刻**写 `{workdir}/_token_{paper_id}.json`：`{"paper_id":<int>,"doc_id":"...","doc_token":"...","doc_url":"..."}`。

**② `cd {workdir}/_work_{paper_id}/images`**（必须，lark-cli `--file` 拒绝绝对路径）。

**③ 顺序遍历 plan-JSON 的第 1 块起**（第 0 块已在 create 时写入）：
- `xml` 块 → `lark-cli docs +update --api-version v2 --doc $DOC_ID --command append --content '<content>'`
- `fig` 块 → `lark-cli docs +media-insert --doc $DOC_ID --file <fig.file> --caption "<fig.caption>" --align center`（**注意**：media-insert 不接受 `--api-version`，加了会报错）

**④ 重试**：每个 lark-cli 调用若返回 429 / 5xx / `Overloaded`，退避重试（sleep 2/4/8s）最多 3 次。`missing_scope` / `token expired` 不重试，直接进失败返回。

DocxXML 语法、create/update/media-insert 的完整参数见 `references/feishu-docxml.md`。

---

## Phase 4：自审（数你已落 plan-JSON 的内容）

- 字数 ≥ 3000？`<p>` ≥ 15？类比 ≥ 2？原文引用（公式/Figure/Table 编号）≥ 3？
- 配图 ≥ 3（图文交错，不是堆末尾）？金句 callout 1 句？代码段 ≥ 2（如找到 github）？局限 ≥ 2？
- **开场段有 H1**（内容话题词 / paper-specific 实质标题，**不是**"钩子开头"字面量）？
- **没有任何 H1 含修辞功能词**（钩子 / 开头 / 序言 / 尾声 / 金句 / "1 · " 数字编号）？（内容话题词如方法详解/实验/局限/总结/核心洞察/深层意义 作 H1 是 OK 的）
- meta-info 段无 venue / 年份 / paper_id？无 AI 套话？

**本地素材自审**：
- `ls {workdir}/_pdfs/{paper_id}.pdf` 存在？
- `ls {workdir}/_work_{paper_id}/images/manifest.json` 存在？
- `ls {workdir}/_docx_plan_{paper_id}.json` 存在且能 parse？
- plan-JSON 里**没有**任何 `<img href="https://...">`（图全走 `fig` 块）？
- 用过 git 找代码的话 `ls /tmp/paper_code_{paper_id}/` 存在？

任一不达标 → 改 plan-JSON 并把缺失部分 `+update --command append` 补进飞书、违规 H1 用 `block_replace` 改、多余块用 `block_delete` 删。

---

## 唯一返回（一行 JSON，不要任何其他文本）

成功：
```json
{"paper_id": <int>, "status": "success", "stage": "done", "doc_url": "<URL>", "doc_token": "<token>", "plan_path": "<{workdir}/_docx_plan_{paper_id}.json>", "n_figures": <int>, "n_paragraphs": <int>, "has_code": <bool>}
```

部分成功（plan-JSON 已落本地，但推进飞书中途失败——可重试）：
```json
{"paper_id": <int>, "status": "partial", "stage": "<push_append|push_media|...>", "error": "<60 字内>", "doc_url": "<已建则填>", "doc_token": "<已建则填>", "plan_path": "<路径>"}
```

失败（取材/写作阶段就断，无可用产物）：
```json
{"paper_id": <int>, "status": "failed", "stage": "<download_pdf|unsupported_source|docxml_invalid|...>", "error": "<60 字内>", "doc_url": "", "doc_token": ""}
```
