# 建立或更新候选人档案

本步骤使用当前宿主模型和本地文件。所有命令从仓库根目录运行，使用 Python 3.10+：
示例写 `python3`；若只有 `python`，先确认它是 Python 3 再替换；Windows 使用 `py -3`。

## 选择工作区与资料来源

默认 workspace 是仓库根目录。用户指定隔离目录时，后续每条支持工作区的命令都带
`--workspace <目录>`；文中 `profile/`、`config/`、`documents/`、`company_research/`
及 `job_search_tracker.csv` 均相对该工作区。隔离时不读取仓库所有者的个人档案或追踪表。
仓库中的工具、方法说明和模板仍从仓库根目录读取。

```bash
python3 tools/jobpilot.py init --workspace /tmp/fictional-work
```

`/tmp/fictional-work` 仅为虚构演练路径，实际使用用户选定的目录，Windows 换成本地路径。

先读 workspace 中已有的 `profile/candidate.json`。如有旧档案，按需读取 `CLAUDE.md`
的 Candidate Profile、`.claude/skills/job-application-assistant/01-candidate-profile.md`
及 `cv/main_example.tex`，核对事实再合并；未指定隔离目录时才使用仓库内的这些兼容资料。
模板占位符、虚构例子不算事实，冲突先向用户确认，不能覆盖已有真实信息。

按用户语言交流，中文默认 CV language: 中文；已有语言选择或明确要求优先。
用户已经给出来源与事实时直接提取、补问缺项；否则提供三条路径：

- A 读取工作区 `documents/` 中的资料：适合已有多份材料。
- B 导入用户提供的一份简历。
- C 从零访谈：适合还没有简历的用户。

统计和读取 `documents/` 时只算实际资料文件，忽略 `.gitkeep`、README、隐藏文件和空目录；
只有 `.gitkeep` 的目录视为空，不推荐为“已有资料”。没有材料时说明如何添加，或继续访谈。
不要为了选择路径重复索取用户已经提供的信息。

## 提取、访谈与核对

按需读取资料，记录每项事实来源，先核对日期、学校、学位、雇主、职称、技能、指标及个人贡献。
`documents/applications/` 里的旧稿不能自行升级为已确认的新事实；结果或面试反馈同样需区分事实与推测。

最小信息：姓名、城市、教育/经历（在校项目也算）、目标岗位、职业阶段、可到岗时间。
分别确认以下信息，不能互相推断：

- Career stage: experienced / campus / intern（社招 / 校招 / 实习）。
- Student status: true / false / unknown（是否在读）。校招或毕业年份不能证明仍在读。
- Graduation year: 四位毕业年份，实际或预计应明确区分。
- Availability: 到岗日期；实习还可记录每周天数与持续月数。

逐项收集教育、工作/实习、课程/个人/团队项目、技术技能及语言水平。学生没有雇主不构成缺陷；
保留项目背景，不把项目算成任职年限。STAR 只整理已有证据，缺少贡献或结果时记录问题，不编数字。
可选收集职业方向、城市/通勤、薪资底线、工作偏好、行为风格及推荐人。
电话/邮箱可以暂缺；LinkedIn/GitHub、GPA/排名、照片、奖项、测评均可跳过。
不索取身份证、密钥或无关隐私，不启用招聘门户、联网核验、打招呼或投递。

可以按需参考 `.claude/skills/job-application-assistant/02-behavioral-profile.md`、
`03-writing-style.md`、`04-job-evaluation.md` 和 `07-interview-prep.md` 的本地方法。
这些文件中的联网公司核验要求不适用于本中文路径：只使用用户提供的材料与已确认事实；
公司说法不明时在 notes/review 文件标「待确认」，不能写进求职信。

## 保存档案与筛选配置

新用户只需 JSON，不要求创建或改写历史 Markdown、`cv/main_example.tex` 或共享模板。
建档只保存事实和偏好；针对岗位的简历/求职信在 apply 步骤生成，统一放到工作区
`documents/applications/<company>_<role>/`。已有主简历是兼容事实来源，不是新申请的输出。

```bash
python3 tools/jobpilot.py init
python3 tools/jobpilot.py setup-profile write --in profile/confirmed.json
```

隔离时两条命令均加 `--workspace <目录>`，`--in` 指向该目录的确认稿。
初始化的 `profile/candidate.example.json` 是空白示例，先填写副本，再保存为 confirmed.json。
不传 `--in` 则从标准输入读取 JSON；Windows 推荐文件方式。

JSON 至少包含 name、city、career_stage。其他字段：student_status（true/false/null）、
graduation_year（四位整数/null）、availability、phone、email、summary、skills（字符串），
education、experience、projects（字符串数组，每条只写已确认事实）。未知布尔/年份用 null，
未知可选字段省略；需要追问的内容另存 `profile/setup_summary.md`，不要把问题当成履历事实。

CLI 合并顶层字段，数组以此次完整值替换；未提供字段保留。
写入 `profile/candidate.json` 和 `config/cn_filters.json`，自动同步职业阶段、届别与在读状态，
保留原有薪资与 opt-in。宿主负责提取、确认以及必要的旧档案定点同步；CLI 不改写 Markdown。
新确认事实及时写回 JSON；纠正既有档案事实时同步相关处，避免下次产生冲突。
个人资料保持 gitignored，不提交。

其他筛选阈值由宿主按用户确认的选择写入工作区 `config/cn_filters.json`，
不能照抄 `config/cn_filters.example.json` 的虚构数字：

- 学历、院校、年龄、城市、户籍只记录已确认的规则；未知留 null 或空段。
- 社招 `salary.min_monthly_k` 是千元/月，`min_months` 是薪数；实习 `min_daily` 是元/天，
  不将日薪折月薪。年包不证明保证奖金或月薪。
- `campus.mode`、`campus.graduation_year` 与 `labor.candidate_is_student` 按档案同步。
- 第五轮可选项见 [第五轮产品决策](../../../docs/cn/第五轮产品决策.md)：
  `availability.days_per_week`、`duration_months`、`start_date` 和 `salary.min_annual_total_k`
  默认 null，仅明确需要提示时开启；失配只 flag，不扣分或拒绝。
  `salary.compare_annual_as_monthly` 默认 true，只有用户选择时才关闭。
  `employer.detect_self_description` 与 `jargon.flexible_work_overtime_only` 默认 false。
  不因为档案有到岗文字就开启比较，更新时不重置既有选择。

## 确认与下一步

展示档案摘要、事实来源、缺项/冲突和实际更新的文件。未确认内容只留在档案摘要或 notes 中。
中文社招模板为 `templates/cn/resume.tex`，校招/实习为 `templates/cn/campus/resume.tex`；
已激活的自定义模板或用户明确选择优先。不要改写发货模板或复制虚构例子作为事实。

下一步请用户提供完整本地 JD，进入同目录 apply.md；面试准备读取 interview.md。
不把建档完成说成已生成正式 PDF 或已投递。历史 Markdown 可能被 git 跟踪，个人修改不提交。
