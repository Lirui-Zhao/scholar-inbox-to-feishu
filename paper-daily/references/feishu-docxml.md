# Feishu DocxXML —— 语法 + lark-cli 食谱

> paper-daily 把内容用飞书 **DocxXML 原生格式**直构造，不走 HTML 中间形态。
> 本文是 **主 agent**（建 Round 4 当日索引 doc）和 **sub-agent**（建单篇深读 doc）共用的语法/命令真相源。

## 一次性环境准备（已对 lark-cli v1.0.43 实测）

```bash
# 1. 装官方 CLI
npm install -g @larksuite/cli

# 2. 初始化应用配置（会阻塞并输出一个验证 URL —— 浏览器打开完成 app 授权）
lark-cli config init --new

# 3. 用户身份授权（device flow，会再给一个验证 URL；务必带上所需 scope）
lark-cli auth login --domain docs,drive,im
#   headless / agent 场景：lark-cli auth login --domain docs,drive,im --no-wait --json
#   → 把 verification_url 发给用户，待其确认后再：lark-cli auth login --device-code <device_code>

# 4. 校验
lark-cli auth status   # identities.user.openId 非空；scope 串含 im:message.send_as_user / docx:document / drive:drive
```

> 可选：`npx skills add larksuite/cli -g -y` 装官方 agent skill 增强提示——**非必需**，本 skill 已自带 references/。
>
> ⚠️ `--recommend` 只申请"自动批准"的 scope，可能漏掉 `im:message.send_as_user`，所以这里显式 `--domain docs,drive,im`。

授权后 token 持久化（默认 7 天过期）。遇 401 / `needs_refresh` / token 过期 → `lark-cli auth login --refresh`；**部分版本（实测 v1.0.43）无 `--refresh` flag**（会报 `unknown flag: --refresh`），改用 `lark-cli auth login --domain docs,drive,im` 重新授权。

接收卡片的人（receiver）：默认本人 DM（当前认证用户 open_id）。发到群聊：`.env` 加 `FEISHU_RECEIVER=oc_xxxxxxxx`。

---

## DocxXML 渲染能力（已验证）

| 元素 | DocxXML 语法 | 飞书渲染 |
|---|---|---|
| 章节标题 | `<h1>` ~ `<h9>` | ✅ 有层级感 |
| 段落 | `<p>` | ✅ |
| 加粗 / 斜体 / 颜色 | `<b>` / `<em>` / `<span text-color="blue">` | ✅ |
| 换行 | `<br/>` | ✅ |
| 超链接 | `<a href="...">文字</a>` | ✅ |
| 高亮框 | `<callout emoji="💡" background-color="light-yellow" border-color="yellow">` | ✅ |
| 行内/块公式 | `<latex>E = mc^2</latex>` | ✅ **原生 LaTeX 渲染** |
| 代码块 | `<pre lang="python" caption="..."><code>...</code></pre>` | ✅ 带语言高亮 |
| 表格 | `<table>` + `<thead>` / `<tbody>` + `<th background-color="light-gray">` | ✅ 表头浅灰 |
| 图片 | `lark-cli docs +media-insert --file ./fig.png --caption "..."` | ✅ 上传后嵌入 |

转义：在 `<code>` 里的 `<` `>` `&` 必须写成 `&lt;` `&gt;` `&amp;`。可选颜色：`light-yellow`/`light-blue`/`light-green`/`light-purple`/`light-gray` 等。

---

## 建文档 / 追加 / 插图（lark-cli docs）

> ⚠️ **解析 lark-cli 输出**：stdout 前常有 `[lark-cli] [WARN] proxy detected …` / `Creating …` 等非 JSON 行（WARN 本走 stderr，但 `2>&1` 会把它混进 stdout）。解析 `document_id` / `folder_token` 前**从第一个 `{` 截取再 `json.loads`**（或 `json.JSONDecoder().raw_decode`），且**不要 `2>&1`**——让 WARN 留在 stderr。否则会解析成空串、token 丢失、下次重复建文件夹/文档。scripts/ 里的 Python（`feishu_push.py` 的 `extract_json`、`backfill_history.py`）已如此处理；主 agent 在 shell 里手动解析时尤须注意。

### 创建（带父文件夹）

```bash
lark-cli docs +create --api-version v2 \
    --title "{标题}" \
    --parent-token {FOLDER_TOKEN} \
    --content '<title>{标题}</title>...首屏内容...'
# 解析 stdout JSON：data.document.document_id (DOC_ID)、data.document.url (DOC_URL)
```

⚠️ 创建时**必须**带 `--parent-token`，否则文档落到根目录，归档失效。**并且**建完后务必再跑一次落点保障 move：`lark-cli drive +move --file-token <DOC_TOKEN> --folder-token <FOLDER_TOKEN> --type docx`（幂等无害）——因为 `+create` 偶发不把文档落进指定父夹会把它丢到云盘根目录，这一步兜底归位。

⚠️ **大段 / 含嵌套引号的 DocxXML 用 stdin，不要内联**：`--content '...'` 内联只适合短小片段；当内容很长或含 `"`、`'`、中文引号时，shell 转义极易出错。改用 stdin：
```bash
cat doc.xml | lark-cli docs +create --api-version v2 --title "..." --parent-token {TOKEN} --content -
```
注意 `--content @file` 也有"必须是 cwd 内相对路径"的限制（和 `+media-insert --file` 一样），绝对路径会被拒；stdin (`-`) 最省心。

### 追加正文（section-by-section）

