"""Tests for backfill_history.py — heat-field passthrough, history doc_url lookup,
and the one-line-summary sources (structured sidecar preferred, callout regex as
backward-compatible fallback for papers built before the sidecar existed).

Run as a subprocess so PAPER_DAILY_WORKDIR_ROOT (read at import) points at a
temp history tree.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

BACKFILL = os.path.join(os.path.dirname(__file__), "..", "scripts", "backfill_history.py")


def _w(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


class BackfillHistoryTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pd-backfill-")
        self.env = dict(os.environ, PAPER_DAILY_WORKDIR_ROOT=self.root)

        # --- paper 111: OLD paper (no sidecar) → summary must come from callout regex ---
        d1 = os.path.join(self.root, "2026-05-30")
        os.makedirs(d1)
        _w(os.path.join(d1, "_feishu_records.json"),
           [{"paper_id": 111, "title": "中文标题A", "doc_url": "https://x.feishu.cn/docx/aaa"}])
        _w(os.path.join(d1, "_docx_plan_111.json"),
           [{"type": "xml",
             "content": "<title>中文标题A</title>"
                        "<p><b>一句话总结</b>：这是A的精炼总结。</p>"}])
        # note: NO _docx_meta_111.json — simulates a pre-change paper

        # --- paper 333: NEW paper with structured sidecar; its callout uses non-standard
        #     wording so the regex would MISS — proving the sidecar decouples extraction ---
        d2 = os.path.join(self.root, "2026-05-31")
        os.makedirs(d2)
        _w(os.path.join(d2, "_token_333.json"),
           {"paper_id": 333, "doc_id": "x", "doc_token": "t",
            "doc_url": "https://x.feishu.cn/docx/ccc"})
        _w(os.path.join(d2, "_docx_plan_333.json"),
           [{"type": "xml",
             "content": "<title>中文标题C</title>"
                        "<p><b>核心提要</b>：正则抓不到的写法。</p>"}])
        _w(os.path.join(d2, "_docx_meta_333.json"),
           {"title": "中文标题C", "summary": "结构化总结C。"})

        # today's digest: 111 (history+regex), 222 (no history), 333 (history+sidecar)
        self.digest = os.path.join(self.root, "_digest.json")
        _w(self.digest, [
            {"paper_id": 111, "title": "Original Title A", "ranking_score": 0.91,
             "affiliations": ["Fudan", "MIT"], "total_read": 50, "total_likes": 7,
             "url": "https://arxiv.org/pdf/1234.5678"},
            {"paper_id": 222, "title": "Original Title B", "ranking_score": 0.80,
             "affiliations": ["CMU"], "total_read": 3, "total_likes": 0,
             "project_url": "https://example.com/paperB"},
            {"paper_id": 333, "title": "Original Title C", "ranking_score": 0.70,
             "affiliations": ["Tsinghua"], "total_read": 9, "total_likes": 2,
             "url": "https://arxiv.org/pdf/9999.0000"},
        ])
        self.out = os.path.join(self.root, "_history_records.json")

    def _run(self):
        subprocess.run(
            [sys.executable, BACKFILL, "--digest", self.digest,
             "--out", self.out, "--exclude-date", "2026-06-02"],
            env=self.env, capture_output=True, text=True, check=True,
        )
        with open(self.out, encoding="utf-8") as f:
            return {r["paper_id"]: r for r in json.load(f)}

    def test_heat_fields_passed_through(self):
        recs = self._run()
        self.assertEqual(recs[111]["affiliations"], ["Fudan", "MIT"])
        self.assertEqual(recs[111]["total_read"], 50)
        self.assertEqual(recs[111]["total_likes"], 7)
        self.assertEqual(recs[222]["affiliations"], ["CMU"])
        self.assertEqual(recs[222]["total_likes"], 0)

    def test_history_lookup_found(self):
        a = self._run()[111]
        self.assertTrue(a["found"])
        self.assertEqual(a["doc_url"], "https://x.feishu.cn/docx/aaa")
        self.assertEqual(a["title"], "中文标题A")  # history Chinese title wins

    def test_history_miss_falls_back(self):
        b = self._run()[222]
        self.assertFalse(b["found"])
        self.assertEqual(b["doc_url"], "")
        self.assertEqual(b["fallback_url"], "https://example.com/paperB")
        self.assertEqual(b["title"], "Original Title B")  # no history → digest title

    def test_summary_from_callout_regex_backward_compat(self):
        # OLD paper (no sidecar): summary still extracted from the callout, as before
        self.assertEqual(self._run()[111]["summary"], "这是A的精炼总结。")

    def test_summary_from_structured_sidecar(self):
        # NEW paper: sidecar wins; its non-standard callout wording would defeat the
        # regex, so a non-empty summary here proves extraction is decoupled from prose
        c = self._run()[333]
        self.assertEqual(c["summary"], "结构化总结C。")
        self.assertEqual(c["title"], "中文标题C")
        self.assertTrue(c["found"])


if __name__ == "__main__":
    unittest.main()
