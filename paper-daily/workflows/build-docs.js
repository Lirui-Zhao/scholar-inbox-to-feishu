export const meta = {
  name: 'paper-daily-build',
  description: 'Build one Feishu doc per paper (PDF→code→figures→storytelling→plan-JSON→push), then quality-verify and bounded-repair each',
  whenToUse: 'paper-daily Round 3 fan-out: turn a deduped list of Scholar Inbox papers into one Feishu cloud doc each, concurrently, with a per-paper quality gate.',
  phases: [
    { title: 'Build', detail: 'one sub-agent per paper: read PDF, find code, fetch figures, write Chinese storytelling DocxXML to a local plan-JSON, replay into Feishu' },
    { title: 'Verify', detail: 'read the local plan-JSON, compute deterministic metrics, run one bounded repair pass if below bar' },
  ],
}

// ── args (passed by the main agent; see SKILL.md Round 3) ────────────────────
//   papers          : array of Scholar Inbox digest objects (already deduped/limited)
//   dateFolderToken : Feishu folder token for ~/papers-daily/YYYY-MM-DD (Round 0.5)
//   workdir         : absolute path, e.g. /root/papers-daily/2026-05-29
//   date            : YYYY-MM-DD
//   guidePath       : absolute path to references/paper-writeup-guide.md
//   docxmlPath      : absolute path to references/feishu-docxml.md
//   parallelHint    : advisory concurrency (Workflow caps at min(16, cores-2); not a hard knob)
// Defensive: some harnesses deliver `args` as a JSON-encoded string; coerce it.
const A = (typeof args === 'string') ? JSON.parse(args) : (args || {})
if (!A || !Array.isArray(A.papers) || A.papers.length === 0) {
  throw new Error('build-docs.js: args.papers must be a non-empty array (got typeof args=' + (typeof args) + ')')
}
const papers = A.papers
const dateFolderToken = A.dateFolderToken || ''
const workdir = A.workdir
const guidePath = A.guidePath || '~/.claude/skills/paper-daily/references/paper-writeup-guide.md'
const docxmlPath = A.docxmlPath || '~/.claude/skills/paper-daily/references/feishu-docxml.md'
const indexDocUrl = A.indexDocUrl || ''   // pre-built daily-index shell URL; '' = no back-link
if (!workdir) throw new Error('build-docs.js: args.workdir is required')

// ── schemas (force validated structured returns) ─────────────────────────────
const RETURN_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    paper_id: { type: 'integer' },
    status: { type: 'string', enum: ['success', 'partial', 'failed'] },
    stage: { type: 'string' },
    doc_url: { type: 'string' },
    doc_token: { type: 'string' },
    plan_path: { type: 'string' },
    n_figures: { type: 'integer' },
    n_paragraphs: { type: 'integer' },
    has_code: { type: 'boolean' },
    error: { type: 'string' },
  },
  required: ['paper_id', 'status', 'stage'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  properties: {
    paper_id: { type: 'integer' },
    meets_bar: { type: 'boolean' },
    char_count: { type: 'integer' },
    n_paragraphs: { type: 'integer' },
    n_figures: { type: 'integer' },
    n_latex: { type: 'integer' },
    n_refs: { type: 'integer', description: 'count of cited 公式/Figure/Table references' },
    h1_violations: { type: 'array', items: { type: 'string' } },
    cliche_hits: { type: 'array', items: { type: 'string' } },
    issues: { type: 'array', items: { type: 'string' } },
    repaired: { type: 'boolean' },
    status: { type: 'string', description: 'success | failed (for recovery reporting)' },
    doc_url: { type: 'string' },
    doc_token: { type: 'string' },
  },
  required: ['paper_id', 'meets_bar', 'issues', 'repaired'],
}

