"""Unit tests for feishu_push.py card rendering (机构 + 热度 同步)."""
import importlib.util
import os
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _load(name):
    path = os.path.join(SCRIPTS, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fp = _load("feishu_push")


def _div_contents(card):
    """All div text contents in order; element 0 is the intro line."""
    return [e["text"]["content"] for e in card["elements"] if e["tag"] == "div"]


class FmtAffiliationsTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(fp._fmt_affiliations(None), "")
        self.assertEqual(fp._fmt_affiliations([]), "")
        self.assertEqual(fp._fmt_affiliations(["", "  "]), "")

    def test_str_passthrough(self):
        self.assertEqual(fp._fmt_affiliations("Fudan"), "Fudan")

    def test_one_no_suffix(self):
        self.assertEqual(fp._fmt_affiliations(["Fudan"]), "Fudan")

    def test_two_no_suffix(self):
        self.assertEqual(fp._fmt_affiliations(["Fudan", "MIT"]), "Fudan、MIT")

    def test_more_than_two_gets_deng(self):
        self.assertEqual(
            fp._fmt_affiliations(["Fudan", "Shanghai AI Lab", "MIT"]),
            "Fudan、Shanghai AI Lab 等",
        )


class MetaLineTest(unittest.TestCase):
    def test_full(self):
        line = fp._meta_line(
            {"affiliations": ["Fudan", "MIT"], "total_read": 128, "total_likes": 24}
        )
        self.assertIn("🏛 Fudan、MIT", line)
        self.assertIn("👀 128", line)
        self.assertIn("👍 24", line)

    def test_zero_heat_still_shown(self):
        # 0 is a legitimate int → shown (sync with index doc, honest counts)
        line = fp._meta_line({"total_read": 0, "total_likes": 0})
        self.assertEqual(line, "👀 0 · 👍 0")

    def test_only_read(self):
        line = fp._meta_line({"total_read": 5})
        self.assertEqual(line, "👀 5")

    def test_missing_all_is_empty(self):
        self.assertEqual(fp._meta_line({}), "")
        # bools must not be treated as heat ints
        self.assertEqual(fp._meta_line({"total_read": True}), "")


class BuildCardTest(unittest.TestCase):
    def test_paper_row_has_meta_line(self):
        records = [
            {
                "paper_id": 1,
                "title": "扩散模型的三维一致性新解",
                "score": 0.943,
                "doc_url": "https://x.feishu.cn/docx/abc",
                "affiliations": ["Fudan", "Shanghai AI Lab", "MIT"],
                "total_read": 128,
                "total_likes": 24,
            }
        ]
        card = fp.build_card("2026-06-02", records)
        paper = _div_contents(card)[1]  # [0] is the intro line
        self.assertIn("**[0.943] 扩散模型的三维一致性新解**", paper)
        self.assertIn("🏛 Fudan、Shanghai AI Lab 等", paper)
        self.assertIn("👀 128 · 👍 24", paper)
        self.assertIn("📖 [打开](https://x.feishu.cn/docx/abc)", paper)
        # ordering: title line, then meta, then 打开
        self.assertLess(paper.index("🏛"), paper.index("📖"))

    def test_paper_row_without_heat_has_no_meta_line(self):
        # single-link mode: no affiliations / heat → no extra line
        records = [
            {"paper_id": 7, "title": "随手一篇", "score": 0.0,
             "doc_url": "https://x.feishu.cn/docx/zzz", "affiliations": []}
        ]
        card = fp.build_card("2026-06-02", records)
        paper = _div_contents(card)[1]
        self.assertNotIn("🏛", paper)
        self.assertNotIn("👀", paper)
        self.assertEqual(paper, "**[0.000] 随手一篇**\n📖 [打开](https://x.feishu.cn/docx/zzz)")

    def test_index_row_has_no_score_or_meta(self):
        records = [
            {"is_index": True, "paper_id": "INDEX",
             "title": "📚 当日索引", "doc_url": "https://x.feishu.cn/docx/idx"},
            {"paper_id": 1, "title": "正文篇", "score": 0.5,
             "doc_url": "https://x.feishu.cn/docx/abc",
             "affiliations": ["Fudan"], "total_read": 3, "total_likes": 1},
        ]
        card = fp.build_card("2026-06-02", records)
        idx = _div_contents(card)[1]
        self.assertIn("**📚 当日索引**", idx)
        self.assertNotIn("[0.", idx)   # no score bracket
        self.assertNotIn("🏛", idx)


if __name__ == "__main__":
    unittest.main()
