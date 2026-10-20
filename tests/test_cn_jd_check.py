"""tools/cn_jd_check.py screens a hand-pasted Chinese JD.

Hard filters (degree, school tier, age, city, hukou, salary) come from
config/cn_filters.json when that file exists, otherwise the example file.
Example thresholds are hints: those fails become flags. Jargon lowers the
score. Scam phrases reject. The tool never fetches, greets, or applies.
Numbers in the example config and in these JDs are fictional.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "cn_jd_check.py"
EXAMPLE = REPO / "config" / "cn_filters.example.json"

sys.path.insert(0, str(REPO / "tools"))
import cn_jd_check  # noqa: E402


CLEAN = """\
示意科技招聘后端工程师（虚构）
工作地点：杭州
薪资：15-25K·14薪
学历：本科及以上
岗位职责：
1. 负责内部接口开发
任职要求：
1. 本科及以上
2. 双休
"""

JARGON = "抗压能力强，大小周，996，base+期权，狼性，弹性工作制"

SCAM_NEGATED = """\
工作地点：杭州
薪资：20-30K·14薪
学历：本科
户口不限，不收取任何押金，拒绝刷单，谨防虚假招聘，无培训贷，不收费入职。
拒绝996，不接受大小周。
"""


def _row(report, name):
    return next(item for item in report["hard_filters"] if item["name"] == name)


def _write_filters(directory, data=None) -> Path:
    """A non-example config file. Passing it keeps hard fails (source custom)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "filters.json"
    payload = data if data is not None else EXAMPLE.read_text(encoding="utf-8")
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


REJECT = """\
示意科技（虚构）
工作地点：成都
年龄：18-25岁
学历：硕士及以上
任职要求：985/211院校
薪资：8-12K·12薪
需本地户口
"""


