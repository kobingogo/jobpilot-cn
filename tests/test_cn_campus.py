"""Campus/intern routing and scoring on fictional, hand-pasted JDs only."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import cn_jd_check as checker
from tests.test_cn_resume_template import _pdf_page_count, UNCOMMENTED_PHOTO, UNBRACED_BRACKET_ITEM

REPO = Path(__file__).resolve().parent.parent
CAMPUS = REPO / 'templates/cn/campus'


def read(path):
    return (REPO / path).read_text(encoding='utf-8')


def row(report, name):
    return next(r for r in report['hard_filters'] if r['name'] == name)


class CampusScoring(unittest.TestCase):
    def check(self, text, **sections):
        # Fictional thresholds, deliberately high monthly floor to catch unit confusion.
        filters = {'salary': {'min_monthly_k': 20, 'min_months': 14, 'min_daily': 200}}
        filters.update(sections)
        return checker.check_jd(text, filters)

    def test_daily_pay_formats_are_not_monthly(self):
        for text, low, high in (
            ('实习日薪200-300元/天', 200, 300),
            ('日薪：200-300元', 200, 300),
            ('实习薪资1000元/天', 1000, 1000),
            ('200元/日', 200, 200),
            ('日薪２００－３００元／天', 200, 300),
        ):
            with self.subTest(text=text):
                report = self.check(text)
                pay = report['parsed']['salary']
                self.assertEqual(pay['period'], 'day')
                self.assertEqual((pay['min_daily'], pay['max_daily']), (low, high))
                for key in ('min_monthly_k', 'max_monthly_k', 'months'):
                    self.assertIsNone(pay[key])
                self.assertEqual(row(report, 'salary')['status'], 'pass')
                self.assertFalse(report['hard_fail'])
                self.assertEqual(report['scam'], [])
                self.assertIn('元', pay['evidence'])

    def test_daily_floor_boundary_and_missing_threshold(self):
        below = self.check('实习100-199元/天')
        self.assertEqual(row(below, 'salary')['codes'], ['salary_daily_below_floor'])
        self.assertTrue(below['hard_fail'])
        boundary = self.check('实习150-200元/天')
        self.assertEqual(row(boundary, 'salary')['status'], 'pass')
        unknown = self.check('实习1000元/天', salary={'min_monthly_k': 20})
        self.assertEqual(row(unknown, 'salary')['status'], 'unknown')
        self.assertFalse(unknown['hard_fail'])

    def test_monthly_annual_hourly_and_mixed_are_separate(self):
        for text, period, status in (('校招20-30K·14薪', 'month', 'pass'),
                                     ('校招年薪30-40万', 'year', 'flag')):
            report = self.check(text)
            self.assertEqual(report['parsed']['salary']['period'], period)
            self.assertEqual(row(report, 'salary')['status'], status)
        hourly = self.check('实习1000元/小时')
        self.assertEqual(hourly['parsed']['salary']['period'], 'hour')
        self.assertEqual(hourly['parsed']['salary']['min_hourly'], 1000)
        self.assertEqual(row(hourly, 'salary')['status'], 'unknown')
        mixed = self.check('实习200元/天或30元/小时')
        self.assertEqual(mixed['parsed']['salary']['period'], 'mixed')
        self.assertEqual(row(mixed, 'salary')['status'], 'unknown')

    def test_auto_mode_and_explicit_override_do_not_infer_student(self):
        for text, mode in (('校园招聘', 'campus'), ('应届毕业生', 'campus'), ('2027届', 'campus'),
                           ('后端实习', 'intern'), ('招在校生', 'campus'), ('社招工程师', 'experienced')):
            with self.subTest(text=text):
                report = self.check(text)
                self.assertEqual(report['parsed']['campus']['mode'], mode)
                self.assertEqual(row(report, 'student_status')['status'], 'unknown')
        for mode in ('campus', 'intern', 'experienced'):
            report = self.check('实习', campus={'mode': mode})
            self.assertEqual(report['parsed']['campus']['mode'], mode)
            self.assertIsNone(report['thresholds']['candidate_is_student'])

    def test_student_status_requires_confirmed_profile(self):
        for status, expected in ((True, 'pass'), (False, 'fail'), (None, 'unknown')):
            with self.subTest(status=status):
                report = self.check('仅招在校硕士研究生，实习200-300元/天',
                                    labor={'candidate_is_student': status})
                self.assertEqual(row(report, 'student_status')['status'], expected)
                self.assertNotEqual(row(report, 'degree')['status'], 'fail')
        for text in ('在校生', '在读本科', '在校大学生', '在读大学生'):
            self.assertTrue(self.check(text)['parsed']['campus']['student_required'])
        for text in ('非在校生', '不限在校生身份'):
            self.assertFalse(self.check(text)['parsed']['campus']['student_required'])

    def test_cohort_single_short_multi_range_and_unknown(self):
        for text, years in (('2027届应届毕业生', [2027]), ('27届实习生', [2027]),
                            ('面向2026-2028届', [2026, 2027, 2028]),
                            ('2026届/2027届', [2026, 2027]), ('26、28届', [2026, 2028])):
            with self.subTest(text=text):
                report = self.check(text, campus={'graduation_year': 2027})
                self.assertEqual(report['parsed']['campus']['graduation_years'], years)
                self.assertEqual(row(report, 'graduation_year')['status'], 'pass' if 2027 in years else 'fail')
        missing = self.check('2027届应届毕业生')
        self.assertEqual(row(missing, 'graduation_year')['status'], 'unknown')
        # No automatic current-year or enrollment assumption.
        unspecific = self.check('应届毕业生', campus={'graduation_year': 2025})
        self.assertEqual(row(unspecific, 'graduation_year')['status'], 'unknown')
        self.assertFalse(self.check('非2027届')['parsed']['campus']['graduation_years'])

    def test_preferred_student_and_cohort_are_hints_not_vetoes(self):
        report = self.check('在校生优先；2027届优先', campus={'graduation_year': 2026},
                            labor={'candidate_is_student': False})
        self.assertEqual(row(report, 'student_status')['status'], 'flag')
        self.assertEqual(row(report, 'graduation_year')['status'], 'flag')
        self.assertFalse(report['hard_fail'])
        self.assertEqual(report['verdict'], 'caution')

    def test_contract_uses_existing_student_status_not_campus_mode(self):
        text = '实习，以实习协议代替劳动合同'
        for student, status, penalty in ((True, 'info', 0), (False, 'flag', 6), (None, 'flag', 6)):
            with self.subTest(student=student):
                report = self.check(text, campus={'mode': 'intern'}, labor={'candidate_is_student': student})
                contract = next(hit for hit in report['labor'] if hit['name'] == 'contract')
                self.assertEqual(contract['status'], status)
                self.assertEqual(report['labor_penalty'], penalty)
                self.assertFalse(report['hard_fail'])
                self.assertNotEqual(report['verdict'], 'reject')
        student_jd = self.check('仅招在校生，以实习协议代替劳动合同')
        self.assertEqual(student_jd['labor'][0]['status'], 'info')
        self.assertEqual(row(student_jd, 'student_status')['status'], 'unknown')
        self.assertEqual(self.check('实习生签实习协议', labor={'candidate_is_student': True})['labor'], [])

    def test_labor_only_risks_never_reject_campus_student(self):
        report = self.check('实习，试用期7个月，工资打七折，转正后才缴社保，不签劳动合同',
                            campus={'mode': 'intern'}, labor={'candidate_is_student': True})
        self.assertFalse(report['hard_fail'])
        self.assertEqual(report['verdict'], 'caution')
        self.assertTrue(all(hit['status'] in {'flag', 'info'} for hit in report['labor']))

    def test_example_misses_softened_and_config_legacy_validation(self):
        example = checker.load_filters(checker.EXAMPLE_CONFIG)
        self.assertEqual(example['campus']['mode'], 'auto')
        self.assertIn('min_daily', example['salary'])
        fictional = {**example, 'campus': {'graduation_year': 2026}, 'labor': {'candidate_is_student': False}}
        with mock.patch.object(checker, 'load_filters', return_value=fictional):
            report = checker.check_jd('仅招在校生，2027届，实习100元/天', config_path=checker.EXAMPLE_CONFIG)
        for name in ('salary', 'student_status', 'graduation_year'):
            self.assertEqual(row(report, name)['status'], 'flag')
        self.assertFalse(report['hard_fail'])
        self.assertEqual(report['thresholds_source'], 'example')
        legacy = checker.check_jd('20-30K·14薪', {'salary': {'min_monthly_k': 20, 'min_months': 14}})
        self.assertEqual(row(legacy, 'salary')['status'], 'pass')
        for value in ('2027', True, 27, 1999):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'graduation_year'):
                self.check('实习', campus={'graduation_year': value})
        for mode in ('typo', [], True):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'campus.mode'):
                self.check('实习', campus={'mode': mode})

    def test_cli_custom_config_student_daily_and_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'filters.json'
            path.write_text(json.dumps({'salary': {'min_daily': 200}, 'campus': {'mode': 'intern', 'graduation_year': 2027},
                                        'labor': {'candidate_is_student': True}}), encoding='utf-8')
            proc = subprocess.run([sys.executable, str(REPO / 'tools/cn_jd_check.py'), '--config', str(path)],
                                  input='2027届在校生，日薪200-300元，以实习协议代替劳动合同',
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report['thresholds_source'], 'custom')
        for name in ('salary', 'student_status', 'graduation_year'):
            self.assertEqual(row(report, name)['status'], 'pass')
        self.assertEqual(report['labor_penalty'], 0)
        self.assertFalse(report['hard_fail'])


class CampusCommandWiring(unittest.TestCase):
    def test_onboarding_records_route_on_all_paths_before_shortcut(self):
        setup = read('.claude/commands/setup.md')
        language_route = setup.split('### Language and career-stage routing', 1)[1].split('If `$ARGUMENTS` contains', 1)[0]
        for token in ('writes Chinese', '中文', 'CV language: English', 'explicit CV-language choice',
                      'Career stage: experienced / campus / intern', 'Student status: true / false / unknown',
                      'Graduation year', 'templates/cn/campus/resume.tex', 'ACTIVE-TEMPLATE', 'docs/cn/',
                      'Path A/B', 'no scraper', 'manually pasted JDs'):
            self.assertIn(token, language_route)
        settings = setup.split('### 8a.', 1)[1].split('### 9.', 1)[0]
        for token in ('config/cn_filters.json', 'campus.mode', 'campus.graduation_year',
                      'labor.candidate_is_student', 'salary.min_daily', 'confirmed thresholds only'):
            self.assertIn(token, settings)
        summary = setup.split('## Step 4:', 1)[1]
        self.assertIn('Do not show `/scrape`, a Danish URL', summary)
        for profile in ('CLAUDE.md', '.claude/skills/job-application-assistant/01-candidate-profile.md'):
            text = read(profile)
            for field in ('Career stage', 'Student status', 'Graduation year', 'Availability'):
                self.assertIn(f'**{field}:**', text)

    def test_chinese_quick_start_is_prominent_and_uses_this_fork(self):
        readme = read('README.md')
        self.assertLess(readme.index('[中文快速开始]'), readme.index('## Does it actually work?'))
        cn = readme.split('## 中文快速开始', 1)[1].split('## Quick start', 1)[0]
        for token in ('kobingogo/jobpilot-cn.git', '/setup 中文', 'CV language: 中文', 'texlive-lang-chinese',
                      'fonts-noto-cjk', '手工粘贴', 'templates/cn/campus/resume.tex', '不自动打招呼或投递'):
            self.assertIn(token, cn)
        self.assertNotIn('/scrape', cn)
        self.assertIn('## Quick start', readme)  # English instructions retained.
        guide = read('SETUP.md').split('## 中文路径', 1)[1].split('## 1.', 1)[0]
        self.assertIn('English', guide)
        self.assertIn('salary.min_daily', guide)

    def test_apply_selects_campus_only_within_chinese_route_and_custom_wins(self):
        apply = read('.claude/commands/apply.md')
        branch = apply.split('**Campus variant within the Chinese selection above:**', 1)[1].split('Also read', 1)[0]
        for token in ('Career stage: campus / intern', 'templates/cn/campus/resume.tex',
                      'education first', 'ACTIVE-TEMPLATE', 'exactly 1 page', '虚构'):
            self.assertIn(token, branch)
        self.assertIn('or `templates/cn/campus/resume.tex`) to this path', apply)
        for file in ('.claude/skills/job-application-assistant/04-job-evaluation.md', '.claude/agents/posting-scorer.md'):
            rubric = read(file)
            self.assertIn('Career stage: campus / intern', rubric)
            self.assertIn('projects', rubric)
            self.assertIn('internships', rubric)

    def test_interview_routing_and_student_guide_avoid_employer_script(self):
        command = read('.claude/commands/interview.md')
        for step in ('## Step 1:', '## Step 3:', '## Step 4:'):
            block = command.split(step, 1)[1].split('\n## ', 1)[0]
            self.assertIn('docs/cn/校招实习面试准备.md', block)
        campus = read('docs/cn/校招实习面试准备.md')
        for topic in ('群面', '无领导小组', '技术面', 'HR 面', '笔试', '测评', '三方协议', 'offer 比较', '实习转正', '违约金', '户口', '编制'):
            self.assertIn(topic, campus)
        self.assertIn('不是朗读台词', campus)
        self.assertNotIn('[YOUR_EMPLOYER]', campus)
        self.assertNotIn('目前在 [', campus)
        social = read('docs/cn/面试准备.md')
        self.assertIn('[校招实习面试准备](校招实习面试准备.md)', social)
        self.assertIn('不是朗读台词', social)
        self.assertNotIn('[YOUR_METRIC] 写在已提交的简历上', social)
        self.assertNotRegex(social, r'(?m)^> .*\[(?:YOUR_|ROLE)')


class CampusTemplate(unittest.TestCase):
    def test_template_and_fictional_example_education_first_optional_photo(self):
        for name in ('resume.tex', 'example.tex'):
            text = (CAMPUS / name).read_text(encoding='utf-8')
            self.assertIn('ctexart', text)
            self.assertIn(r'\usepackage{cnresume}', text)
            self.assertIsNone(UNCOMMENTED_PHOTO.search(text))
            self.assertIsNone(UNBRACED_BRACKET_ITEM.search(text))
            sections = re.findall(r'\\cnsection\{([^}]+)\}', text)
            self.assertEqual(sections[0], '教育背景')
            self.assertEqual(sections[1:3], ['实习经历', '项目经历'])
            self.assertIn('在校经历 / 竞赛 / 奖学金', sections)
            self.assertNotIn('工作经历', sections)
            self.assertNotIn('YOUR_EMPLOYER', text)
        example = (CAMPUS / 'example.tex').read_text(encoding='utf-8')
        self.assertIn(r'\cnnotice{虚构示例', example)
        self.assertIn('程示例（虚构）', example)
        self.assertIn('campus@example.com', example)
        self.assertNotRegex(example, r'1[3-9]\d{9}')  # No plausible personal phone.
        self.assertNotIn('--', example)
        self.assertIn('GPA', example)

    @unittest.skipUnless(shutil.which('xelatex'), 'xelatex is not installed')
    def test_campus_files_compile_to_one_page_with_extractable_education(self):
        # Test the shared-style lookup exactly as /apply uses it after copying
        # either source into cv/, without duplicating cnresume.sty.
        with tempfile.TemporaryDirectory(prefix='campus-tex-') as tmp:
            tmp = Path(tmp)
            cv = tmp / 'cv'
            cv.mkdir()
            templates = tmp / 'templates'
            shutil.copytree(REPO / 'templates/cn', templates / 'cn')
            env = {**os.environ, 'TEXINPUTS': '../templates/cn//:'}
            for source in ('resume.tex', 'example.tex'):
                with self.subTest(source=source):
                    filename = 'main_fictional_' + source
                    shutil.copy(CAMPUS / source, cv / filename)
                    proc = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error', filename],
                                          cwd=cv, env=env, capture_output=True, text=True, timeout=120)
                    log = proc.stdout + proc.stderr
                    self.assertEqual(proc.returncode, 0, log[-4000:])
                    pdf = cv / filename.replace('.tex', '.pdf')
                    self.assertEqual(_pdf_page_count(pdf, log), 1)
                    if shutil.which('pdftotext'):
                        extracted = subprocess.run(['pdftotext', '-enc', 'UTF-8', str(pdf), '-'],
                                                   capture_output=True, text=True, check=True).stdout
                        self.assertIn('教育背景', extracted)
                        self.assertLess(extracted.index('教育背景'), extracted.index('实习经历'))
                        self.assertIn('项目经历', extracted)
                        self.assertNotIn('工作经历', extracted)
                        if source == 'example.tex':
                            self.assertIn('虚构', extracted)


if __name__ == '__main__':
    unittest.main()
