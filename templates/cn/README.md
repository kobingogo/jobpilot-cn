# 一页中文简历（ctex / xeCJK）

给 `/apply` 用的一页中文简历。职位描述一律手贴。这里不抓取招聘网站，也不自动打招呼或投递。

`example.tex` 是**虚构**示例：林示意这个人、电话、邮箱、公司、学校和数字都是编的，只演示版式。不要把它抄进申请，也不要把它当事实来源。真实内容只来自候选人档案。

## 文件

| 文件 | 作用 |
|---|---|
| `cnfonts.sty` | CV 与中文求职信共享字体选择（不改变求职信版式） |
| `cnresume.sty` | 版式。单栏，方便 ATS 按阅读顺序抽取文本 |
| `resume.tex` | 骨架。方括号是占位符，复制后再填 |
| `example.tex` | 虚构的填好示例，页眉和正文都标了「虚构」 |
| `outreach.md` | Boss直聘 打招呼（2 到 3 句）和智联/猎聘申请附言。用户复制后自己发送 |

照片**默认关闭**。需要时在导言区写 `\cnphoto{photo.jpg}`，图片跟源文件放在一起。不要提交图片（仓库忽略 `*.jpg` / `*.png`）。没打开开关就不会去找图片。

## 编译

需要 XeLaTeX 和 ctex（会载入 xeCJK）。不要用 pdflatex 或 lualatex。TeX Live 示例：`texlive-xetex`、`texlive-lang-chinese`、`texlive-latex-extra`、`texlive-latex-recommended`。

中文简历 `.tex` 写 `fontset=none`。`cnresume.sty` 优先用已安装的 Noto Serif CJK SC（Debian/Ubuntu 包 `fonts-noto-cjk`）。这份字体带 ToUnicode，`/apply` 先试的 pypdf 能抽出中文。没有 Noto 时先尝试 Windows/macOS 系统字体，均缺失才退回 Fandol（`texlive-lang-chinese` 自带）：页面能编译，但 pypdf 读到的中文是乱码。这时去装 Noto 再编译，不要按乱码改简历正文。ctex 2.5 没有 `fontset=noto`，不要写这个选项。

在本目录检查示例：

```bash
rm -f example.pdf && mkdir -p build && xelatex -interaction=nonstopmode -halt-on-error -output-directory=build example.tex && mv build/example.pdf ./
```

`/apply` 把 `resume.tex` 复制到 `cv/main_<company>_<role>.tex` 后，在仓库根目录的 `cv/` 里编译，并用 `TEXINPUTS` 找到样式文件：

```bash
cd cv && rm -f main_<company>_<role>.pdf && mkdir -p build && TEXINPUTS=.:../templates/cn//: xelatex -interaction=nonstopmode -halt-on-error -output-directory=build main_<company>_<role>.tex && mv build/main_<company>_<role>.pdf ./
```

失败时先看 `build/` 里的 log，不要留下过期 PDF。不要加 `-shell-escape`。页数必须是 **1**。日期参数用一个 ASCII 连字符（`2022.04-2026.03`），不要写 `--`。百分号写成 `\%`。条目之间不要插入 `\vspace`。

## 怎么被 `/apply` 选中

档案里的 CV language 是「中文」（或 `Chinese` / `zh`），并且没有用 `/add-template` 登记别的模板时，`/apply` 用这份骨架，而不是 moderncv 的两页简历。用户当次明确要求一页中文简历时同样使用。已经激活的自定义模板优先。求职信仍走原来的 `cover.cls`，语言跟手贴的职位描述走。

一页能放下的大概是：简介两三行，技能三四行，最近一份工作三条，前一份两条，一个项目两条，教育一行。溢到第二页就删内容，不要把字号降到五号以下，也不要把页边距压到 12mm 以下。校招/实习使用 [campus/resume.tex](campus/resume.tex)（[说明与虚构示例](campus/README.md)），教育优先，无需现职雇主。`Career stage: campus / intern` 由 `/setup` 记录，`/apply` 据此选中，仍为 xelatex、单栏、1 页。

## 打招呼和申请附言

`outreach.md` 是两段可复制的短讯，不是 PDF。Boss直聘的招呼是 2 到 3 句。智联和猎聘共用一段申请附言，至多 4 句。`/apply` 在选用这份简历，或用户点名这些网站时，按档案填好草稿，写到 `documents/applications/<company>_<role>/outreach.md`。用户自己复制发送。这里不抓取招聘网站，也不自动打招呼或投递。文中的林示意是**虚构**，不能当事实来源。

`tools/verify_layout.py` 底部 90pt 是按 moderncv 标定的。这份简历写满一页时，末行会落进那条带，脚本可能报页脚冲突。那不是排版错误，不要为了消掉它去加大下边距或删内容。页数看 `verify_pdf.py --pages 1`，再读 PDF。超过 100pt 的空洞仍然算错误。


### 输出位置与终端

上面的 `cd cv && ...` 整行从**仓库根目录**执行，社招与校园模板都一样，不从 `documents/applications/` 执行。若已经在 `cv/`，去掉开头的 `cd cv &&`。归档的 `cv_draft.tex` 是快照；编译原稿仍在 `cv/`。编译结束后回到仓库根目录执行 `/apply` 的 `tools/verify_*.py`，否则会报找不到脚本。`TEXINPUTS` 的 `.` 保留源文件旁资源，`//` 递归搜索模板，末尾分隔符保留 TeX 系统包。

Windows 原生 PowerShell 的路径分隔符是分号，不能直接运行 Bash 的变量赋值。从仓库根目录执行（替换文件名）：

```powershell
Push-Location cv
$PreviousTexInputs = $env:TEXINPUTS
try {
    $env:TEXINPUTS = '.;../templates/cn//;'
    Remove-Item main_<company>_<role>.pdf -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force build | Out-Null
    xelatex -interaction=nonstopmode -halt-on-error -output-directory=build main_<company>_<role>.tex
    if ($LASTEXITCODE -ne 0) { throw '编译失败，请查看 build 中的 log；不要使用旧 PDF' }
    Move-Item build/main_<company>_<role>.pdf . -Force
} finally {
    $env:TEXINPUTS = $PreviousTexInputs
    Pop-Location
}
```

中文字体按 Noto CJK → Windows SimSun / Microsoft YaHei → macOS Songti SC / PingFang SC → Fandol 选择。Noto 的 TTC 固定简体索引和语言；系统字体能否正确嵌入仍要检查 PDF 文本。Linux 安装 `fonts-noto-cjk`；Windows/macOS 可用系统字体或安装 Noto 的 SC 字体。每次确认日志没有 `Missing character`，`pdftotext -layout -enc UTF-8` 能抽出姓名及中文栏目，页数恰好一页。系统字体不可用时按 log 中的具体字体名安装，重启终端后再编译。

中文求职信按 `06-cover-letter-templates.md` 加载 ctex 与共享字体；只用 XeLaTeX 并不会自动支持中文。

内容不足时保留真实留白；尤其学生无实习/奖项时，不为消除 moderncv 的末页空白告警编造经历。继续检查页数、遮挡、断行与中间空洞。可在 `\cnheader` 第二参数写已确认的到岗时间、期望城市；未知则不填。