```bash
lark-cli docs +update --api-version v2 --doc $DOC_ID --command append \
    --content '<h1>{H1}</h1><p>...</p>'
```

⚠️ **分段追加**，不要一次塞完整篇。这样既稳（规避单次体积上限），又方便图文交错。

### 插图（必须相对路径）

```bash
cd {images 目录}        # lark-cli --file 拒绝绝对路径，必须先 cd
# ⚠️ +media-insert 不接受 --api-version（加了会报 usage）；它本身就是 v2 orchestration
lark-cli docs +media-insert --doc $DOC_ID \
    --file ./fig2_architecture.png \
    --caption "Figure 2. ...（中文图注）" --align center
```

报 `unsafe file path: --file must be a relative path` = 没 cd 到图目录就用了绝对路径。

### 改 / 删已有块

`--command block_replace`（改违规 H1 等）、`--command block_delete`（删多余块）。块 id 从 `lark-cli docs +fetch --doc $DOC_ID --api-version v2`（回读文档结构）或 update 返回里取。

> 注：读回文档用 `docs +fetch`（不是 `+read`/`+get`）。媒体插入 `docs +media-insert` **默认追加到文档末尾**——paper-daily 的 plan-JSON 是顺序回放（先 append 一段正文、紧接着 media-insert 那张图），所以"追加到末尾"恰好把图放在刚写的正文后面，图文交错成立。

---

## doc_url 校验（租户无关）

合法飞书文档 URL 形如 `https://<tenant>.feishu.cn/docx/...`（v2）或 `.../docs/...`（legacy）或 `.../wiki/...`。校验正则：

```
^https://[^/]+\.feishu\.(cn|com)/(docx|docs|wiki)/
```

不要写死某个租户域名（如 `your-tenant.feishu.cn`）——换租户即失效。

---

## 单篇 doc 顶部横幅（返回索引 + 去点赞）

每篇深读 doc 的最顶部（`<title>` 之后、一句话总结之前）放一个横幅 callout，含两个动作：

```xml
<callout emoji="📚" background-color="light-blue" border-color="blue"><p>👉 <a href="{INDEX_URL}">返回今日论文索引</a>　·　👍 <a href="https://www.scholar-inbox.com">去 Scholar Inbox 点赞（帮它学你的口味）</a></p></callout>
```

- **返回索引**：`{INDEX_URL}` 是索引文档 URL。单篇 doc 在索引之前生成，所以主流程**先建索引壳子**（只含 `<title>`）拿到稳定 URL，传给各篇；索引正文最后再填。`--no-feishu` / 单链接模式（无索引）时**去掉这一段**。
- **去点赞**：链接是**常量** `https://www.scholar-inbox.com`（首页；用户登录态打开自己的 digest 去点赞，让推荐算法学口味）。**任何时候都保留**。⚠️ 绝不把 sha_key 放进链接。

meta-info 段（紧跟横幅的 `<p>`）除作者/论文/代码外，加 **机构**（`affiliations` 逗号连接）和 **热度**（`👀 {total_read} 人读过 · 👍 {total_likes} 赞`）；字段缺失（单链接模式）则省略热度行。

## Round 4：当日索引文档模式（主 agent 用）

主 agent **先建只含 `<title>` 的索引壳子**（Round 2.5，拿到稳定 URL 供各篇回链），待所有单篇 doc 建好后，把下面的**正文**（**不含 `<title>`**，标题已在壳子里）用 `docs +update --command append` 追加进壳子：

```xml
<callout emoji="📅" background-color="light-blue" border-color="blue">
  <p><b>今日 Top N</b>（按 Scholar Inbox 个性化相关度排序）<br/>
  <b>主题</b>：（根据 N 篇标题归纳 1–2 句）<br/>
  <b>共同点</b>：（有就写，没有省略）</p>
</callout>

<h1>今日精选</h1>

<table>
  <thead>
    <tr>
      <th background-color="light-gray">#</th>
      <th background-color="light-gray">论文</th>
      <th background-color="light-gray">机构</th>
      <th background-color="light-gray">相关度</th>
      <th background-color="light-gray">🔥 热度</th>
      <th background-color="light-gray">深度阅读</th>
    </tr>
  </thead>
  <tbody>
    <!-- N 行：序号、<b>中文标题</b>、机构(affiliations 缩写：前 1-2 个 + 等)、score、👀{total_read} 👍{total_likes}、<a href="DOC_URL">📖 打开</a> -->
  </tbody>
</table>

<h1>一句话简介</h1>

<h2><a href="{DOC_URL_1}">1 · 论文 1 中文标题</a></h2>
<p>（一句话简介，100–150 字，提炼核心创新 + 关键数字）</p>

<h2><a href="{DOC_URL_2}">2 · 论文 2 中文标题</a></h2>
<p>...</p>
<!-- N 个 H2，每个超链接到对应 doc -->

<callout emoji="💡" background-color="light-green" border-color="green">
  <p><b>怎么用这份索引</b>：点 "📖 打开" 或上方一句话简介标题，进入每篇完整深度解读。每篇约 10–15 分钟读完。</p>
</callout>
```

⚠️ 索引文档的 **H2 保留 "数字编号 · 中文标题"**（如 "1 · DiffuView：..."）是 OK 的——索引需要清晰导航编号。但 H2 后缀**不要**加 "(Fudan, CVPR 2026, score 0.943)"，venue/score 已在表格里。

> 注：单篇深读 doc 的正文 H1 规则（禁修辞功能词）见 `references/paper-writeup-guide.md`，与索引文档的 H2 编号规则是两回事，别混。