class CheckJd(unittest.TestCase):
    def test_example_config_shape_and_clean_jd_passes(self):
        filters = cn_jd_check.load_filters()
        self.assertEqual(filters["degree"]["candidate"], "bachelor")
        self.assertEqual(filters["school_tier"]["candidate_tiers"], [])
        self.assertEqual(filters["age"]["candidate"], 28)
        self.assertIn("杭州", filters["city"]["accept"])
        self.assertEqual(filters["hukou"]["has"], [])
        self.assertTrue(filters["hukou"]["reject_if_required"])
        self.assertEqual(filters["salary"]["min_monthly_k"], 20)
        self.assertEqual(filters["salary"]["min_months"], 13)

        report = cn_jd_check.check_jd(CLEAN)
        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["score"], 100)
        self.assertFalse(report["hard_fail"])
        self.assertFalse(report["scam_fail"])
        self.assertEqual(report["jargon"], [])
        self.assertEqual(report["scam"], [])
        self.assertEqual(_row(report, "degree")["status"], "pass")
        self.assertEqual(_row(report, "city")["status"], "pass")
        self.assertEqual(_row(report, "salary")["status"], "pass")
        self.assertEqual(_row(report, "school_tier")["status"], "unknown")
        self.assertIn("Does not scrape", report["note"])
        self.assertEqual(report["thresholds_source"], "example")
        self.assertEqual(report["warning"], cn_jd_check.EXAMPLE_WARNING)

    def test_salary_15_25k_14_months_and_other_shapes(self):
        parsed = cn_jd_check.parse_salary("薪资：15-25K·14薪")
        self.assertEqual(parsed["min_monthly_k"], 15)
        self.assertEqual(parsed["max_monthly_k"], 25)
        self.assertEqual(parsed["months"], 14)
        self.assertEqual(parsed["evidence"], "15-25K·14薪")
        self.assertFalse(parsed["annual"])

        spaced = cn_jd_check.parse_salary("15-25K * 14薪")
        self.assertEqual(spaced["months"], 14)
        self.assertEqual(spaced["max_monthly_k"], 25)

        wan = cn_jd_check.parse_salary("月薪1.5-2.5万/月")
        self.assertEqual(wan["min_monthly_k"], 15)
        self.assertEqual(wan["max_monthly_k"], 25)
        self.assertFalse(wan["annual"])

        annual = cn_jd_check.parse_salary("年薪20-40万")
        self.assertTrue(annual["annual"])
        self.assertEqual(annual["min_monthly_k"], 16.67)
        self.assertEqual(annual["max_monthly_k"], 33.33)

        self.assertEqual(cn_jd_check.parse_salary("薪资面议")["evidence"], "面议")
        self.assertIsNone(cn_jd_check.parse_salary("薪资面议")["max_monthly_k"])

    def test_thresholds_come_from_config_not_hardcoded(self):
        report = cn_jd_check.check_jd("工作地点：杭州\n薪资：15-25K·14薪\n学历：本科\n")
        self.assertEqual(_row(report, "salary")["status"], "pass")
        self.assertEqual(report["thresholds"]["min_monthly_k"], 20)

        strict = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        strict["salary"] = {"min_monthly_k": 30, "min_months": 13}
        failed = cn_jd_check.check_jd("工作地点：杭州\n薪资：15-25K·14薪\n学历：本科\n", strict)
        self.assertEqual(_row(failed, "salary")["status"], "fail")
        self.assertIn("salary_below_floor", _row(failed, "salary")["codes"])

        months = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        months["salary"] = {"min_monthly_k": 15, "min_months": 15}
        short = cn_jd_check.check_jd("薪资：15-25K·14薪", months)
        self.assertIn("salary_months_below_floor", _row(short, "salary")["codes"])

        master = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        master["degree"] = {"candidate": "硕士", "reject_if_required_above": True}
        raised = cn_jd_check.check_jd("学历：硕士及以上", master)
        self.assertEqual(_row(raised, "degree")["status"], "pass")
        self.assertEqual(raised["parsed"]["degree"]["required"], "master")

    def test_hard_filters_reject_degree_school_age_city_hukou_salary(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = _write_filters(tmp)
            report = cn_jd_check.check_jd(REJECT, config_path=custom)
        self.assertEqual(report["thresholds_source"], "custom")
        self.assertNotIn("warning", report)
        self.assertEqual(report["verdict"], "reject")
        self.assertTrue(report["hard_fail"])
        self.assertFalse(report["scam_fail"])
        failed = {row["name"] for row in report["hard_filters"] if row["status"] == "fail"}
        self.assertEqual(failed, {"degree", "school_tier", "age", "city", "hukou", "salary"})
        self.assertEqual(report["parsed"]["degree"]["required"], "master")
        self.assertEqual(report["parsed"]["school_tier"]["required"], ["985", "211"])
        self.assertEqual(report["parsed"]["age"], {"min": 18, "max": 25, "evidence": "18-25岁"})
        self.assertEqual(report["parsed"]["cities"], ["成都"])
        self.assertIn("salary_below_floor", _row(report, "salary")["codes"])
        self.assertIn("salary_months_below_floor", _row(report, "salary")["codes"])
        self.assertIn("hukou_required", _row(report, "hukou")["codes"])

    def test_age_cap_city_alias_and_school_preference(self):
        under = cn_jd_check.check_jd("年龄35岁以下\n工作地点：杭州市\n薪资：20-30K·14薪\n学历：本科")
        self.assertEqual(_row(under, "age")["status"], "pass")
        self.assertEqual(under["parsed"]["age"]["max"], 35)
        self.assertEqual(_row(under, "city")["status"], "pass")

        with tempfile.TemporaryDirectory() as tmp:
            capped = cn_jd_check.check_jd("年龄不超过27周岁", config_path=_write_filters(tmp))
        self.assertEqual(capped["thresholds_source"], "custom")
        self.assertEqual(_row(capped, "age")["status"], "fail")
        self.assertEqual(capped["parsed"]["age"]["max"], 27)

        preferred = cn_jd_check.check_jd("工作地点：上海\n薪资：25-40K·15薪\n学历：本科及以上\n985/211优先")
        self.assertEqual(_row(preferred, "school_tier")["status"], "flag")
        self.assertEqual(preferred["parsed"]["school_tier"]["mode"], "preferred")
        self.assertFalse(preferred["hard_fail"])
        self.assertEqual(preferred["verdict"], "caution")

        owned = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        owned["school_tier"] = {"candidate_tiers": ["211"], "reject_if_required": True}
        self.assertEqual(_row(cn_jd_check.check_jd("要求211院校", owned), "school_tier")["status"], "pass")
        self.assertEqual(_row(cn_jd_check.check_jd("仅限985", owned), "school_tier")["status"], "fail")
        owned["school_tier"] = {"candidate_tiers": ["985"], "reject_if_required": True}
        self.assertEqual(_row(cn_jd_check.check_jd("双一流院校", owned), "school_tier")["status"], "pass")

    def test_jargon_penalties_do_not_stack_overlaps(self):
        report = cn_jd_check.check_jd(JARGON)
        phrases = {item["phrase"]: item["penalty"] for item in report["jargon"]}
        self.assertEqual(phrases, {
            "抗压能力强": 8,
            "大小周": 15,
            "996": 20,
            "base+期权": 10,
            "狼性": 12,
            "弹性工作制": 6,
        })
        self.assertEqual(report["jargon_penalty"], 71)
        self.assertEqual(report["score"], 29)
        self.assertEqual(report["verdict"], "caution")
        self.assertFalse(report["hard_fail"])

        stacked = cn_jd_check.check_jd("狼性文化，弹性工作制，抗压能力强，Base + 期权")
        stacked_phrases = [item["phrase"] for item in stacked["jargon"]]
        self.assertEqual(stacked_phrases.count("狼性"), 0)
        self.assertIn("狼性文化", stacked_phrases)
        self.assertNotIn("弹性工作", stacked_phrases)
        self.assertIn("base+期权", stacked_phrases)
        self.assertNotIn("抗压能力", stacked_phrases)

        cleared = cn_jd_check.check_jd("拒绝996，不接受大小周，双休")
        self.assertEqual(cleared["jargon"], [])
        self.assertEqual(cleared["score"], 100)

        # 1996 must not be read as 996.
        self.assertEqual(cn_jd_check.check_jd("公司成立于1996年")["jargon"], [])

    def test_scam_categories_and_negation(self):
        jd = "入职需缴纳培训贷与押金，收费入职，兼职刷单，此为虚假招聘。"
        report = cn_jd_check.check_jd(jd)
        self.assertEqual(
            {item["category"] for item in report["scam"]},
            {"虚假招聘", "培训贷", "收费入职", "押金", "刷单"},
        )
        self.assertTrue(report["scam_fail"])
        self.assertEqual(report["verdict"], "reject")
        self.assertEqual(report["score"], 0)

        clean = cn_jd_check.check_jd(SCAM_NEGATED)
        self.assertEqual(clean["scam"], [])
        self.assertFalse(clean["scam_fail"])
        self.assertEqual(clean["jargon"], [])

        # A futures desk talking about margin is not an onboarding deposit.
        desk = cn_jd_check.check_jd("负责保证金风控和结算")
        self.assertEqual(desk["scam"], [])
        paid = cn_jd_check.check_jd("入职前需缴纳保证金")
        self.assertEqual(paid["scam"], [{"category": "押金", "phrase": "保证金"}])

    def test_empty_jd(self):
        report = cn_jd_check.check_jd("  \n")
        self.assertTrue(report["empty"])
        self.assertEqual(report["verdict"], "empty")
        self.assertFalse(report["ok"])
        self.assertFalse(report["hard_fail"])

    def test_cli_file_stdin_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jd.txt"
            path.write_text(CLEAN, encoding="utf-8")
            code, out, err = _run(["--in", str(path)])
            self.assertEqual(code, 0, err)
            self.assertEqual(err, "")
            report = json.loads(out)
            self.assertEqual(report["verdict"], "pass")
            self.assertEqual(report["parsed"]["salary"]["months"], 14)
            self.assertIn("15-25K·14薪", report["parsed"]["salary"]["evidence"])

            code, out, err = _run(["--config", str(EXAMPLE)], stdin=CLEAN)
            self.assertEqual(code, 0, err)
            example_clean = json.loads(out)
            self.assertEqual(example_clean["thresholds"]["age"], 28)
            self.assertEqual(example_clean["thresholds_source"], "example")
            self.assertEqual(example_clean["warning"], cn_jd_check.EXAMPLE_WARNING)

            custom = _write_filters(tmp)
            code, out, err = _run(["--config", str(custom)], stdin="年龄不超过27周岁\n")
            self.assertEqual(code, 0, err)
            custom_report = json.loads(out)
            self.assertEqual(custom_report["thresholds_source"], "custom")
            self.assertTrue(custom_report["hard_fail"])
            self.assertEqual(_row(custom_report, "age")["status"], "fail")
            self.assertNotIn("warning", custom_report)

            code, out, err = _run(["--config", str(EXAMPLE)], stdin="年龄不超过27周岁\n")
            self.assertEqual(code, 0, err)
            example_age = json.loads(out)
            self.assertEqual(example_age["thresholds_source"], "example")
            self.assertFalse(example_age["hard_fail"])
            self.assertEqual(_row(example_age, "age")["status"], "flag")
            self.assertEqual(example_age["warning"], cn_jd_check.EXAMPLE_WARNING)

            # Default config is next to the repo, not the process cwd.
            code, out, err = _run(["--in", str(path)], cwd="/tmp")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["verdict"], "pass")

            missing = Path(tmp) / "missing.txt"
            code, out, err = _run(["--in", str(missing)])
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("cannot read", err)

            code, out, err = _run(["--in", str(path), "--config", str(Path(tmp) / "no.json")])
            self.assertEqual(code, 2)
            self.assertIn("no.json", err)

            code, _out, err = _run(["--in", str(path), str(path)])
            self.assertEqual(code, 2)
            self.assertIn("not both", err)

    def test_cli_utf8_when_stdout_encoding_is_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jd.txt"
            path.write_text("工作地点：杭州\n学历：本科\n", encoding="utf-8")
            env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
            proc = subprocess.run(
                [sys.executable, str(TOOL), "--in", str(path)],
                capture_output=True,
                env=env,
            )
        self.assertNotIn(b"UnicodeEncodeError", proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        text = proc.stdout.decode("utf-8")
        self.assertIn("杭州", text)
        self.assertEqual(json.loads(text)["parsed"]["cities"], ["杭州"])

    def test_stdlib_only_and_does_not_fetch(self):
        source = TOOL.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
        self.assertTrue(modules)
        self.assertTrue(modules <= sys.stdlib_module_names)
        for banned in ("requests", "urllib", "http", "socket", "subprocess", "scrapy"):
            self.assertNotIn(banned, modules)
        self.assertIn("Pasted JD only", source)

    def test_example_comment_and_gitignore_point_at_user_config(self):
        comment = json.loads(EXAMPLE.read_text(encoding="utf-8"))["_comment"]
        self.assertIn("config/cn_filters.json", comment)
        rules = {
            line.strip()
            for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        self.assertIn("config/cn_filters.json", rules)
        self.assertNotIn("config/cn_filters.example.json", rules)

    def test_thresholds_source_user_example_and_custom(self):
        """User file hard-fails. A missing user file, or an explicit example
        path, is source example and downgrades those fails to flags."""
        warning = "未找到 config/cn_filters.json，使用示例阈值，仅作提示"
        self.assertEqual(cn_jd_check.EXAMPLE_WARNING, warning)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            user_data["age"] = {"candidate": 41}
            user = _write_filters(root / "user", user_data)
            example_data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            example_data["age"] = {"candidate": 99}
            example_copy = _write_filters(root / "example", example_data)
            custom = _write_filters(root / "custom")
            missing = root / "absent" / "cn_filters.json"

            with mock.patch.object(cn_jd_check, "USER_CONFIG", user), \
                 mock.patch.object(cn_jd_check, "EXAMPLE_CONFIG", example_copy):
                loaded = cn_jd_check.load_filters()
                self.assertEqual(loaded["age"]["candidate"], 41)
                report = cn_jd_check.check_jd(REJECT)
                self.assertEqual(report["thresholds_source"], "user")
                self.assertEqual(report["thresholds"]["age"], 41)
                self.assertNotIn("warning", report)
                self.assertTrue(report["hard_fail"])
                self.assertEqual(report["verdict"], "reject")
                failed = {row["name"] for row in report["hard_filters"] if row["status"] == "fail"}
                self.assertEqual(
                    failed, {"degree", "school_tier", "age", "city", "hukou", "salary"}
                )

                via_user = cn_jd_check.check_jd(REJECT, config_path=user)
                self.assertEqual(via_user["thresholds_source"], "user")
                self.assertTrue(via_user["hard_fail"])

                via_example = cn_jd_check.check_jd(REJECT, config_path=example_copy)
                self.assertEqual(via_example["thresholds_source"], "example")
                self.assertEqual(via_example["thresholds"]["age"], 99)
                self.assertFalse(via_example["hard_fail"])
                self.assertEqual(via_example["warning"], warning)
                alias = example_copy.parent / "." / example_copy.name
                via_alias = cn_jd_check.check_jd(REJECT, config_path=alias)
                self.assertEqual(via_alias["thresholds_source"], "example")
                self.assertFalse(via_alias["hard_fail"])

                via_custom = cn_jd_check.check_jd(REJECT, config_path=custom)
                self.assertEqual(via_custom["thresholds_source"], "custom")
                self.assertTrue(via_custom["hard_fail"])
                self.assertNotIn("warning", via_custom)
                self.assertEqual(
                    {row["name"] for row in via_custom["hard_filters"] if row["status"] == "fail"},
                    {"degree", "school_tier", "age", "city", "hukou", "salary"},
                )

            with mock.patch.object(cn_jd_check, "USER_CONFIG", missing), \
                 mock.patch.object(cn_jd_check, "EXAMPLE_CONFIG", example_copy):
                self.assertFalse(missing.exists())
                fallback = cn_jd_check.check_jd(REJECT)
                self.assertEqual(fallback["thresholds_source"], "example")
                self.assertEqual(fallback["thresholds"]["age"], 99)
                self.assertFalse(fallback["hard_fail"])
                self.assertEqual(fallback["verdict"], "caution")
                self.assertEqual(fallback["warning"], warning)
                self.assertEqual(
                    {row["name"] for row in fallback["hard_filters"] if row["status"] == "fail"},
                    set(),
                )
                for name in ("degree", "school_tier", "age", "city", "hukou", "salary"):
                    self.assertEqual(_row(fallback, name)["status"], "flag")
                self.assertIn("city_not_accepted", _row(fallback, "city")["codes"])
                self.assertIn("salary_below_floor", _row(fallback, "salary")["codes"])
                self.assertIn("hukou_required", _row(fallback, "hukou")["codes"])


class LaborCheck(unittest.TestCase):
    def check(self, text, filters=None):
        return cn_jd_check.check_jd(text, filters={} if filters is None else filters)

    def hits(self, report, name):
        return [hit for hit in report["labor"] if hit["name"] == name]

    def test_probation_months_boundaries_and_chinese_units(self):
        for text, months, status in (
            ("试用期1个月", None, None),
            ("试用期两个月", None, None),
            ("试用期为三个月", None, None),
            ("试用期半个月", None, None),
            ("试用期一个半月", None, None),
            ("试用期4个月", 4, "info"),
            ("试用期三个月半", 3.5, "info"),
            ("试用期：6个月", 6, "info"),
            ("试用期半年", 6, "info"),
            ("试用期限为六个月", 6, "info"),
            ("试用期６个月", 6, "info"),
            ("试用期6.5个月", 6.5, "flag"),
            ("试用期六个半月", 6.5, "flag"),
            ("试用期七个月", 7, "flag"),
            ("试用期一年", 12, "flag"),
            ("试用期为期十二个月", 12, "flag"),
            ("试用期一年半", 18, "flag"),
            ("试用期两年", 24, "flag"),
        ):
            with self.subTest(text=text):
                report = self.check(text)
                hits = self.hits(report, "probation_months")
                if months is None:
                    self.assertEqual(hits, [])
                    self.assertEqual(report["verdict"], "pass")
                else:
                    self.assertEqual(len(hits), 1)
                    self.assertEqual(hits[0]["value"], months)
                    self.assertEqual(hits[0]["status"], status)
                    self.assertEqual(report["verdict"], "caution")
                self.assertFalse(report["hard_fail"])
                self.assertEqual(report["labor_penalty"], 6 if status == "flag" else 0)

    def test_long_probation_is_flagged_even_with_long_contract(self):
        report = self.check("签订三年以上劳动合同，试用期一年")
        self.assertEqual(self.hits(report, "probation_months")[0]["status"], "flag")
        self.assertEqual(report["verdict"], "caution")

    def test_probation_pay_below_eighty(self):
        for text, ratio in (
            ("试用期工资七折", 70),
            ("试用期薪资打7折", 70),
            ("试用期打七五折", 75),
            ("试用期打7.5折", 75),
            ("试用期工资79.9%", 79.9),
            ("试用期工资为工资的70%", 70),
            ("试用期按转正工资的７０％发放", 70),
            ("试用期工资为百分之七十", 70),
            ("试用期间工资70%", 70),
            ("试用期6个月，打七折", 70),
            ("试用期6个月，工资的70%", 70),
        ):
            with self.subTest(text=text):
                report = self.check(text)
                hit = self.hits(report, "probation_pay_ratio")[0]
                self.assertEqual(hit["value"], ratio)
                self.assertEqual(hit["status"], "flag")
                self.assertEqual(report["labor_penalty"], 6)
                self.assertEqual(report["score"], 94)
                self.assertEqual(report["verdict"], "caution")

    def test_eighty_percent_and_other_percentages_are_not_flags(self):
        for text in (
            "试用期工资八折", "试用期打8折", "试用期工资80%",
            "试用期工资为工资的80%", "试用期工资百分之八十",
            "试用期工资100%", "试用期工资打九折", "试用期工资８０％",
            "试用期2个月，绩效占工资的70%", "试用期项目完成率70%",
            "试用期1个月。转正后工资的70%为基本工资",
            "试用期1个月；转正后工资的70%为基本工资",
            "试用期1个月\n转正后工资的70%为基本工资",
            "试用期1个月，转正后工资的70%为基本工资",
            "试用期1个月，工资20K，转正后工资的70%为基本工资",
            "正式工资打七折", "一年合同，月薪20K",
        ):
            with self.subTest(text=text):
                report = self.check(text)
                self.assertEqual(report["labor"], [])
                self.assertEqual(report["labor_penalty"], 0)
                self.assertEqual(report["verdict"], "pass")

    def test_social_insurance_risks(self):
        for text, code in (
            ("五险一金按最低基数缴纳", "insurance_minimum_base"),
            ("按最低标准缴纳社保", "insurance_minimum_base"),
            ("五险一金最低标准缴纳", "insurance_minimum_base"),
            ("五险一金按最低基数", "insurance_minimum_base"),
            ("转正后缴五险一金", "insurance_after_probation"),
            ("转正后才缴纳五险一金", "insurance_after_probation"),
            ("转正后购买五险一金", "insurance_after_probation"),
            ("转正后才购买社保", "insurance_after_probation"),
            ("试用期不缴社保", "insurance_unpaid_probation"),
            ("试用期不买社保", "insurance_unpaid_probation"),
            ("试用期间不交五险一金", "insurance_unpaid_probation"),
            ("自愿放弃社保", "insurance_waived"),
            ("自愿放弃社会保险", "insurance_waived"),
            ("不交公积金", "housing_fund_unpaid"),
            ("不缴纳住房公积金", "housing_fund_unpaid"),
        ):
            with self.subTest(text=text):
                report = self.check(text)
                hits = self.hits(report, "social_insurance")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["status"], "flag")
                self.assertEqual(hits[0]["codes"], [code])
                self.assertEqual(report["labor_penalty"], 6)
                self.assertFalse(report["hard_fail"])
                self.assertFalse(report["scam_fail"])
                self.assertEqual(report["verdict"], "caution")

    def test_positive_benefits_do_not_deduct_or_trigger_caution(self):
        report = self.check("六险二金，社保全额缴纳，按实际工资缴纳，补充公积金")
        self.assertEqual(len(report["labor"]), 4)
        for hit in report["labor"]:
            self.assertEqual(hit["status"], "info")
            self.assertFalse(hit["risk"])
            self.assertEqual(hit["codes"], ["insurance_positive"])
        self.assertEqual(_row(report, "labor")["status"], "info")
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["labor_penalty"], 0)

    def test_negation_suppresses_risks_and_positive_claims(self):
        for text in (
            "拒绝试用期一年", "并非试用期七个月", "不是试用期工资七折",
            "试用期工资不打七折", "试用期工资不是70%",
            "不按最低基数缴纳", "拒绝按最低标准缴纳",
            "并非最低标准缴纳",
            "并非转正后才缴纳五险一金", "禁止试用期不缴社保",
            "不要自愿放弃社保", "杜绝不交公积金",
            "不以实习协议代替劳动合同", "严禁不签劳动合同",
            "并非人力外包", "非劳务派遣", "不驻场", "不是派遣制",
            "不提供六险二金", "无补充公积金", "并非全额缴纳",
            "不是按实际工资缴纳",
        ):
            with self.subTest(text=text):
                report = self.check(text)
                self.assertEqual(report["labor"], [])
                self.assertEqual(_row(report, "labor")["status"], "unknown")
                self.assertEqual(report["score"], 100)
                self.assertEqual(report["verdict"], "pass")

    def test_negated_occurrence_does_not_hide_a_later_risk(self):
        report = self.check("不按最低基数缴纳。另一岗位按最低基数缴纳")
        self.assertEqual(len(report["labor"]), 1)
        self.assertEqual(report["labor"][0]["status"], "flag")
        mixed = self.check("六险二金，不交公积金")
        self.assertEqual({hit["status"] for hit in mixed["labor"]}, {"flag", "info"})
        self.assertEqual(mixed["verdict"], "caution")

    def test_outsourcing_is_information_with_no_deduction(self):
        for text in ("外包", "驻场", "劳务派遣", "人力外包", "派遣制"):
            with self.subTest(text=text):
                report = self.check(text)
                hits = self.hits(report, "outsourcing")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["status"], "info")
                self.assertEqual(report["verdict"], "caution")
                self.assertEqual(report["score"], 100)
                self.assertEqual(report["labor_penalty"], 0)

    def test_contract_risks_and_student_context(self):
        for text in ("不签合同", "不签劳动合同", "不签订书面劳动合同", "以实习协议代替劳动合同"):
            with self.subTest(text=text):
                report = self.check(text)
                self.assertEqual(self.hits(report, "contract")[0]["status"], "flag")
                self.assertEqual(report["labor_penalty"], 6)
                self.assertEqual(report["verdict"], "caution")
        student_text = "仅招在校生，以实习协议代替劳动合同"
        student = self.check(student_text)
        self.assertEqual(self.hits(student, "contract")[0]["status"], "info")
        self.assertEqual(student["labor_penalty"], 0)
        explicit_student = self.check("不签劳动合同", {"labor": {"candidate_is_student": True}})
        self.assertEqual(self.hits(explicit_student, "contract")[0]["status"], "info")
        non_student = self.check(student_text, {"labor": {"candidate_is_student": False}})
        self.assertEqual(self.hits(non_student, "contract")[0]["status"], "flag")
        negated_student = self.check("非在校生，不签劳动合同")
        self.assertEqual(self.hits(negated_student, "contract")[0]["status"], "flag")

    def test_labor_config_validation_and_legacy_config(self):
        self.assertEqual(self.check("双休", {})["labor"], [])
        self.assertEqual(self.check("双休", {"labor": None})["labor"], [])
        for value in ("false", 0, 1, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "candidate_is_student"):
                    self.check("双休", {"labor": {"candidate_is_student": value}})
        with tempfile.TemporaryDirectory() as tmp:
            config = _write_filters(tmp, {"labor": []})
            with self.assertRaisesRegex(ValueError, "labor must be a JSON object"):
                cn_jd_check.load_filters(config)
            config = _write_filters(tmp, {"labor": {"candidate_is_student": "true"}})
            with self.assertRaisesRegex(ValueError, "candidate_is_student"):
                cn_jd_check.load_filters(config)

    def test_report_jd3_and_summary_row(self):
        report = self.check("试用期6个月，打八折，五险一金按最低基数缴纳")
        self.assertEqual({hit["name"] for hit in report["labor"]}, {"probation_months", "social_insurance"})
        self.assertEqual(_row(report, "labor")["status"], "flag")
        self.assertIn("probation_check_contract_term", _row(report, "labor")["codes"])
        self.assertIn("insurance_minimum_base", _row(report, "labor")["codes"])
        self.assertEqual(report["score"], 94)
        self.assertEqual(report["verdict"], "caution")
        self.assertFalse(report["hard_fail"])
        self.assertFalse(report["scam_fail"])
        self.assertFalse(report["ok"])

    def test_penalty_per_dimension_and_never_rejects(self):
        text = "试用期一年，试用期工资七折，转正后才缴五险一金，不交公积金，不签劳动合同"
        for filters in ({}, cn_jd_check.load_filters()):
            with self.subTest(filters=filters):
                report = self.check(text, filters)
                self.assertEqual(report["labor_penalty"], 24)
                self.assertEqual(report["score"], 76)
                self.assertEqual(report["verdict"], "caution")
                self.assertFalse(report["hard_fail"])
                self.assertFalse(report["scam_fail"])
        repeated = self.check("试用期一年，试用期七个月，试用期一年")
        self.assertEqual(repeated["labor_penalty"], 6)
        self.assertEqual(repeated["score"], 94)
        many = self.check("，".join(["试用期一年"] * 30))
        self.assertEqual(many["verdict"], "caution")
        self.assertEqual(many["labor_penalty"], 6)

    def test_existing_penalties_and_rejections_still_apply(self):
        jargon = self.check("狼性，试用期一年")
        self.assertEqual(jargon["score"], 82)
        self.assertEqual(jargon["jargon_penalty"], 12)
        self.assertEqual(jargon["labor_penalty"], 6)
        self.assertEqual(jargon["verdict"], "caution")
        hard = self.check("工作地点：成都，不签劳动合同", {"city": {"accept": ["北京"]}})
        self.assertTrue(hard["hard_fail"])
        self.assertEqual(hard["verdict"], "reject")
        scam = self.check("需缴纳押金，不签劳动合同")
        self.assertTrue(scam["scam_fail"])
        self.assertEqual(scam["verdict"], "reject")
        self.assertEqual(scam["score"], 64)
        clamped = self.check(JARGON + "，试用期一年，试用期工资七折，不签劳动合同，缴纳押金")
        self.assertEqual(clamped["score"], 0)

    def test_cli_labor_output_and_example_source(self):
        code, out, err = _run(["--config", str(EXAMPLE)], stdin="试用期一年，工资七折，不交公积金")
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        report = json.loads(out)
        self.assertEqual(report["thresholds_source"], "example")
        self.assertEqual(report["verdict"], "caution")
        self.assertEqual(_row(report, "labor")["status"], "flag")
        self.assertEqual(report["labor_penalty"], 18)
        self.assertEqual(report["score"], 82)

    def test_exact_supplied_legal_bases_and_hint_wording(self):
        bases = {
            "probation_months": "《劳动合同法》第十九条：劳动合同期限三个月以上不满一年的，试用期不得超过一个月；一年以上不满三年的，不得超过二个月；三年以上固定期限和无固定期限的，不得超过六个月；同一用人单位与同一劳动者只能约定一次试用期。",
            "probation_pay_ratio": "《劳动合同法》第二十条：试用期工资不得低于本单位相同岗位最低档工资或者劳动合同约定工资的百分之八十，并不得低于用人单位所在地的最低工资标准。",
            "contract": "《劳动合同法》第十条：建立劳动关系，应当订立书面劳动合同。",
            "outsourcing": "《劳动合同法》第五十九条（派遣单位与用工单位订立劳务派遣协议）、第六十六条（劳务派遣只能在临时性、辅助性或者替代性的工作岗位上实施）；《劳务派遣暂行规定》第四条（派遣用工数量不得超过其用工总量的10%）。",
            "social_insurance": "《社会保险法》第五十八条（用人单位应当自用工之日起三十日内为其职工申请办理社会保险登记）、第六十条（用人单位应当自行申报、按时足额缴纳社会保险费）；《住房公积金管理条例》第二十条（单位应当按时、足额缴存住房公积金）。",
        }
        report = self.check("试用期一年，试用期工资70%，不交公积金，六险二金，人力外包，不签劳动合同")
        self.assertEqual({hit["name"] for hit in report["labor"]}, set(bases))
        for hit in report["labor"]:
            self.assertEqual(hit["legal_basis"], bases[hit["name"]])
            self.assertIn("风险提示，非法律意见，以合同和当地人社部门解释为准", hit["detail"])
            self.assertIn(hit["evidence"], report["hard_filters"][-1]["evidence"])
            self.assertNotIn("违法", hit["detail"])
            self.assertIn(hit["status"], {"flag", "info"})
            self.assertIn(hit["legal_basis"], _row(report, "labor")["legal_basis"])
        self.assertEqual(self.check("")["labor"], [])
        self.assertEqual(self.check("")["verdict"], "empty")


def _run(argv, stdin=None, cwd=None):
    proc = subprocess.run(
        [sys.executable, str(TOOL), *argv],
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=cwd,
    )
    return proc.returncode, proc.stdout, proc.stderr


if __name__ == "__main__":
    unittest.main()
