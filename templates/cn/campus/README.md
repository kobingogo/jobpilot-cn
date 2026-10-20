# 校招 / 实习一页中文简历

`resume.tex` 是教育优先的骨架，顺序为教育、实习、项目、在校经历/竞赛/奖学金、技能。不要求现职雇主。没有实习、奖项、GPA 或排名就删除对应条目；项目必须保留课程/个人/团队背景，不能伪装成正式工作。预计毕业时间与已获学位应区分。

`example.tex` 是**虚构**示例，程示例不是真人，学校、单位、项目和数字都是编造，邮箱使用 example.com。不要投递或复制其中事实。照片默认关闭。

复用 [上级样式与编译说明](../README.md)，引擎为 xelatex（ctex / xeCJK），单栏，页数必须为 **1**。在本目录测试：

```bash
mkdir -p build
TEXINPUTS=.:..//: xelatex -interaction=nonstopmode -halt-on-error -output-directory=build example.tex
```

`/apply` 先按档案 CV language 选择中文分支，再按 `Career stage: campus` / `intern`（校招/实习）选本骨架；已注册的 `ACTIVE-TEMPLATE` 优先。复制到 `cv/main_<company>_<role>.tex` 后，沿用上级 README 的 `TEXINPUTS=.:../templates/cn//:` 编译命令，从仓库根目录执行，不复制样式文件；Windows PowerShell 用上级说明中的分号分隔符。内容不足时保留真实留白，不编造经历凑版；超过一页先删次要条目。

JD 手工粘贴。不抓取招聘网站，不自动打招呼或投递。
