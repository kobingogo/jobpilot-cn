"""Round 5: compile the canonical Chinese cover preamble and verify A4/text."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(all(shutil.which(x) for x in ('xelatex', 'pdfinfo', 'pdftotext')), 'TeX/Poppler required')
class ChineseCoverLayout(unittest.TestCase):
    def test_canonical_chinese_cover_is_a4_and_extracts_chinese(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'cover_letters', root / 'cover_letters')
            shutil.copytree(ROOT / 'templates/cn', root / 'templates/cn')
            guide = (ROOT / '.claude/skills/job-application-assistant/06-cover-letter-templates.md').read_text()
            preamble = guide.split('### Chinese cover letters', 1)[1].split('```latex\n', 1)[1].split('```', 1)[0]
            source = '\\documentclass[]{cover}\n' + preamble + r'''
\pagestyle{empty}
\begin{document}
\lettercontent{虚构示例：您好，申请虚构公司的后端岗位。Java Python}
\signature{虚构甲}
\end{document}
'''
            work = root / 'cover_letters'
            (work / 'fictional.tex').write_text(source, encoding='utf-8')
            proc = subprocess.run(['xelatex', '-halt-on-error', '-interaction=nonstopmode', 'fictional.tex'],
                                  cwd=work, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout[-3000:])
            self.assertNotIn('Missing character', proc.stdout)
            info = subprocess.check_output(['pdfinfo', str(work / 'fictional.pdf')], text=True)
            self.assertRegex(info, r'Page size:\s+595[.\d]* x 841[.\d]* pts \(A4\)')
            self.assertRegex(info, r'Pages:\s+1\b')
            text = subprocess.check_output(['pdftotext', '-enc', 'UTF-8', str(work / 'fictional.pdf'), '-'], text=True)
            self.assertIn('虚构示例', text)
            self.assertIn('Java Python', text)
