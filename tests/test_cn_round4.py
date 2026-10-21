"""Round 4: fictional China-market regressions and actual documented builds."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools import cn_jd_check as checker

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


class ChineseParsing(unittest.TestCase):
    def test_city_aliases_normalize_both_candidate_and_jd(self):
        cases = [('杭州市余杭区', '杭州'), ('杭州', '杭州市余杭区'),
                 ('上海市浦东新区', '沪'), ('深圳市南山区', '北上广深'),
                 ('北上广深', '广州市天河区'), ('Shanghai', '上海市')]
        for location, accepted in cases:
            with self.subTest(location=location, accepted=accepted):
                report = checker.check_jd('工作地点：' + location,
                                          {'city': {'accept': [accepted]}})
                city = next(r for r in report['hard_filters'] if r['name'] == 'city')
                self.assertEqual(city['status'], 'pass')
        unknown = checker.check_jd('工作地点：朝阳区', {'city': {'accept': ['北京']}})
        self.assertEqual(unknown['parsed']['cities'], [])
        mismatch = checker.check_jd('工作地点：深圳市南山区', {'city': {'accept': ['杭州市余杭区']}})
        self.assertTrue(mismatch['hard_fail'])

    def test_titles_preserve_role_scope_and_original(self):
        for label in ('岗位', '职位名称', 'role', 'job title'):
            report = checker.check_jd(f'{label}：高级Java服务端开发工程师（实习）', {})
            title = report['parsed']['title']
            self.assertEqual(title['raw'], '高级Java服务端开发工程师（实习）')
            self.assertEqual(title['normalized'], '高级Java后端开发工程师（实习）')
            self.assertEqual(title['family'], 'backend')
        self.assertIsNone(checker.check_jd('岗位：全栈工程师', {})['parsed']['title']['family'])
        self.assertEqual(checker.check_jd('岗位：Java开发', {})['parsed']['title']['family'], 'java_development')
        self.assertEqual(checker.check_jd('负责后端开发', {})['parsed']['title']['raw'], '')

    def test_salary_units_periods_and_thresholds(self):
        cases = [('20-30K·14薪', 20, 30, 'month'), ('20k-30k/月·14薪', 20, 30, 'month'),
                 ('20-30千元/月·14薪', 20, 30, 'month'), ('2-3万元/月·14薪', 20, 30, 'month'),
                 ('2-3W元/月·14薪', 20, 30, 'month'), ('20000-30000元/月·14薪', 20, 30, 'month'),
                 ('20000-30000 RMB/month, 14 months', 20, 30, 'month'),
                 ('240000-360000 CNY/year, 14 months', 20, 30, 'year'),
                 ('24-36万元/年·14薪', 20, 30, 'year'), ('年包24-36万·14薪', 20, 30, 'year')]
        for text, low, high, period in cases:
            with self.subTest(text=text):
                salary = checker.check_jd(text, {})['parsed']['salary']
                self.assertEqual((salary['min_monthly_k'], salary['max_monthly_k'], salary['period']), (low, high, period))
                self.assertEqual(salary['months'], 14)
        # Formerly 20-30万元/年 was mistaken for 200-300K monthly and passed.
        report = checker.check_jd('20-30万元/年', {'salary': {'min_monthly_k': 26}})
        self.assertTrue(report['hard_fail'])
        daily = checker.check_jd('200-300元/天', {'salary': {'min_daily': 200, 'min_monthly_k': 50, 'min_months': 16}})
        self.assertFalse(daily['hard_fail'])
        self.assertIsNone(daily['parsed']['salary']['min_monthly_k'])

    def test_windows_bom_and_legacy_console_output_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / '虚构配置.json'
            config.write_text(json.dumps({'city': {'accept': ['杭州']}, 'salary': {'min_daily': 200}}), encoding='utf-8-sig')
            jd = Path(tmp) / '虚构JD.txt'
            jd.write_text('工作地点：杭州市余杭区\n岗位：服务端实习生\n200-300元/天', encoding='utf-8-sig')
            env = {**os.environ, 'PYTHONIOENCODING': 'cp1252', 'PYTHONUTF8': '0'}
            def cli(*args):
                return subprocess.run([sys.executable, str(ROOT / 'tools/cn_jd_check.py'), *map(str, args)],
                                      env=env, capture_output=True, timeout=15)
            proc = cli('--in', jd, '--config', config)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8'))
            report = json.loads(proc.stdout.decode('utf-8'))
            self.assertEqual(report['parsed']['cities'], ['杭州'])
            self.assertIn('日薪', proc.stdout.decode('utf-8'))
            jd.write_bytes('虚构杭州实习'.encode('gbk'))
            proc = cli('--in', jd)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('UTF-8', proc.stderr.decode('utf-8'))
            config.write_text('{', encoding='utf-8')
            jd.write_text('实习', encoding='utf-8')
            proc = cli('--in', jd, '--config', config)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('配置读取或校验失败', proc.stderr.decode('utf-8'))
            self.assertIn('JSON', proc.stderr.decode('utf-8'))


@unittest.skipUnless(all(shutil.which(x) for x in ('xelatex', 'pdfinfo', 'pdftotext')), 'TeX/Poppler required')
class DocumentedBuilds(unittest.TestCase):
    def verify_pdf(self, path, log, needles):
        self.assertNotIn('Missing character', log)
        info = subprocess.check_output(['pdfinfo', str(path)], text=True)
        self.assertRegex(info, r'(?m)^Pages:\s+1\s*$')
        text = subprocess.check_output(['pdftotext', '-enc', 'UTF-8', str(path), '-'], text=True)
        self.assertNotIn('\ufffd', text)
        for word in needles:
            self.assertIn(word, text)

    def test_apply_commands_from_real_output_locations(self):
        with tempfile.TemporaryDirectory(prefix='cn-walk-') as tmp:
            root = Path(tmp)
            (root / 'cv').mkdir()
            shutil.copytree(ROOT / 'templates/cn', root / 'templates/cn')
            shutil.copytree(ROOT / 'cover_letters', root / 'cover_letters')
            command = next(line for line in read('templates/cn/README.md').splitlines() if line.startswith('cd cv &&'))
            for source, key, heading in [('templates/cn/resume.tex', '虚构社招_后端', '工作经历'),
                                         ('templates/cn/campus/resume.tex', '虚构学生_实习', '教育背景')]:
                # Start from the selected skeleton. All fields are fictional.
                text = read(source)
                text = re.sub(r'\[[^\]\n]*\]', lambda m: m[0] if m[0] in ('[a4paper,fontset=none,zihao=5]',) else '虚构', text)
                (root / 'cv' / f'main_{key}.tex').write_text(text, encoding='utf-8')
                proc = subprocess.run(command.replace('<company>_<role>', key), shell=True, cwd=root, capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr)
                log = (root / 'cv/build' / f'main_{key}.log').read_text(encoding='utf-8')
                self.verify_pdf(root / 'cv' / f'main_{key}.pdf', log, ['虚构', heading])
            # The exact documented campus directory command is also exercised.
            campus_command = read('templates/cn/campus/README.md').split('```bash\n', 1)[1].split('```', 1)[0]
            proc = subprocess.run(campus_command, shell=True, cwd=root / 'templates/cn/campus', capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr)
            self.verify_pdf(root / 'templates/cn/campus/build/example.pdf', proc.stdout, ['虚构', '教育背景'])
            # Use the preamble from the canonical cover guide and compile from cover_letters/.
            preamble = read('.claude/skills/job-application-assistant/06-cover-letter-templates.md').split('### Chinese cover letters', 1)[1].split('```latex\n', 1)[1].split('```', 1)[0]
            letter = '\\documentclass[]{cover}\n' + preamble + r'''
\pagestyle{empty}
\begin{document}
\namesection{}{\Huge{虚构乙}}{p2@example.com}
\currentdate{2026年10月21日}
\lettercontent{您好：申请虚构公司的后端实习。本人本科在读，每周四天。}
\lettercontent{课程项目中使用Java与MySQL，验证仅限本机。}
\closing{期待交流。}
\signature{虚构乙}
\end{document}
'''
            (root / 'cover_letters/cover_虚构_实习.tex').write_text(letter, encoding='utf-8')
            proc = subprocess.run('cd ../cover_letters && xelatex -interaction=nonstopmode cover_虚构_实习.tex', shell=True, cwd=root / 'cv', capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr)
            self.verify_pdf(root / 'cover_letters/cover_虚构_实习.pdf', proc.stdout, ['虚构乙', '您好', '本科在读', '每周四天'])

    def test_native_font_fallback_selection(self):
        # Exercise TeX branch selection without pretending proprietary fonts are
        # installed on Linux. Stub font loading; real Noto rendering is tested above.
        for available, expected in [(['SimSun', 'Microsoft YaHei'], 'SimSun/Microsoft YaHei'),
                                    (['SimSun'], 'SimSun/SimSun'),
                                    (['Songti SC', 'PingFang SC'], 'Songti SC/PingFang SC'),
                                    (['PingFang SC'], 'PingFang SC/PingFang SC')]:
            with self.subTest(available=available), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copy(ROOT / 'templates/cn/cnfonts.sty', root)
                source = r'''\documentclass[fontset=none]{ctexart}
\usepackage{xeCJK}
\ExplSyntaxOn
\RenewDocumentCommand\IfFontExistsTF{mmm}{\str_case_e:nnF{\tl_to_str:n{#1}}{CHOICES}{#3}}
\ExplSyntaxOff
\usepackage{cnfonts}
\renewcommand\cnfontpair[2]{}
\begin{document}fictional\end{document}
'''.replace('CHOICES', ''.join('{' + font + '}{#2}' for font in available))
                # Intercept fontpair before cnfonts defines it, reporting selection.
                source = source.replace(r'\usepackage{cnfonts}', r'\newcommand\cnfontpair[2]{\typeout{PAIR:#1/#2}}' + '\n' + r'\usepackage{cnfonts}')
                fonts = (root / 'cnfonts.sty').read_text().replace(r'\newcommand{\cnfontpair}', r'\providecommand{\cnfontpair}')
                (root / 'cnfonts.sty').write_text(fonts, encoding='utf-8')
                # Keep spaces significant in the test's string cases.
                source = source.replace('Microsoft YaHei', 'Microsoft~YaHei').replace('Songti SC', 'Songti~SC').replace('PingFang SC', 'PingFang~SC')
                (root / 'test.tex').write_text(source, encoding='utf-8')
                proc = subprocess.run(['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'test.tex'], cwd=root, capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stdout[-4000:])
                self.assertIn('PAIR:' + expected, proc.stdout)


class LaborScorePropagation(unittest.TestCase):
    def test_labor_penalty_is_persisted_and_does_not_veto(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state.json'
            results = Path(tmp) / 'results.json'
            state.write_text(json.dumps({'seen': {'fictional': {'company': '虚构公司', 'title': '后端',
                                  'url': 'https://example.com/fictional', 'status': 'new'}}}), encoding='utf-8')
            result = {'key': 'fictional', 'status': 'scored',
                      'scores': {k: 80 for k in ('technical', 'experience', 'behavioral', 'career')},
                      'location_verdict': 'PASS', 'labor_penalty': 12}
            def rank():
                results.write_text(json.dumps([result]), encoding='utf-8')
                return subprocess.run([sys.executable, str(ROOT / 'tools/rank_state.py'), 'apply',
                                       '--results', str(results), '--state', str(state), '--today', '2026-10-21'],
                                      capture_output=True, text=True, encoding='utf-8', timeout=15)
            proc = rank()
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report['ranked'][0]['score'], 68)
            self.assertEqual(report['vetoed'], [])
            self.assertEqual(json.loads(state.read_text())['seen']['fictional']['labor_penalty'], 12)
            del result['labor_penalty']
            proc = rank()
            self.assertEqual(json.loads(proc.stdout)['ranked'][0]['score'], 80)
            self.assertNotIn('labor_penalty', json.loads(state.read_text())['seen']['fictional'])
            for invalid in (-1, True, 'six'):
                result['labor_penalty'] = invalid
                proc = rank()
                self.assertEqual(proc.returncode, 1)
                self.assertIn('labor_penalty', json.loads(proc.stdout)['errors'][0]['error'])
