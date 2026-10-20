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
