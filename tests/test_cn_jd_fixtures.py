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


class Item3ScamLexicon(FixtureBase):
    def test_jd4_rejects_on_fee_and_high_pay_lure(self):
        report = self.check("jd4_scam")
        self.assertEqual(report["verdict"], "reject")
        categories = {item["category"] for item in report["scam"]}
        self.assertIn("收费", categories)
        self.assertIn("高薪诱导", categories)

    def test_negation_and_employer_paid_fees_are_not_scams(self):
        clean = (
            "公司承担体检费，不收取任何培训费",
            "公司承担体检费",
            "公司支付体检费",
            "提供免费培训",
            "谨防刷单返利",
            "不收取任何培训费",
            "无需支付培训费",
            "不要下载招聘APP试岗",
            "当日入职",
            "按日结算",
        )
        for text in clean:
            with self.subTest(text=text):
                report = cn_jd_check.check_jd(text)
                self.assertEqual(report["scam"], [])

    def test_daily_pay_alone_is_slang_not_a_scam(self):
        report = cn_jd_check.check_jd("日结工资")
        self.assertEqual(report["scam"], [])
        self.assertFalse(report["scam_fail"])
        self.assertNotEqual(report["verdict"], "reject")
        self.assertEqual(report["jargon"], [{"phrase": "日结", "penalty": 4}])

    def test_lure_needs_both_sides(self):
        rich = cn_jd_check.check_jd("月入过万")
        self.assertEqual(rich["scam"], [])
        self.assertEqual(rich["jargon"], [{"phrase": "月入过万", "penalty": 6}])
        chat = cn_jd_check.check_jd("加微信详聊")
        self.assertEqual(chat["scam"], [])
        self.assertEqual(chat["jargon"], [{"phrase": "加微信详聊", "penalty": 6}])
        combo = cn_jd_check.check_jd("日结，无需经验")
        self.assertEqual({item["category"] for item in combo["scam"]}, {"高薪诱导"})
        self.assertEqual(combo["verdict"], "reject")

    def test_new_scam_categories(self):
        cases = (
            ("缴纳298元培训资料费", "收费"),
            ("先交体检费", "收费"),
            ("需交工本费", "收费"),
            ("这是招转培", "招转培"),
            ("兼职返利", "刷单返利"),
            ("高额返佣", "刷单返利"),
            ("绑定银行卡", "盗刷"),
            ("提供验证码", "盗刷"),
            ("下载招聘APP试岗", "盗刷"),
            ("下载APP 试岗", "盗刷"),
            ("扣押身份证", "扣证件"),
            ("入职押身份证", "扣证件"),
        )
        for text, category in cases:
            with self.subTest(text=text):
                found = {item["category"] for item in cn_jd_check.check_jd(text)["scam"]}
                self.assertIn(category, found)

    def test_plain_fixtures_still_have_no_scam(self):
        for name in ("jd1_campus", "jd3_social", "jd5_foreign"):
            with self.subTest(name=name):
                self.assertEqual(self.check(name)["scam"], [])


if __name__ == "__main__":
    unittest.main()