// ── prompts ──────────────────────────────────────────────────────────────────
function buildBriefing(p) {
  const pid = p.paper_id
  return `你的任务：把下面这一篇论文做成一个飞书云文档。

【第一步：读方法论】用 Read 工具读这两个文件，严格照做（不要凭记忆）：
1. ${guidePath}  —— 全套流程（取材→写作→组装 plan-JSON→回放推飞书→自审→返回协议）
2. ${docxmlPath} —— DocxXML 语法 + lark-cli 命令

【你这篇论文】paper_id=${pid}，标题《${p.title || ''}》。
完整记录在 ${workdir}/_todo.json（一个数组，按 paper_id 匹配你这篇）。先 Read / python 取出你这篇的字段：
title / abstract / authors / affiliations / arxiv_id / url / html_link / github_url / project_url / teaser_captions / ranking_score / total_read / total_likes（后两个用于 meta 热度行；缺失则省略热度）。
下载 PDF：arxiv_id 非空 → \`https://arxiv.org/pdf/{arxiv_id}\`；否则 url 以 .pdf 结尾 → 直接下 url（CVPR openaccess paper.pdf 属此类）；都不满足 → 按 guide 返回 unsupported_source。

【飞书目标】
- 父文件夹 token: ${dateFolderToken}（创建文档时必须带 --parent-token）
- 文档标题用中文友好版（自己据论文提炼）
- 顶部横幅：plan-JSON 第 0 块、紧跟 <title>、在一句话总结之前，放这个 callout（确保在文档最顶部）：
  ${indexDocUrl
    ? `<callout emoji="📚" background-color="light-blue" border-color="blue"><p>👉 <a href="${indexDocUrl}">返回今日论文索引</a>　·　👍 <a href="https://www.scholar-inbox.com">去 Scholar Inbox 点赞（帮它学你的口味）</a></p></callout>`
    : `<callout emoji="📚" background-color="light-blue" border-color="blue"><p>👍 <a href="https://www.scholar-inbox.com">去 Scholar Inbox 点赞（帮它学你的口味）</a></p></callout>   （本次无索引，只放点赞链接）`}
- meta 热度行：用 _todo.json 的 affiliations / total_read / total_likes（缺失则省略热度行）。

【工作目录命名空间】（绝对路径，避免并发冲突）
- workdir          : ${workdir}
- PDF              : ${workdir}/_pdfs/${pid}.pdf
- 抓图输出         : ${workdir}/_work_${pid}/   （图在 ${workdir}/_work_${pid}/images/）
- 代码 clone       : /tmp/paper_code_${pid}/
- 本地 plan-JSON   : ${workdir}/_docx_plan_${pid}.json
- 幂等 token 文件  : ${workdir}/_token_${pid}.json   （已存在则复用 doc_token、跳过建文档）

务必先 mkdir -p ${workdir}/_pdfs ${workdir}/_work_${pid}。

【铁律 · 不可违反】
1. **只用真实命令**：建/改飞书文档只有这些子命令——\`lark-cli docs +create\`、\`lark-cli docs +update --command append|block_replace|block_delete\`、\`lark-cli docs +media-insert\`、\`lark-cli docs +fetch\`。**没有 \`lark-cli docx\` 命令（是 docs），更没有 \`replay\` 命令。**"回放 plan-JSON" 指的是你自己写一个循环：按 plan-JSON 顺序，xml 块用 +update append、fig 块用 +media-insert，**逐块手动推**，不是某个 replay 命令。先 \`lark-cli docs +create --help\` 看真实 flag。
2. **建文档后立刻写 token 文件**：\`docs +create\` 拿到 document_id/url 的那一刻，立即把 {"paper_id":${pid},"doc_id":"...","doc_token":"...","doc_url":"..."} 写到 ${workdir}/_token_${pid}.json。这是恢复与防重复的唯一依据。
2.5. **落点保障**：建文档 + 写 token 文件后，**立刻**执行 \`lark-cli drive +move --file-token <doc_token> --folder-token ${dateFolderToken} --type docx\`（幂等无害），确保文档在目标父夹而不是云盘根目录。
3. **用 fetch_images.py 抓图**，别手搓 pdftoppm 整页转图当配图。长论文（>20 页）：分多次 Read PDF（每次 5–6 页）、只对少数关键页整页渲染兜底。
4. **StructuredOutput 是最后一个动作**：把"推完飞书 + Phase 4 自审 + 必要修补"全部做完后，**最后**调用一次 StructuredOutput 返回结果；返回后**不要再调用任何工具**。status 用 success / partial / failed。

严格按 guide 的「唯一返回」协议返回一行 JSON（success / partial / failed），不要任何其他文本。`
}

