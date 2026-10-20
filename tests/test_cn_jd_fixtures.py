"""Regression tests on five fictional JDs (tests/fixtures/cn_jd/*.txt).

Every company, number and phone line in the fixtures is made up. The checker
only reads pasted text; it never fetches, greets, or applies.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import cn_jd_check  # noqa: E402

FIX = REPO / "tests" / "fixtures" / "cn_jd"
EXAMPLE = REPO / "config" / "cn_filters.example.json"


def jd(name: str) -> str:
    return (FIX / f"{name}.txt").read_text(encoding="utf-8")


class FixtureBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.custom = Path(cls._tmp.name) / "filters.json"
        shutil.copy(EXAMPLE, cls.custom)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def check(self, name, config=None):
        return cn_jd_check.check_jd(jd(name), config_path=config or self.custom)

    def row(self, report, name):
        return next(r for r in report["hard_filters"] if r["name"] == name)


class Item1ThresholdSource(FixtureBase):
    def test_example_thresholds_never_hard_fail(self):
        report = cn_jd_check.check_jd(jd("jd3_social"), config_path=EXAMPLE)
        self.assertEqual(report["thresholds_source"], "example")
        self.assertFalse(report["hard_fail"])
        self.assertIn("cn_filters.json", report.get("warning", ""))

    def test_custom_config_is_custom(self):
        self.assertEqual(self.check("jd3_social")["thresholds_source"], "custom")


class Item2FalsePositives(FixtureBase):
    def test_jd2_intern_clears_deposit_hotline_and_student_status(self):
        report = self.check("jd2_intern")
        self.assertEqual(report["thresholds_source"], "custom")
        self.assertEqual(report["scam"], [])
        self.assertNotIn("996", [item["phrase"] for item in report["jargon"]])
        self.assertNotEqual(self.row(report, "degree")["status"], "fail")

    def test_real_deposit_slang_and_degree_floor_still_count(self):
        deposit = cn_jd_check.check_jd("需缴纳押金500元")
        self.assertEqual(deposit["scam"], [{"category": "押金", "phrase": "押金"}])

        slang = cn_jd_check.check_jd("公司996")
        self.assertIn("996", [item["phrase"] for item in slang["jargon"]])

        floored = cn_jd_check.check_jd("学历：硕士及以上")
        self.assertEqual(floored["parsed"]["degree"]["required"], "master")


if __name__ == "__main__":
    unittest.main()
