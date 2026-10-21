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


class Item4Parsing(FixtureBase):
    def test_jd1_degree_word_before_the_label(self):
        # "统招全日制本科及以上学历" puts 本科 before 学历.
        report = self.check("jd1_campus")
        self.assertEqual(report["parsed"]["degree"]["required"], "bachelor")

    def test_jd2_base_city_without_a_colon(self):
        report = self.check("jd2_intern")
        self.assertIn("北京", report["parsed"]["cities"])

    def test_jd5_english_city_degree_and_months(self):
        report = self.check("jd5_foreign")
        self.assertIn("上海", report["parsed"]["cities"])
        self.assertEqual(report["parsed"]["degree"]["required"], "bachelor")
        self.assertEqual(report["parsed"]["salary"]["months"], 13)

    def test_base_location_and_english_degree_forms(self):
        known = cn_jd_check.BUILTIN_CITIES
        self.assertIn("北京", cn_jd_check.parse_cities("Base 北京海淀", known))
        self.assertIn("北京", cn_jd_check.parse_cities("base北京", known))
        self.assertIn("上海", cn_jd_check.parse_cities("Location: Shanghai", known))
        self.assertIn("上海", cn_jd_check.parse_cities("(Shanghai)", known))
        self.assertEqual(cn_jd_check.parse_degree("统招全日制本科及以上学历")["required"], "bachelor")
        far = "学历见附件。" + ("其他" * 30) + "须本科及以上"
        self.assertEqual(cn_jd_check.parse_degree(far)["required"], "bachelor")
        self.assertEqual(cn_jd_check.parse_degree("学历不限")["required"], "none")
        self.assertEqual(cn_jd_check.parse_degree("Bachelor's degree or above")["required"], "bachelor")
        self.assertEqual(cn_jd_check.parse_degree("Master's degree or above")["required"], "master")
        self.assertEqual(cn_jd_check.parse_degree("PhD")["required"], "doctor")
        self.assertEqual(cn_jd_check.parse_degree("Doctorate or above")["required"], "doctor")
        parsed = cn_jd_check.parse_salary("Salary: 40k-60k RMB/month, 13 months + bonus")
        self.assertEqual(parsed["months"], 13)


class Item6AgeCap(FixtureBase):
    def test_jd3_social_surfaces_the_cap(self):
        report = self.check("jd3_social")
        age = self.row(report, "age")
        self.assertIn("age_cap", age["codes"])
        self.assertEqual(age["status"], "flag")
        self.assertIn(
            "该岗位设有年龄上限（35岁）。与岗位无关的年龄限制可能涉嫌就业歧视，可拨打 12333 人社服务热线咨询或投诉。",
            report["notices"],
        )
        self.assertNotEqual(report["verdict"], "pass")

    def test_jd1_campus_names_the_hotline(self):
        report = self.check("jd1_campus")
        self.assertIn("age_cap", self.row(report, "age")["codes"])
        self.assertTrue(any("12333" in item for item in report["notices"]))
        self.assertNotEqual(report["verdict"], "pass")

    def test_jd5_foreign_has_no_age_cap_notice(self):
        report = self.check("jd5_foreign")
        self.assertNotIn("age_cap", self.row(report, "age")["codes"])
        self.assertFalse(any("12333" in item or "年龄上限" in item for item in report["notices"]))

    def test_labeled_range_without_sui_parses_max(self):
        parsed = cn_jd_check.parse_age("年龄：25-35")
        self.assertEqual(parsed["max"], 35)
        self.assertEqual(parsed["min"], 25)

    def test_about_and_within_are_caps(self):
        self.assertEqual(cn_jd_check.parse_age("30岁左右")["max"], 30)
        self.assertEqual(cn_jd_check.parse_age("35岁以内")["max"], 35)
        self.assertEqual(cn_jd_check.parse_age("35岁内")["max"], 35)
        about = cn_jd_check.check_jd("要求30岁左右", config_path=self.custom)
        self.assertEqual(about["parsed"]["age"]["max"], 30)
        self.assertIn("age_cap", self.row(about, "age")["codes"])
        self.assertTrue(any("12333" in item for item in about["notices"]))


if __name__ == "__main__":
    unittest.main()
