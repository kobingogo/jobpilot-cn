# 一页中文简历（ctex / xeCJK）

给 `/apply` 用的一页中文简历。职位描述一律手贴。这里不抓取招聘网站，也不自动打招呼或投递。

`example.tex` 是**虚构**示例：林示意这个人、电话、邮箱、公司、学校和数字都是编的，只演示版式。不要把它抄进申请，也不要把它当事实来源。真实内容只来自候选人档案。

## 文件

| 文件 | 作用 |
|---|---|
| `cnfonts.sty` | CV 与中文求职信共享字体选择（不改变求职信版式） |
| `cncover.sty` | 中文求职信 A4；ctexart 提供信头/落款，旧 cover.cls 保留其页边距和字体 |
| `cnresume.sty` | 版式。单栏，方便 ATS 按阅读顺序抽取文本 |
| `resume.tex` | 骨架。方括号是占位符，复制后再填 |
| `example.tex` | 虚构的填好示例，页眉和正文都标了「虚构」 |
| `cover_example.tex` | ctexart + cnfonts + cncover 的一页虚构求职信示例 |
| `outreach.md` | Boss直聘 打招呼（2 到 3 句）和智联/猎聘申请附言。用户复制后自己发送 |

照片**默认关闭**。需要时在导言区写 `\cnphoto{photo.jpg}`，图片跟源文件放在一起。不要提交图片（仓库忽略 `*.jpg` / `*.png`）。没打开开关就不会去找图片。

中文本地 Skill 的求职信采用 ctexart + cnfonts + cncover，共享字体回退，正文与列表使用同一字体。
`\cnletterhead{姓名}{联系方式}{日期}` 提供信头，`\cnlettersignoff{姓名}` 提供落款。
A4，20mm 页边距，一页；未知联系方式省略，问题另记 review.md，不写入最终材料。
旧 Claude adapter 的 cover.cls/Raleway 字体说明仅用于它自己的历史流程，保持原样。

## 编译

需要 XeLaTeX 和 ctex（会载入 xeCJK）。不要用 pdflatex 或 lualatex。TeX Live 示例：`texlive-xetex`、`texlive-lang-chinese`、`texlive-latex-extra`、`texlive-latex-recommended`。

中文简历 `.tex` 写 `fontset=none`。`cnresume.sty` 优先用已安装的 Noto Serif CJK SC（Debian/Ubuntu 包 `fonts-noto-cjk`）。这份字体带 ToUnicode，`/apply` 先试的 pypdf 能抽出中文。没有 Noto 时先尝试 Windows/macOS 系统字体，均缺失才退回 Fandol（`texlive-lang-chinese` 自带）：页面能编译，但 pypdf 读到的中文是乱码。这时去装 Noto 再编译，不要按乱码改简历正文。ctex 2.5 没有 `fontset=noto`，不要写这个选项。

在本目录检查示例：

```bash
rm -f example.pdf && mkdir -p build && xelatex -interaction=nonstopmode -halt-on-error -output-directory=build example.tex && mv build/example.pdf ./
```

## 中文本地 Skill 输出（默认）

`skills/jobpilot-cn/steps/apply.md` 使用 `tools/jobpilot.py scaffold-application`，
从确认档案填入简历与信头。工作区 `documents/applications/<company>_<role>/` 中的源稿直接编译，
以 application.json 的实际 paths 为准，不额外复制到 cv/ 或 cover_letters/。
所有 Python 示例使用 Python 3.10+ 的 `python3`；若只有 `python`，确认版本后替换；Windows 用 `py -3`。

```bash
python3 tools/jobpilot.py compile documents/applications/<company>_<role>/cv_draft.tex --contains "姓名"
python3 tools/jobpilot.py compile documents/applications/<company>_<role>/cover_letter.tex --contains "姓名"
```

隔离工作区时传该工作区的实际文件路径。CLI 自动设置 TEXINPUTS、Windows 分隔符及临时构建目录，
使用 -no-shell-escape，检查一页、中文抽取、缺字及源文件/PDF 占位内容。
含待确认、[占位]、TODO 等则失败；仅预览可加 --draft，最终必须去掉占位并不带该参数编译。
未知项写到独立 review.md/notes.md。两个 PDF 还需查看版面，不以机械检查替代视觉检查。

在仓库根目录可检查虚构求职信示例（勿用于真实申请）：

```bash
python3 tools/jobpilot.py compile templates/cn/cover_example.tex --contains "林示意"
```

照片默认关闭；校园模板是 [campus/resume.tex](campus/resume.tex)，教育优先，无需现职雇主。
内容不足时保留真实留白，不为填页编造经历；超过一页按岗位相关度删减，
不缩到五号字或 12mm 页边距以下。日期用 ASCII 连字符（2022.04-2026.03），百分号写 \%，条目间不插 \vspace。
`tools/verify_layout.py` 的 90pt 页脚带按 moderncv 标定，中文简历可能误报，应结合 PDF 判断。
打招呼和申请附言参考 outreach.md，只起草，用户自行发送，不抓取或自动投递。

## 旧 Claude adapter 的兼容编译（不用于中文本地 Skill）

`.claude/commands/apply.md` 的上游流程仍使用 cv/、cover_letters/，求职信仍走 cover.cls。
该分支的中文信按 `06-cover-letter-templates.md` 加载 ctex、cnfonts、cncover，保留 Raleway 和原页边距。
仅该旧分支从仓库根目录执行下面的历史 CV 命令：

```bash
cd cv && rm -f main_<company>_<role>.pdf && mkdir -p build && TEXINPUTS=.:../templates/cn//: xelatex -interaction=nonstopmode -halt-on-error -output-directory=build main_<company>_<role>.tex && mv build/main_<company>_<role>.pdf ./
```

Windows 手工编译的 TEXINPUTS 使用分号，如 `.;../templates/cn//;`，末尾分隔符保留系统包路径。
中文本地 Skill 直接用上面的 compile 命令，无需手工设置。旧稿不批量改写。

中文字体按 Noto CJK → Windows SimSun / Microsoft YaHei → macOS Songti SC / PingFang SC → Fandol 选择。
Linux 可装 fonts-noto-cjk；系统字体能否正确嵌入仍需检查。安装后重开终端并重新编译，
确认没有 Missing character，pdftotext -layout -enc UTF-8 能抽取姓名与中文栏目，页数恰好一页。
