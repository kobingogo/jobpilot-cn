"""Portable interpreter examples and workspace/documentation boundaries."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class LocalDocumentation(unittest.TestCase):
    def test_python_fallback_and_local_output_rules_are_explicit(self):
        skill = ROOT / 'skills/jobpilot-cn'
        for path in [skill / 'SKILL.md', *skill.glob('steps/*.md')]:
            content = path.read_text(encoding='utf-8')
            self.assertIn('python3', content, path.name)
            self.assertIn('py -3', content, path.name)
            self.assertNotRegex(content, r'\bpython tools/', path.name)
        setup = (skill / 'steps/setup.md').read_text(encoding='utf-8')
        apply = (skill / 'steps/apply.md').read_text(encoding='utf-8')
        for word in ('.gitkeep', '视为空', '不要求', 'cv/main_example.tex'):
            self.assertIn(word, setup)
        for word in ('--draft', 'review.md', 'cncover.sty', '同一工作区', '不联网核验', '用户提供'):
            self.assertIn(word, apply)
        self.assertNotRegex(apply, r'python3 tools/verify_pdf.py cv/')