function verifyBriefing(p, built) {
  const pid = p.paper_id
  return `质量校验 + 有界修补：论文 paper_id=${pid}，飞书文档 doc_token=${built.doc_token || '(无)'}，doc_url=${built.doc_url || '(无)'}。

【1. 读本地 plan-JSON 算确定性指标】读 ${workdir}/_docx_plan_${pid}.json（块数组，xml/fig 两类）。用 Bash/python 统计：
- char_count：所有 xml 块 content 里的中文字符数（CJK 0x4E00–0x9FFF），目标 ≥ 3000
- n_paragraphs：<p> 出现次数，目标 ≥ 15
- n_latex：<latex> 次数（目标 ≥ 1，方法详解应有公式）
- n_figures：fig 块数，目标 ≥ 3
- n_refs：正文里"公式/Figure/Table/图/表 + 编号"的引用次数，目标 ≥ 3
- h1_violations：含修辞功能词的 <h1>（钩子/开头/序言/尾声/金句/"N · "数字编号前缀）——见 guide 的 H1 规则
- cliche_hits：命中 AI 套话（深入探讨/至关重要/值得注意的是/通过本研究/综上所述/在本文中/进一步研究/具有重要意义）

【2. 不达标 → 一次有界修补】若任一硬指标未达标 或 有 h1_violations/cliche_hits：
- 用 doc_token 对飞书文档做**一次**修补：缺段落/字数 → 写**真实补充内容**（如补一段"局限"或"深层意义"的实质分析）后 lark-cli docs +update --command append；违规 H1 → block_replace 成内容话题词；套话 → block_replace 重写该句；图不足 → 读 manifest 再 +media-insert；若文档不在目标父夹 ${dateFolderToken}（掉到了云盘根目录）→ lark-cli drive +move --file-token ${built.doc_token || '<doc_token>'} --folder-token ${dateFolderToken} --type docx 归位（属本次有界修补的一部分，幂等无害）。
- ❌ 严禁用"进一步分析表明…/本文具有重要意义…"这类空话凑数（那本身就是被禁的 AI 套话）。
- 修补后同步更新本地 plan-JSON，repaired=true。
- 限一次：修补后仍不达标，meets_bar=false，把缺口写进 issues，不再循环。

返回 VERDICT JSON（含 paper_id）。`
}

