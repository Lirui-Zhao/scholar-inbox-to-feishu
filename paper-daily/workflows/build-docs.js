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
- 用 doc_token 对飞书文档做**一次**修补：缺段落/字数 → 写**真实补充内容**（如补一段"局限"或"深层意义"的实质分析）后 lark-cli docs +update --command append；违规 H1 → block_replace 成内容话题词；套话 → block_replace 重写该句；图不足 → 读 manifest 再 +media-insert。
- ❌ 严禁用"进一步分析表明…/本文具有重要意义…"这类空话凑数（那本身就是被禁的 AI 套话）。
- 修补后同步更新本地 plan-JSON，repaired=true。
- 限一次：修补后仍不达标，meets_bar=false，把缺口写进 issues，不再循环。

返回 VERDICT JSON（含 paper_id）。`
}

// ── pipeline: build → verify(+repair), per-paper, no batch barrier ────────────
const results = await pipeline(
  papers,
  (p) => agent(buildBriefing(p), {
    label: `build:${p.paper_id}`,
    phase: 'Build',
    schema: RETURN_SCHEMA,
    agentType: 'general-purpose',
  }),
  (built, p) => {
    // build failed or no doc → nothing to verify; pass through
    if (!built || built.status !== 'success' || !built.doc_url) {
      return { ...(built || { paper_id: p.paper_id, status: 'failed', stage: 'build_returned_null' }), verdict: null }
    }
    return agent(verifyBriefing(p, built), {
      label: `verify:${p.paper_id}`,
      phase: 'Verify',
      schema: VERDICT_SCHEMA,
    }).then((verdict) => ({ ...built, verdict }))
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
