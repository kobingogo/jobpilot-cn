#!/usr/bin/env python3
"""jobpilot-cn 本地工作流；仅标准库，不连接模型或招聘网站。"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata

if __package__:
    from . import cn_jd_check, posting_guard, rank_state
else:
    import cn_jd_check
    import posting_guard
    import rank_state

REPO = Path(__file__).resolve().parent.parent
STAGES = {"experienced": "experienced", "社招": "experienced", "campus": "campus",
          "校招": "campus", "intern": "intern", "实习": "intern"}


class ChineseParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"参数错误：{message}；请运行 python tools/jobpilot.py --help，或在子命令后加 --help 查看用法。\n")


def read_text(path):
    return Path(path).read_text(encoding="utf-8-sig")


def read_json(path):
    return json.loads(read_text(path))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace only after the complete UTF-8 document has reached disk.
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def stage(value):
    if value not in STAGES:
        raise ValueError("职业阶段请填写 experienced/社招、campus/校招 或 intern/实习")
    return STAGES[value]


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("档案必须是 JSON 对象")
    for key in ("name", "city", "career_stage"):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError(f"档案缺少 {key}；请按 steps/setup.md 填写确认后的信息")
    profile = dict(profile)
    profile["career_stage"] = stage(profile["career_stage"])
    student = profile.get("student_status")
    if student is not None and not isinstance(student, bool):
        raise ValueError("student_status 请用 true、false 或 null，不能从 JD 推断")
    year = profile.get("graduation_year")
    if year is not None and (type(year) is not int or not 1900 <= year <= 2200):
        raise ValueError("graduation_year 请填写四位毕业年份或 null")
    for key in ("phone", "email", "availability", "summary", "skills"):
        if key in profile and not isinstance(profile[key], str):
            raise ValueError(f"{key} 请填写文字，未知可省略")
    for key in ("education", "experience", "projects"):
        if key in profile and (not isinstance(profile[key], list)
                               or any(not isinstance(v, str) for v in profile[key])):
            raise ValueError(f"{key} 请填写字符串数组，每条只写已确认的事实")
    return profile


def profile_for(args):
    path = args.profile or args.workspace / "profile/candidate.json"
    if not path.is_file():
        raise ValueError(f"找不到档案 {path}；先执行 init，再用 setup-profile write 保存已确认资料")
    return validate_profile(read_json(path))


def cmd_init(args):
    root = args.workspace
    for folder in ("profile", "config", "documents/applications", "documents/postings"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    template = root / "profile/candidate.example.json"
    if not template.exists():
        write_json(template, {"name": "待确认", "city": "待确认", "career_stage": "experienced",
                              "student_status": None, "graduation_year": None, "availability": "待确认",
                              "education": [], "experience": [], "projects": [], "skills": "待确认"})
    # A standalone workspace needs the same local-data boundary as this repository.
    ignore = root / ".gitignore"
    content = read_text(ignore) if ignore.exists() else ""
    rules = ("profile/", "config/cn_filters.json", "documents/applications/", "documents/postings/")
    missing = [rule for rule in rules if rule not in content.splitlines()]
    if missing:
        with ignore.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("\n# jobpilot-cn 本地个人资料\n" + "\n".join(missing) + "\n")
    return {"workspace": str(root), "profile_example": str(template), "message": "已初始化；示例不是候选人事实，请确认后保存档案"}


def input_text(path):
    if path is not None:
        if str(path).startswith(("http:", "https:")):
            raise ValueError("请将完整 JD 手工保存成 UTF-8 文件；不接受网站地址")
        text = read_text(path)
    else:
        buffer = getattr(sys.stdin, "buffer", None)
        text = buffer.read().decode("utf-8-sig") if buffer else sys.stdin.read()
    if not text.strip() or re.fullmatch(r"https?://\S+", text.strip()):
        raise ValueError("请输入完整 JD 正文（文件或标准输入）；只有链接或空白无法评估，不会抓取网站")
    return text


def cmd_profile(args):
    incoming = read_json(args.infile) if args.infile else json.loads(input_text(None))
    path = args.workspace / "profile/candidate.json"
    current = read_json(path) if path.exists() else {}
    if not isinstance(incoming, dict) or not isinstance(current, dict):
        raise ValueError("档案必须是 JSON 对象")
    profile = validate_profile({**current, **incoming})
    filters_path = args.workspace / "config/cn_filters.json"
    filters = read_json(filters_path) if filters_path.exists() else {}
    if not isinstance(filters, dict):
        raise ValueError("筛选配置必须是 JSON 对象")
    campus = dict(filters.get("campus", {}))
    campus["mode"] = profile["career_stage"]
    if "graduation_year" in incoming:
        campus["graduation_year"] = profile["graduation_year"]
    labor = dict(filters.get("labor", {}))
    if "student_status" in incoming:
        labor["candidate_is_student"] = profile["student_status"]
    filters.update(campus=campus, labor=labor)
    cn_jd_check.check_jd("校验配置", filters)
    write_json(path, profile)
    write_json(filters_path, filters)
    return {"profile": str(path), "filters": str(filters_path), "career_stage": profile["career_stage"]}


def check_text(text, args):
    cleaned, findings = posting_guard.guard(text, "text")
    config = args.config or args.workspace / "config/cn_filters.json"
    # Never accidentally consume the repository owner's config in an isolated workspace.
    if args.config or config.exists():
        report = cn_jd_check.check_jd(cleaned, config_path=config)
    else:
        report = cn_jd_check.check_jd(cleaned, config_path=cn_jd_check.EXAMPLE_CONFIG)
    report["integrity"] = {"verdict": posting_guard.verdict(findings), "findings": findings}
    return cleaned, report


def cmd_check(args):
    _, report = check_text(input_text(args.infile), args)
    return report


def slug(value):
    # Same documents/README.md naming rule, plus Windows reserved-name handling.
    text = unicodedata.normalize("NFC", value).lower().strip()
    text = re.sub(r'\s+', '_', text)
    text = re.sub(r'[^\w-]', '', text, flags=re.UNICODE).strip("_")
    if not text or len(text) > 80:
        raise ValueError("公司和岗位需包含文字或数字，且各不超过 80 字符；请使用简称")
    if re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", text):
        text = "_" + text
    return text


def tex(value):
    table = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
             "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
             "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(table.get(c, c) for c in str(value)).replace("\n", " ")


def resume(profile, role):
    campus = profile["career_stage"] in ("campus", "intern")
    template = REPO / ("templates/cn/campus/resume.tex" if campus else "templates/cn/resume.tex")
    # Reuse the shipped preamble/style, replacing content with confirmed facts.
    preamble = read_text(template).split(r"\begin{document}", 1)[0]
    preamble = preamble.replace("pdftitle={姓名}", "pdftitle={" + tex(profile["name"]) + "}")
    preamble = preamble.replace("pdfauthor={姓名}", "pdfauthor={" + tex(profile["name"]) + "}")
    lines = [preamble, r"\begin{document}",
             r"\cnheader{" + tex(profile["name"]) + "}{" + tex(role + " · " + profile["city"])
             + "}{" + tex(profile.get("phone", "电话待确认") + " · " + profile.get("email", "邮箱待确认")) + "}"]
    if profile.get("availability"):
        lines.append(r"\cnprofile{可到岗时间：" + tex(profile["availability"]) + "}")
    sections = [("education", "教育背景"), ("experience", "实习经历"), ("projects", "项目经历")] if campus else [
        ("experience", "工作经历"), ("projects", "项目经历"), ("education", "教育背景")]
    if profile.get("summary"):
        lines.extend([r"\cnsection{个人简介}", r"\cnprofile{" + tex(profile["summary"]) + "}"])
    for key, title in sections:
        values = profile.get(key, [])
        if values:
            lines.extend([r"\cnsection{" + title + "}", r"\begin{itemize}"])
            lines.extend(r"\item " + tex(value) for value in values)
            lines.append(r"\end{itemize}")
    lines.extend([r"\cnsection{专业技能}", r"\cnprofile{" + tex(profile.get("skills", "待确认")) + "}",
                  "% 草稿：缺失事实请与本人确认；不得把项目改写成任职。", r"\end{document}"])
    return "\n".join(lines) + "\n", template.relative_to(REPO).as_posix()


def cmd_scaffold(args):
    profile = profile_for(args)
    cleaned, report = check_text(input_text(args.infile), args)
    if (report["hard_fail"] or report["scam_fail"]) and not args.allow_risk:
        raise ValueError("JD 存在硬筛选/骗局风险；先运行 check-jd 查看证据，仅本人明确要求继续时使用 --allow-risk")
    if "⚠" in report["integrity"]["verdict"] and not args.allow_risk:
        raise ValueError("JD 完整性检查有提醒；先运行 check-jd 审阅证据，确认后可用 --allow-risk 继续")
    folder = args.workspace / "documents/applications" / (slug(args.company) + "_" + slug(args.role))
    if folder.exists():
        raise ValueError(f"申请目录已存在：{folder}；保留原始材料，请由 Agent 定点编辑或选择不同岗位名")
    cv, selected = resume(profile, args.role)
    letter = (r"\documentclass[a4paper,fontset=none,zihao=5]{ctexart}" + "\n"
              r"\usepackage{cnfonts}" + "\n" + r"\usepackage[margin=20mm]{geometry}" + "\n"
              r"\pagestyle{empty}" + "\n" + r"\begin{document}" + "\n"
              + tex(args.company + "招聘团队：") + "\n\n"
              + tex("申请" + args.role + "。我是" + profile["name"] + "。") + "\n\n"
              + "待补充：从已确认的档案选一条贡献，对应 JD 的一条要求；没有直接经验的部分如实说明。\n\n"
              + tex(profile["name"]) + "\n" + r"\end{document}" + "\n")
    folder.mkdir(parents=True)
    paths = {key: str(folder / name) for key, name in {
        "cv": "cv_draft.tex", "cover_letter": "cover_letter.tex", "posting": "job_posting.md",
        "outreach": "outreach.md", "check": "jd_check.json"}.items()}
    (folder / "cv_draft.tex").write_text(cv, encoding="utf-8")
    (folder / "cover_letter.tex").write_text(letter, encoding="utf-8")
    counts = {key: len(value) if isinstance(value, (dict, list)) else value
              for key, value in report["integrity"]["findings"].items()}
    (folder / "job_posting.md").write_text(cleaned + "\n\n## posting_guard\n"
        + report["integrity"]["verdict"] + "\n" + json.dumps(counts, ensure_ascii=False) + "\n", encoding="utf-8")
    # Archive only counts, never the removed excerpts.
    report["integrity"]["findings"] = counts
    write_json(folder / "jd_check.json", report)
    (folder / "outreach.md").write_text("# 投递短讯草稿（未发送）\n\n"
        f"公司：{args.company}\n岗位：{args.role}\n\n"
        "## Boss直聘 打招呼\n\n待补充：2 到 3 句，仅使用档案事实。\n\n"
        "## 智联/猎聘 申请附言\n\n待补充：一段，至多 4 句。\n\n"
        "用户审阅后自行复制发送；当前状态 drafted，不代表 applied。\n", encoding="utf-8")
    manifest = {"company": args.company, "role": args.role, "status": "drafted",
                "template": selected, "paths": paths}
    write_json(folder / "application.json", manifest)
    return {**manifest, "directory": str(folder), "message": "已填入已知事实和输出路径；仍需 Agent 按 apply 步骤撰写、审阅及编译"}


def cmd_compile(args):
    source = args.source.resolve()
    if source.suffix != ".tex" or not source.is_file():
        raise ValueError("compile 需要现有 .tex 文件；请检查路径")
    executable = shutil.which("xelatex")
    if not executable:
        raise ValueError("找不到 xelatex；请安装 TeX Live/MiKTeX、ctex、xeCJK 和中文字体，参阅 SETUP.md 中文路径")
    # os.pathsep is ':' on POSIX, ';' on Windows. The final empty element keeps TeX defaults.
    env = os.environ.copy()
    env["TEXINPUTS"] = os.pathsep.join([str(REPO / "templates/cn") + "//",
        str(REPO / "cover_letters") + "//", env.get("TEXINPUTS", ""), ""])
    with tempfile.TemporaryDirectory(prefix="jobpilot-tex-") as tmp:
        process = subprocess.run([executable, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error",
            "-output-directory=" + tmp, str(source)], cwd=source.parent, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        log_path = Path(tmp) / (source.stem + ".log")
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        output = process.stdout.decode("utf-8", errors="replace")
        if process.returncode:
            raise ValueError("XeLaTeX 编译失败；请修复模板/字体依赖后重试：\n" + output[-2400:])
        if "Missing character" in log or "Missing character" in output:
            raise ValueError("发现 Missing character；请安装 Noto CJK 等字体并重新编译，不能交付缺字 PDF")
        built = Path(tmp) / (source.stem + ".pdf")
        if not shutil.which("pdfinfo") or not shutil.which("pdftotext"):
            raise ValueError("缺少 pdfinfo/pdftotext，无法验证页数和中文抽取；请安装 Poppler 后重新运行 compile")
        # Reuse the existing Poppler fallback without depending on optional pypdf.
        if __package__:
            from .verify_pdf import VerificationError, _extract_pdftotext, normalize_text
        else:
            from verify_pdf import VerificationError, _extract_pdftotext, normalize_text
        try:
            extracted, pages = _extract_pdftotext(built)
        except VerificationError as exc:
            raise ValueError(f"PDF 抽取工具执行失败，请检查 Poppler 安装：{exc}") from exc
        if pages != args.pages:
            raise ValueError(f"PDF 应为 {args.pages} 页，实际 {pages} 页；请按岗位相关度删减，不缩小到五号字/12mm 以下")
        if not re.search(r"[\u3400-\u9fff]", extracted) or "\ufffd" in extracted or re.search(r"\(cid:\d+\)", extracted):
            raise ValueError("PDF 中文抽取缺失或乱码；请安装 Noto CJK 字体并重新编译")
        for needle in args.contains:
            if normalize_text(needle) not in normalize_text(extracted):
                raise ValueError(f"PDF 未抽取到 {needle!r}；检查中文字体及源文件内容")
        pdf = source.with_suffix(".pdf")
        shutil.copyfile(built, pdf)
    return {"pdf": str(pdf), "pages": pages, "extractor": "pdftotext", "cjk": True,
            "missing_character": False, "message": "机械检查通过；仍需查看 PDF 版面及事实，草稿不等于可投递"}


def cmd_interview(args):
    profile = profile_for(args)
    folder = args.application.resolve()
    if not folder.is_dir():
        raise ValueError("找不到申请目录；先 scaffold-application，或提供已保存的申请目录")
    guide = REPO / ("docs/cn/校招实习面试准备.md" if profile["career_stage"] in ("campus", "intern")
                    else "docs/cn/面试准备.md")
    posting = folder / "job_posting.md"
    if not posting.is_file():
        raise ValueError("申请缺少 job_posting.md；请先手工保存完整 JD，不从网站补抓")
    _, report = check_text(read_text(posting).split("\n## posting_guard", 1)[0], args)
    output = folder / ("interview_prep_" + slug(args.stage) + ".md")
    if output.exists():
        raise ValueError(f"准备稿已存在：{output}；请由 Agent 定点更新或换一个面试阶段名")
    headings = ["自我介绍与申请动机", "群面/无领导小组", "技术面", "HR面", "笔试/测评", "三方协议/offer 比较", "实习转正"] if profile["career_stage"] in ("campus", "intern") else ["自我介绍", "离职原因", "薪资谈判", "群面/无领导小组讨论"]
    text = (f"# 面试准备草稿：{args.stage}\n\n职业阶段：{profile['career_stage']}\n"
            f"指南：{guide}\n档案：{args.profile or args.workspace / 'profile/candidate.json'}\n"
            f"申请目录：{folder}\n完整性：{report['integrity']['verdict']}\n\n"
            "只使用本人确认及提交材料中的事实。公司资料未经核实标待确认；虚构示例不是事实。\n\n")
    text += "\n\n".join("## " + h + "\n\n待确认：根据指南、JD、提交版 CV 和前轮反馈填写。" for h in headings)
    text += "\n\n## STAR 与缺口\n\nS/T/A/R：待确认；项目不得换算为任职年限。\n\n## 反问与安排\n\n待确认：阶段、时间、面试官、形式与前轮反馈。\n"
    output.write_text(text, encoding="utf-8")
    return {"prep": str(output), "guide": str(guide), "career_stage": profile["career_stage"],
            "message": "已选择指南并生成准备提纲；由宿主 Agent 阅读指南和材料后完成回答"}


def cmd_rank(args):
    rows = read_json(args.results)
    if not isinstance(rows, list):
        raise ValueError("rank --results 应为 JSON 数组；每行包含 jd_file、scores 和证据")
    ranked, vetoed = [], []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("每个评分条目必须是 JSON 对象")
        jd = row.get("jd_file")
        if not isinstance(jd, str) or jd.startswith(("http:", "https:")):
            raise ValueError("每个条目需提供本地 jd_file，不接受招聘链接")
        path = Path(jd)
        if not path.is_absolute():
            path = args.results.resolve().parent / path
        _, report = check_text(input_text(path), args)
        score = rank_state.overall_score(row.get("scores"))
        score, hard, scam, *_ = rank_state.cn_adjust(report, score)
        location, language = row.get("location_verdict", "FLAG"), row.get("language_gate", "FLAG")
        if location not in ("PASS", "FLAG", "FAIL") or language not in ("PASS", "FLAG", "FAIL"):
            raise ValueError("location_verdict/language_gate 仅允许 PASS、FLAG、FAIL；未知请填 FLAG")
        result = {**row, "score": score, "verdict": rank_state.band(score), "hard_fail": hard,
                  "scam_fail": scam, "location_verdict": location, "language_gate": language,
                  "thresholds_source": report["thresholds_source"], "jd_check": report}
        (vetoed if hard or scam or location == "FAIL" or language == "FAIL" else ranked).append(result)
    ranked.sort(key=lambda row: row["score"], reverse=True)
    return {"ranked": ranked, "vetoed": vetoed, "message": "仅汇总宿主 Agent 的四维评分及本地 JD 风险，不代表自动评估/投递"}


def parser():
    ap = ChineseParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", type=Path, default=Path.cwd(), help="个人资料与输出根目录，默认当前目录")
    common.add_argument("--profile", type=Path, help="已确认档案 JSON，默认 workspace/profile/candidate.json")
    common.add_argument("--config", type=Path, help="本地筛选 JSON；省略时先找 workspace/config/cn_filters.json")
    sub = ap.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", parents=[common], help="初始化本地目录和空档案示例")
    init.set_defaults(func=cmd_init)
    setup = sub.add_parser("setup-profile", help="保存确认后的本地档案")
    writer = setup.add_subparsers(dest="action", required=True).add_parser("write", parents=[common])
    writer.add_argument("--in", dest="infile", type=Path, help="UTF-8 档案 JSON，省略则从标准输入读")
    writer.set_defaults(func=cmd_profile)
    for name, func in (("check-jd", cmd_check), ("scaffold-application", cmd_scaffold)):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("--in", dest="infile", type=Path, help="UTF-8 JD 文件，省略则从标准输入读")
        p.set_defaults(func=func)
        if name == "scaffold-application":
            p.add_argument("--company", required=True)
            p.add_argument("--role", required=True)
            p.add_argument("--allow-risk", action="store_true", help="仅本人审阅风险并明确要求继续时使用")
    p = sub.add_parser("compile", help="XeLaTeX 编译并验证一页中文 PDF（需要 Poppler）")
    p.add_argument("source", type=Path)
    p.add_argument("--pages", type=int, choices=range(1, 100), default=1)
    p.add_argument("--contains", action="append", default=[], help="必须抽取到的姓名/关键词，可重复")
    p.set_defaults(func=cmd_compile)
    p = sub.add_parser("interview-prep", parents=[common])
    p.add_argument("--application", type=Path, required=True)
    p.add_argument("--stage", default="一面")
    p.set_defaults(func=cmd_interview)
    p = sub.add_parser("rank", parents=[common])
    p.add_argument("--results", type=Path, required=True, help="包含本地 JD 路径及四维评分的 JSON 数组")
    p.set_defaults(func=cmd_rank)
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    if hasattr(args, "workspace"):
        args.workspace = args.workspace.resolve()
    try:
        result = args.func(args)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RuntimeError) as exc:
        print(f"jobpilot：{exc}；请检查路径、UTF-8 编码和输入格式，详见 skills/jobpilot-cn/SKILL.md", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