// Recovery: when build did NOT return cleanly (e.g. it called StructuredOutput then
// kept working → agent() throws), find any doc that was actually created via the
// on-disk _token_<pid>.json the build agent writes on +create, then verify+repair it.
// The on-disk token is the source of truth, decoupled from a clean structured return.
function recoverBriefing(p, built) {
  const pid = p.paper_id
  return `恢复 + 校验：上一步 build 没有干净返回（可能 StructuredOutput 后又继续操作、或中途出错）。先弄清文档到底建出来没有。

【1. 找回已建文档】Read ${workdir}/_token_${pid}.json。
- 不存在 → 文档没建成：返回 {paper_id:${pid}, meets_bar:false, status:"failed", doc_url:"", doc_token:"", issues:["no doc created (no _token file)"], repaired:false}，结束。
- 存在 → 取 doc_id / doc_token / doc_url，进入校验。再用 lark-cli docs +fetch --doc <doc_token> --api-version v2 确认文档真的存在（取不到就当未建成，按上一行返回 failed）。

【2. 校验】对照 ${workdir}/_docx_plan_${pid}.json（若在）与飞书文档本体算指标：
char_count(中文≥3000)/n_paragraphs(<p>≥15)/n_latex/n_figures(≥3)/n_refs(≥3)/
h1_violations(<h1>含 钩子|开头|序言|尾声|金句|"N ·"数字编号前缀)/
cliche_hits(深入探讨|至关重要|值得注意的是|通过本研究|综上所述|在本文中|进一步研究|具有重要意义)/
顶部点赞横幅是否在（应含 https://www.scholar-inbox.com 的"去 Scholar Inbox 点赞"）。
**落点校验**：确认文档确实在目标父夹 ${dateFolderToken} 内（用 \`lark-cli drive files list --params '{"folder_token":"${dateFolderToken}"}'\` 看成员里有无该 doc_token）；若不在（掉到了云盘根目录）→ \`lark-cli drive +move --file-token <doc_token> --folder-token ${dateFolderToken} --type docx\` 归位（直接 move 兜底亦可，幂等无害）。

【3. 一次有界修补】用 doc_token 对飞书文档做**一次**修补（只用真实命令 docs +update --command append|block_replace、docs +media-insert）：
违规 H1 → block_replace 成内容话题词；字数/段落不足 → append **真实**补充段落（❌禁 AI 套话凑数）；缺点赞横幅 → 在最前补 <callout emoji="📚" background-color="light-blue" border-color="blue"><p>👍 <a href="https://www.scholar-inbox.com">去 Scholar Inbox 点赞（帮它学你的口味）</a></p></callout>（定位不到就 append，至少要有）；图不足 → 读 manifest 再 +media-insert。

【4. 返回】**只调用一次** StructuredOutput 返回 VERDICT JSON：必带 paper_id/meets_bar/issues/repaired，并带 status("success"/"failed")+doc_url+doc_token。返回后不要再调用任何工具。`
}

// ── pipeline: build → verify(+repair), per-paper, no batch barrier ────────────
const results = await pipeline(
  papers,
  (p) => agent(buildBriefing(p), {
    label: `build:${p.paper_id}`,
    phase: 'Build',
    schema: RETURN_SCHEMA,
    agentType: 'general-purpose',
  }).catch((e) => ({ paper_id: p.paper_id, status: 'build_threw', stage: 'build_exception', error: String(e).slice(0, 200), doc_url: '', doc_token: '' })),
  (built, p) => {
    // build agent occasionally fumbles its return (StructuredOutput then keeps working)
    // → agent() threw and was caught above. Either way stage 2 ALWAYS runs: verify a
    // clean build, or recover one whose doc may exist on disk.
    const clean = built && built.status === 'success' && built.doc_url
    const prompt = clean ? verifyBriefing(p, built) : recoverBriefing(p, built)
    return agent(prompt, {
      label: `${clean ? 'verify' : 'recover'}:${p.paper_id}`,
      phase: 'Verify',
      schema: VERDICT_SCHEMA,
    }).then((verdict) => {
      const docUrl = clean ? built.doc_url : (verdict && verdict.doc_url) || ''
      const docTok = clean ? built.doc_token : (verdict && verdict.doc_token) || ''
      return { ...(built || { paper_id: p.paper_id }), status: docUrl ? 'success' : 'failed', doc_url: docUrl, doc_token: docTok, verdict }
    }).catch((e) => ({ ...(built || { paper_id: p.paper_id }), status: 'failed', stage: 'verify_exception', error: String(e).slice(0, 160), verdict: null }))
  }
)

const clean = results.filter(Boolean)
const succeeded = clean.filter((r) => r.status === 'success')
const belowBar = succeeded.filter((r) => r.verdict && r.verdict.meets_bar === false)
log(`build-docs done: ${succeeded.length}/${papers.length} success, ${belowBar.length} below quality bar after repair`)

return {
  date: A.date,
  total: papers.length,
  succeeded: succeeded.length,
  failed: clean.length - succeeded.length,
  below_bar: belowBar.length,
  results: clean,
}
