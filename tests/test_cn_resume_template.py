"""The shipped one-page Chinese résumé stays fictional, optional-photo, and wired in.

/apply selects templates/cn/ only as a CV-language exception. The stock
moderncv page check (exactly 2) has to remain the literal command in Step 5b,
and the example résumé must stay obviously 虚构 so it cannot be mistaken for
a candidate.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CN = REPO / "templates" / "cn"
APPLY = REPO / ".claude" / "commands" / "apply.md"
GUIDE = REPO / ".claude" / "skills" / "job-application-assistant" / "05-cv-templates.md"
REVIEWER = REPO / ".claude" / "agents" / "application-reviewer.md"

UNBRACED_BRACKET_ITEM = re.compile(r"\\item\s*\[")
UNCOMMENTED_PHOTO = re.compile(r"(?m)^(?!\s*%).*\\cnphoto\{")
PAGES_LINE = re.compile(
    r"^python tools/verify_pdf\.py cv/main_<company>_<role>\.pdf --pages (\d+)\s*$",
    re.MULTILINE,
)


class ChineseResumeTemplate(unittest.TestCase):
    def test_files_exist(self):
        for name in ("README.md", "cnresume.sty", "resume.tex", "example.tex"):
            self.assertTrue((CN / name).is_file(), name)

    def test_skeleton_uses_ctex_and_xecjk_with_photo_off(self):
        sty = (CN / "cnresume.sty").read_text(encoding="utf-8")
        resume = (CN / "resume.tex").read_text(encoding="utf-8")
        self.assertIn("xeCJK", sty)
        self.assertIn(r"\cnphotofalse", sty)
        self.assertIn(r"\newcommand{\cnphoto}", sty)
        self.assertIn(r"\documentclass", resume)
        self.assertIn("ctexart", resume)
        self.assertIn(r"\usepackage{cnresume}", resume)
        self.assertIsNone(
            UNCOMMENTED_PHOTO.search(resume),
            "resume.tex must leave \\cnphoto commented out",
        )
        self.assertIsNone(UNBRACED_BRACKET_ITEM.search(resume))
        self.assertIsNone(UNBRACED_BRACKET_ITEM.search(sty))

    def test_example_is_marked_fictional_and_has_no_photo(self):
        example = (CN / "example.tex").read_text(encoding="utf-8")
        for token in ("虚构", "林示意", "shiyi.lin@example.com", "138-0000-0000", "示意理工大学"):
            self.assertIn(token, example)
        self.assertNotIn("[YOUR_NAME]", example)
        self.assertNotIn("[YOUR_EMAIL]", example)
        self.assertIsNone(
            UNCOMMENTED_PHOTO.search(example),
            "example.tex must not turn the photo on",
        )
        self.assertIsNone(UNBRACED_BRACKET_ITEM.search(example))
        # Dates stay ASCII hyphens so the ATS date check does not fire.
        self.assertNotIn("--", example)

    def test_readme_states_the_rules(self):
        readme = (CN / "README.md").read_text(encoding="utf-8")
        self.assertIn("虚构", readme)
        self.assertIn("xelatex", readme)
        self.assertIn("xeCJK", readme)
        self.assertRegex(readme, r"手贴|粘贴")
        self.assertIn("不抓取", readme)
        self.assertIn("不自动", readme)
        self.assertIn(r"\cnphoto", readme)

    def test_apply_flow_selects_it_without_replacing_the_stock_page_check(self):
        apply = APPLY.read_text(encoding="utf-8")
        guide = GUIDE.read_text(encoding="utf-8")
        reviewer = REVIEWER.read_text(encoding="utf-8")
        self.assertIn("templates/cn/resume.tex", apply)
        self.assertIn("templates/cn/example.tex", apply)
        self.assertIn("虚构", apply)
        self.assertIn("does not scrape", apply)
        self.assertIn("templates/cn/", guide)
        self.assertIn("xelatex", guide)
        self.assertIn("templates/cn/example.tex", reviewer)
        # The mechanical 2-page command stays. A second line for the same
        # path with --pages 1 would make the page-count test keep the last one.
        self.assertEqual(PAGES_LINE.findall(apply), ["2"])

    def test_outreach_template_is_manual_and_fictional(self):
        text = (CN / "outreach.md").read_text(encoding="utf-8")
        for token in (
            "Boss直聘",
            "打招呼",
            "智联",
            "猎聘",
            "虚构",
            "林示意",
            "示意云计算",
            "[YOUR_NAME]",
            "不抓取",
            "不自动",
            "复制",
            "2 到 3",
        ):
            self.assertIn(token, text, token)
        self.assertNotIn(".env", text)
        self.assertNotIn("@", text)
        self.assertNotIn("--", text)
        self.assertNotIn("——", text)
        self.assertIsNone(re.search(r"1[3-9]\d{9}", text))

        boss = _between(text, "## Boss直聘 打招呼", "## 智联/猎聘 申请附言")
        boss_quotes = _quotes(boss)
        self.assertEqual(len(boss_quotes), 2, boss_quotes)
        self.assertIn("[YOUR_NAME]", boss_quotes[0])
        self.assertNotIn("[YOUR_NAME]", boss_quotes[1])
        self.assertIn("虚构", boss_quotes[1])
        for quote in boss_quotes:
            sentences = quote.count("。")
            self.assertGreaterEqual(sentences, 2, quote)
            self.assertLessEqual(sentences, 3, quote)

        note = _between(text, "## 智联/猎聘 申请附言", "## `/apply` 写出的文件")
        note_quotes = _quotes(note)
        self.assertEqual(len(note_quotes), 2, note_quotes)
        self.assertIn("[YOUR_NAME]", note_quotes[0])
        self.assertNotIn("[YOUR_NAME]", note_quotes[1])
        self.assertIn("虚构", note_quotes[1])
        self.assertIn("林示意", note_quotes[1])
        for quote in note_quotes:
            self.assertLessEqual(quote.count("。"), 4, quote)
            self.assertGreaterEqual(quote.count("。"), 1, quote)

    def test_apply_produces_outreach_for_hand_copy(self):
        apply = APPLY.read_text(encoding="utf-8")
        guide = GUIDE.read_text(encoding="utf-8")
        reviewer = REVIEWER.read_text(encoding="utf-8")
        fetcher = (REPO / ".claude" / "agents" / "posting-fetcher.md").read_text(encoding="utf-8")
        self.assertIn("templates/cn/outreach.md", apply)
        self.assertIn("documents/applications/<company>_<role>/outreach.md", apply)
        self.assertIn("The user copies the text and sends it manually.", apply)
        self.assertIn("Never send", apply)
        self.assertIn("2 or 3 sentences", apply)
        self.assertIn("does not scrape", apply)
        self.assertIn("zhipin.com", apply)
        self.assertIn("Do not add a scraper", apply)
        self.assertIn("templates/cn/outreach.md", guide)
        self.assertIn("templates/cn/outreach.md", reviewer)
        self.assertIn("2 or 3 sentences", reviewer)
        self.assertIn("虚构", reviewer)
        tools = re.search(r"^tools:\s*(.*)$", reviewer, re.M).group(1)
        self.assertNotIn("Edit", tools)
        self.assertNotIn("Write", tools)
        self.assertIn("paste required", fetcher)
        self.assertIn("Do not add a scraper", fetcher)
        self.assertIn("zhipin.com", fetcher)
        # The stock 2-page command is unchanged by the outreach path.
        self.assertEqual(PAGES_LINE.findall(apply), ["2"])

    def test_example_embeds_simplified_cjk_when_noto_is_installed(self):
        if shutil.which("xelatex") is None or shutil.which("pdffonts") is None:
            self.skipTest("xelatex or pdffonts is not installed")
        if not _noto_cjk_installed():
            self.skipTest("Noto CJK is not installed")
        sty = (CN / "cnresume.sty").read_text(encoding="utf-8")
        noto, _, fandol = sty.partition("Falling back to Fandol")
        for token in (
            "NotoSerifCJK-Regular.ttc",
            "NotoSerifCJK-Bold.ttc",
            "NotoSansCJK-Regular.ttc",
            "NotoSansCJK-Bold.ttc",
            "FontIndex=2",
            "Script=CJK",
            "Language={Chinese Simplified}",
        ):
            self.assertIn(token, noto, token)
        self.assertNotIn("FontIndex", fandol)
        self.assertIn("FandolSong-Regular.otf", fandol)
        with tempfile.TemporaryDirectory(prefix="cnresume-") as tmp:
            proc = subprocess.run(
                [
                    "xelatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={tmp}",
                    "example.tex",
                ],
                cwd=CN,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            log_path = Path(tmp) / "example.log"
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            log = f"{log}\n{proc.stdout}\n{proc.stderr}"
            self.assertEqual(proc.returncode, 0, log[-4000:])
            pdf = Path(tmp) / "example.pdf"
            self.assertTrue(pdf.is_file(), "example.pdf was not written")
            pages = _pdf_page_count(pdf, log)
            self.assertEqual(pages, 1, log[-1500:])
            fonts = subprocess.run(
                ["pdffonts", str(pdf)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            _assert_simplified_cjk(self, fonts, log)


def _noto_cjk_installed() -> bool:
    fc_list = shutil.which("fc-list")
    if fc_list is not None:
        found = subprocess.run(
            [fc_list, ":family", "file"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "NotoSerifCJK-Regular.ttc" in found.stdout or "Noto Serif CJK SC" in found.stdout:
            return True
    return any(
        path.is_file()
        for path in (
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
            Path("/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc"),
        )
    )


def _pdf_page_count(pdf: Path, log: str) -> int:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo is not None:
        info = subprocess.run(
            [pdfinfo, str(pdf)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        match = re.search(r"(?m)^Pages:\s+(\d+)\s*$", info)
        if match is None:
            raise AssertionError(f"pdfinfo did not report a page count:\n{info}")
        return int(match.group(1))
    match = re.search(r"Output written on .+\((\d+) page", log)
    if match is None:
        raise AssertionError("could not determine the PDF page count")
    return int(match.group(1))


def _assert_simplified_cjk(test: unittest.TestCase, fonts: str, log: str) -> None:
    """SC is either a CJKsc PostScript name, or FontIndex 2 plus locl.

    fonts-noto-cjk ships a Super OTC. Every face shares one CFF table whose
    FontName is Noto*CJKjp, so pdffonts keeps saying CJKjp after FontIndex=2.
    Region-specific files do embed as CJKsc; then CJKjp must be absent.
    """
    if "CJKsc" in fonts:
        test.assertNotIn("CJKjp", fonts)
        return
    # example.tex uses the serif face (including bold). Sans is declared but
    # not selected, so it is not in this log; the sty text above covers it.
    flat = re.sub(r"\(fontspec\)", "", log)
    flat = re.sub(r"\s+", "", flat)
    test.assertIn("Language={ChineseSimplified}", flat)
    test.assertIn("language=ZHS", flat)
    test.assertIn("NotoSerifCJK-Regular.ttc:2", flat)
    test.assertIn("NotoSerifCJK-Bold.ttc:2", flat)
    test.assertNotIn("language=JAN", flat)
    test.assertIn("Noto", fonts)
    test.assertNotIn("Fandol", fonts)


def _between(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    stop = text.index(end, begin + len(start))
    return text[begin:stop]


def _quotes(section: str) -> list[str]:
    return [line[2:].strip() for line in section.splitlines() if line.startswith("> ")]


if __name__ == "__main__":
    unittest.main()
