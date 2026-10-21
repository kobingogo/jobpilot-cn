"""Final TeX/PDF placeholder gates and the local Chinese letterhead."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import jobpilot

ROOT = Path(__file__).resolve().parent.parent


class FinalArtifactPlaceholders(unittest.TestCase):
    def test_source_placeholders_fail_cli_before_tex_dependencies_are_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'fictional.tex'
            for placeholder in ('待确认', '时间待确认', '学校城市待确认', '[占位]', 'TODO', 'todo: dates',
                                'FIXME', 'TBD', 'XXX', '[YOUR_EMAIL]', '［占位］', '待补充', '[姓名]'):
                source.write_text('虚构材料\n' + placeholder, encoding='utf-8')
                proc = subprocess.run([sys.executable, str(ROOT / 'tools/jobpilot.py'), 'compile', str(source)],
                                      capture_output=True, text=True, timeout=15)
                self.assertNotEqual(proc.returncode, 0, placeholder)
                self.assertIn('占位', proc.stderr)
                self.assertIn('review.md', proc.stderr)
                self.assertIn('--draft', proc.stderr)
                self.assertNotIn('Traceback', proc.stderr)
                self.assertFalse(source.with_suffix('.pdf').exists())

    def test_draft_flag_only_bypasses_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'fictional.tex'
            source.write_text('待确认', encoding='utf-8')
            args = jobpilot.parser().parse_args(['compile', str(source), '--draft'])
            with patch.object(jobpilot.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(ValueError, '找不到 xelatex'):
                    jobpilot.cmd_compile(args)
        # Real technical words must not become TODO-like false positives.
        jobpilot.reject_placeholders('虚构经历：Todoist API，使用 xxxlib，编写方法 todos()；'
                                    '使用 SQL 占位符绑定参数，实现图片占位加载', '源文件')


TEX = all(shutil.which(x) for x in ('xelatex', 'pdfinfo', 'pdftotext'))


@unittest.skipUnless(TEX, 'XeLaTeX/Poppler required for actual PDF checks')
class RealChineseArtifacts(unittest.TestCase):
    def compile(self, source, *flags):
        args = jobpilot.parser().parse_args(['compile', str(source), *flags])
        return jobpilot.cmd_compile(args)

    def test_pdf_placeholder_from_input_is_blocked_and_draft_still_checks_page_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'body.tex').write_text('学校城市待确认', encoding='utf-8')
            source = root / 'fictional.tex'
            source.write_text(r'''\documentclass[a4paper,fontset=none]{ctexart}
\usepackage{cnfonts}
\begin{document}虚构材料\input{body.tex}\end{document}''', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'PDF 文本含占位'):
                self.compile(source)
            self.assertFalse(source.with_suffix('.pdf').exists())
            report = self.compile(source, '--draft', '--contains', '虚构材料')
            self.assertTrue(report['draft'])
            self.assertEqual(report['pages'], 1)
            with self.assertRaisesRegex(ValueError, '实际 1 页'):
                self.compile(source, '--draft', '--pages', '2')
            with self.assertRaisesRegex(ValueError, '未抽取到'):
                self.compile(source, '--draft', '--contains', '不存在的虚构姓名')
            (root / 'body.tex').write_text('虚构大学，杭州', encoding='utf-8')
            self.assertFalse(self.compile(source)['draft'])

    def test_fictional_cover_example_is_a4_one_page_with_extractable_letterhead_and_signoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'fictional.tex'
            source.write_text((ROOT / 'templates/cn/cover_example.tex').read_text(encoding='utf-8'), encoding='utf-8')
            result = self.compile(source, '--contains', '林示意', '--contains', 'shiyi.lin@example.com')
            self.assertEqual(result['pages'], 1)
            info = subprocess.check_output(['pdfinfo', result['pdf']], text=True)
            self.assertRegex(info, r'Page size:\s+595[.\d]* x 841[.\d]* pts \(A4\)')
            text = subprocess.check_output(['pdftotext', '-enc', 'UTF-8', result['pdf'], '-'], text=True)
            for token in ('138-0000-0000', '2026-10-21', '招聘团队', '此致', '敬礼'):
                self.assertIn(token, text)
            self.assertLess(text.index('林示意'), text.index('招聘团队'))
            self.assertGreater(text.rindex('林示意'), text.index('此致'))

