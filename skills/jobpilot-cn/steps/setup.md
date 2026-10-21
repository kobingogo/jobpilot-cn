<!-- Migrated from .claude/commands/setup.md; legacy section names retained for regression coverage. -->
# 建立或更新候选人档案

You are running the onboarding setup for the AI Job Search framework. Your goal is to collect the user's professional information and populate all profile files for application drafting. 可直接说「帮我建档」，不需要任何平台专用命令。

There are three paths into setup. Step 0 picks the right one; all three converge on Step 3 (file generation) and Step 4 (confirmation).

---

## Step 0: Welcome & Choose Path

### Language and career-stage routing (all paths, including --section updates)

Before the welcome, use the user's conversation language or explicit language choice. If the user writes Chinese or chooses **中文**, conduct onboarding in Chinese and set **CV language: 中文** by default. If they write English, keep the English interview and **CV language: English** default. An explicit CV-language choice or an existing populated CV-language field wins; an update-only run must not silently reset it. If there is no language signal, offer **中文 / English** before the path choice. Translate every prompt and summary below, including the privacy preflight, into the selected conversation language.

For Chinese users, present these three choices in Chinese: **A 读取 documents/ 资料 / B 导入一份简历 / C 从零访谈**. Explain the minimum needed: 姓名、城市、教育/经历（在校项目也算）、目标岗位、职业阶段、可到岗时间。期望薪资可填写区间或标「暂不确定」；电话/邮箱可暂留占位符，正式导出前再确认。LinkedIn/GitHub、GPA/排名、照片、奖项、推荐人、行为测评和家庭情况均可跳过。不要追问身份证、密钥或无关隐私。

Ask **职业阶段：社招 / 校招（应届）/ 实习**. Record the normalized **Career stage: experienced / campus / intern** in both `CLAUDE.md` and `01-candidate-profile.md`. Separately confirm **Student status: true / false / unknown**, **Graduation year** (expected or actual four-digit year), and **Availability** (date; internship days/week and months). Do not infer current enrollment from a campus application or a graduation year. If importing documents in Path A/B, extract supported facts and ask only for missing or conflicting values; do not invent a current employer for a student. Apply this routing before any Path A skip or --section shortcut.

For CV language 中文 (`Chinese` / `zh` also count), choose `templates/cn/resume.tex`; for **Career stage: campus / intern** (校招/实习), choose `templates/cn/campus/resume.tex` instead. Read `templates/cn/README.md` and the campus README when applicable. An existing `ACTIVE-TEMPLATE` registration still wins. Point to `docs/cn/` and to `docs/cn/校招实习面试准备.md` for campus/intern profiles. English users keep the stock moderncv path unless they explicitly choose another language/template.

Chinese-market onboarding uses **manually pasted JDs**: no scraper, portal CLI setup, automatic greeting or applying. Skip Path C Section 9's portal enablement and search-query suggestions for this path; collect target roles/cities and CV language only. Legacy portal examples are outside this Skill. Do not enable them for this workflow.

If `user input` contains `--section <name>`, skip directly to that section in Path C for an update-only flow. Do not run the path-selection prompt below.

新用户默认只写被忽略的 `profile/` JSON，跳过下面针对旧版 tracked 档案的远端检查。
只有用户选择更新历史 tracked Markdown 时才执行这一兼容检查；不需要 gh 工具才能完成建档。

Otherwise, first check where this working copy would publish to — **before anything is
written, not after** (the Step 4 privacy note fires only once every file is already on
disk, which is too late to inform the decision). Run `git remote get-url origin`; if the
command fails (no remote, or not a git checkout), skip this check silently. If there is
a GitHub `origin`, check it with `gh repo view <owner/repo> --json visibility,isFork`
when `gh` is available. If the origin is a **public fork** of the template — or its
visibility cannot be determined — warn now and wait:

> **Heads-up before we start:** your `origin` points at `<owner/repo>`, which is a
> public GitHub fork. This setup writes your personal data (name, contact details,
> employment history, salary expectations) into **tracked** files, and anything you
> commit *and push* to that fork is visible to anyone. Two safe options: keep your
> profile commits local and never push them, or push to a **private** repository
> instead — SETUP.md section 8 has the two-minute private-remote recipe. Want to
> continue with the setup?

Wait for the user's confirmation before showing the path prompt. A private origin, no
origin, or a non-fork remote needs no warning — continue silently.

Then scan the `documents/` folder. Use the shell or a recursive file listing of `documents/**/*` and count files per subfolder (`cv/`, `linkedin/`, `diplomas/`, `references/`, `projects/`, `applications/`).

Then welcome the user with a single message that lists three paths. The wording changes based on what was found.

**If `documents/` has files** in one or more subfolders, lead with Path A:

> **Welcome to the AI Job Search setup!**
>
> I'll help you build your professional profile so the host agent can evaluate job postings, tailor CVs, write cover letters, and prepare you for interviews.
>
> I see files in your `documents/` folder: [list per subfolder, e.g. "2 in cv/, 1 in linkedin/, 3 in references/"]. Three ways to start:
>
> **Path A: Read my documents folder** (recommended for what you have) - I'll read everything in `documents/`, cross-reference for consistency, and build your profile from real source materials. Idempotent and safe to re-run as you add more documents.
>
> **Path B: Single CV import** - Paste or @-mention a single CV/resume here. I'll extract it and ask follow-up questions for what's missing.
>
> **Path C: Interview mode** - I'll walk you through structured questions section by section.
>
> Which would you like?

**If `documents/` is empty or missing**, surface Path A as a "do this if you have materials" option:

> **Welcome to the AI Job Search setup!**
>
> I'll help you build your professional profile so the host agent can evaluate job postings, tailor CVs, write cover letters, and prepare you for interviews.
>
> Three ways to start:
>
> **Path A: Documents folder** (best signal if you have several materials) - Drop your CV / LinkedIn export / diplomas / reference letters / project summaries in the `documents/` folder, then say "go". I'll read everything and build your profile from it. See `documents/README.md` for the folder layout.
>
> **Path B: Single CV import** - Paste or @-mention a single CV/resume here. I'll extract it and ask follow-up questions for what's missing.
>
> **Path C: Interview mode** - I'll walk you through structured questions section by section. Good if you're starting from scratch.
>
> Which would you like?

Wait for the user's choice. If they pick A but the folder is still empty, tell them what to add (point at `documents/README.md`) and stop.

---

## Path A: Documents Folder

Reads structured documents in `documents/`, cross-references them for consistency, and merges extracted data into existing profile methodology files when present. Read-before-write and idempotent: changes already present will not be proposed again.

Follow these steps **exactly in order**.

### Step A1: Inventory

Use the shell or a recursive file listing of `documents/**/*` to scan the full tree. Print:

```
## Documents Found

**cv/**: [list files, or "(empty)"]
**linkedin/**: [list files, or "(empty)"]
**diplomas/**: [list files, or "(empty)"]
**references/**: [list files, or "(empty)"]
**projects/**: [list files, or "(empty)"]
**applications/**: [list subfolders with their files, or "(empty)"]

I will read these and cross-reference before proposing any changes.
```

If every subfolder is empty, stop and tell the user to populate the folder. Point at `documents/README.md` for the layout.

### Step A2: Read Existing Skill Files

Read these in parallel before extracting anything. You must know what is already there to make the merge intelligent.

- `.claude/skills/job-application-assistant/01-candidate-profile.md`
- `.claude/skills/job-application-assistant/02-behavioral-profile.md`
- `.claude/skills/job-application-assistant/03-writing-style.md`
- `.claude/skills/job-application-assistant/04-job-evaluation.md`
- `.claude/skills/job-application-assistant/05-cv-templates.md`
- `.claude/skills/job-application-assistant/06-cover-letter-templates.md`
- `.claude/skills/job-application-assistant/07-interview-prep.md`

Hold this content in context throughout Path A. Do not re-read.

### Step A3: Parse Documents

Read each document found in Step A1. Process subfolders in this order: `cv/`, `linkedin/`, `diplomas/`, `references/`, `projects/`, `applications/`.

**`cv/` documents:** name, contact (email, phone, LinkedIn, GitHub), education (degree, institution, dates, thesis), work experience (title, company, dates, location, bullets), skills, languages (with any stated proficiency), publications, awards, profile/summary.

**`linkedin/` documents:** About/summary section (full text, used for behavioral inference), work experience, education, skills and endorsements, **Languages section** (language name + self-rated proficiency level, e.g. "Spanish - Native or bilingual proficiency" - a high-confidence structured source, feeds the Language Gate in `04-job-evaluation.md`), certifications, volunteer work, publications, recommendations received (full text). If multiple LinkedIn exports are present, use the most recently modified file.

**`diplomas/` documents:** official degree title and level, institution name (official spelling), graduation date, grade or distinction or GPA if visible.

**`references/` documents:** referee name, title, organization; full text of the letter (extract specific quotes); competency language used.

**`projects/` documents:** project name, summary/description, problem domain, tech stack (languages, frameworks, tools), key technical challenges and architectural decisions, measurable outcomes/metrics (e.g. users, performance, stars, impact).

**`applications/<company>_<role>/` subfolders:**
- `job_posting.md`: role title, company, required skills, experience level, sector, role type
- `cover_letter.tex`: opening structure, body structure, bullet style, closing, recurring phrases
- `cv_draft.tex`: profile statement, section ordering, framing for this role type
- `outcome.md`: status (in_progress/hired/offer_declined/rejected/no_response/interview_only), interview stages, notes. Skip `in_progress` applications for calibration — they have no final signal yet.

After reading, proceed to Step A4 without intermediate output. The user sees a complete picture in Step A6.

### Step A4: Cross-Reference Check

Before mapping anything to skill files, check for inconsistencies:

- Date mismatches between CV / LinkedIn / diploma
- Title mismatches across documents for the same role
- Education mismatches (degree name, graduation date)
- Employer name variations

If inconsistencies are found, present them as a numbered list and wait for the user to resolve each one before continuing:

```
## Cross-Reference Issues Found

These need to be resolved before I continue. For each one, tell me which version is correct.

1. **Role title mismatch - [COMPANY]:**
   CV says: "[TITLE_A]"
   LinkedIn says: "[TITLE_B]"
   Which is correct?

2. ...
```

If no inconsistencies, state "No cross-reference issues found." and continue.

### Step A5: Build Change Sets

For each skill file, compare extracted document content against the current file content from Step A2. Build two buckets.

**Additive changes:** entirely new content not in the skill file in any form. Examples: a certification not in `01-candidate-profile.md`, a new independent project not in `01-candidate-profile.md`, a new endorsement skill, a referee not yet listed, a new behavioral quote from a reference letter, a new award.

**Conflicting changes:** content that touches something already in a skill file but disagrees. Examples: a different date range for an existing job, a different job title for the same role, a different graduation date than what is recorded.

**Inference rules** (apply when populating from inferred sources):

- **`01-candidate-profile.md` (`## Independent Projects`):** Source is `projects/` documents. Extract structured project entries formatted as `- **[PROJECT_NAME]**: [DESCRIPTION with tech stack and measurable outcome]`. Ground all claims in the document text.
- **`02-behavioral-profile.md`:** Source is LinkedIn About + recommendation letters. Extract recurring themes, adjectives, phrases about how the candidate works. Add only to the "Strongest Behaviors", "How You Work Best", or "Management Style Preferences" sections (the shipped file's `##` headings). Do not overwrite existing scored assessments. Always label inferred additions: *[Inferred from LinkedIn About / Reference letter - review before relying on this]*
- **`03-writing-style.md`:** Source is `cover_letter.tex` files. Extract recurring patterns. Add as observations under "## Patterns Observed in Past Applications". Do not modify existing rules. Only add if 2+ cover letters show a genuine pattern.
- **`04-job-evaluation.md`:** Source is `job_posting.md` + `outcome.md` pairs. If an application reached interview or offer: note role type and sector as a confirmed strong-fit signal. If 2+ applications repeat a no-response or rejection pattern: note it. Add findings under "## Calibration from Past Applications". Do not modify the existing scoring framework.
- **`05-cv-templates.md`:** Source is `cv_draft.tex` files. Extract any profile statement that does not already appear in templates. Label with: *[Used for: <company>_<role>]*. **Ground before extracting:** archived drafts are tailored outputs, not source documents - verify every factual claim in an extracted statement (titles, employers, metrics, technologies) against `01-candidate-profile.md` and drop or correct any claim the profile does not support, keeping only the framing. A tailored draft that drifted must never become a template future applications start from.
- **`06-cover-letter-templates.md`:** Source is `cover_letter.tex` files. Extract opening patterns, bullet structures, closing formulations. Add only what is structurally distinct from existing templates.
- **`07-interview-prep.md`:** Source is CV bullets, LinkedIn descriptions, reference letter quotes. Identify achievements not yet covered by an existing STAR example. Do NOT draft full STAR examples. Add stubs under "## STAR Candidates (Complete Manually)":

```markdown
### [Achievement title]
**Source:** [CV / LinkedIn / Reference letter - role/company]
**What happened:** [one sentence]
**Why it matters:** [interview question types this could answer]
**S/T/A/R stub:**
- Situation:
- Task:
- Action:
- Result:
```

### Step A6: Present and Confirm Changes

Present the full change set before writing anything.

**Additive changes** (single grouped list, organized by target file):

```
## Proposed Additive Changes

### 01-candidate-profile.md
- [ ] New certification: [title], [issuer], [date] - extracted from LinkedIn
- [ ] New independent project: [PROJECT_NAME] - [description, tech stack, key outcome]
- [ ] New reference: [name, title, company]
  Quote: "[relevant quote]"

### 02-behavioral-profile.md
- [ ] New behavioral observation [labeled as inference]: "[phrase]"

[and so on per file]
```

Then ask:

> **Apply all additive changes?** These add new content without touching anything already in the files.
> Reply **yes** to apply all, or list the numbers you want to skip.

Wait for the response. Apply only the confirmed items.

**Conflicting changes** (one at a time):

```
## Conflict 1 of [N]: Job title - [COMPANY]

**Current in 01-candidate-profile.md:**
[TITLE_A] - [COMPANY] ([START]-[END])

**Proposed (from LinkedIn export):**
[TITLE_B] - [COMPANY] ([START]-[END])

Options:
  [keep] Keep the existing text
  [replace] Replace with the version from the document
  [manual] I'll edit this myself - skip for now
```

Wait for the user's choice on each conflict. If no conflicts, state "No conflicting changes found." and skip this section.

### Step A7: Write Confirmed Changes and Fill Gaps

Apply the confirmed changes with file read/write. Make targeted edits only. Do not rewrite entire files. State which changes were applied per file. If a file has no confirmed changes, state "No changes made to [filename]."

Documents cover skills, experience, education, references, and behavioral signal. They do not cover everything `/apply` and `/scrape` need. After the writes, ask follow-up questions for gaps:

- Career goals and target role types
- What excites the user in their next role
- Deal-breakers and must-haves
- Languages you work in professionally, with proficiency levels (only if not already extracted from `cv/` or `linkedin/` above) - this feeds the Language Gate in `04-job-evaluation.md`, so ask directly rather than skipping it
- Salary expectations / baseline (optional)
- Commute or location constraints (if not visible from CV)
- Target roles, cities and CV language (Path C Section 9)

Then proceed to Step 3 for local profile generation and compatible existing records. Step 3 will detect that the seven skill files are already populated and skip those substeps.

---

## Path B: Single CV Import

If the user provides a single CV/resume:

1. Read the document thoroughly.
2. Extract all structured information: name, contact, education, experience, skills, languages, publications, awards.
3. Present a summary of what was extracted.
4. Ask follow-up questions for gaps (behavioral profile, career goals, deal-breakers, languages and proficiency levels if not already extracted, salary expectations, references).
5. Proceed to Step 3 (file generation).

---

## Path C: Interview Mode

Walk through each section conversationally. Ask questions naturally, not as a form. Let the user answer in their own words and you'll structure the data.

### Section 1: Identity & Contact
Ask about:
- Full name
- Location (city, country)
- Phone, email, LinkedIn, GitHub
- What languages they work in professionally, and roughly what level in each (native, fluent, conversational, a CEFR letter like B2 - whatever's natural for them to describe, doesn't need to be precise). Worth explaining why: a posting requiring a language they don't list at all gets auto-excluded later by the Language Gate, while one asking for a higher level in a language they do list gets flagged for their own judgment instead of silently passed or rejected - so it's worth being honest here rather than optimistic.
- Career stage, student status, graduation year and availability per Step 0 (all paths)
- Current employment status (students may have no employer)
- Family/commute constraints (if any)

### Section 2: Education
For each degree:
- Level (PhD, MSc, BSc, etc.), field, institution, years
- Thesis topic (if applicable)
- Key coursework or topics

Also ask about certifications (online courses, professional certs).

### Section 3: Professional Experience
For each role (most recent first):
- Job title, company, dates, location
- Key responsibilities (3-5 bullets)
- Key achievements or projects
- Technologies/tools used

For campus/intern profiles, ask about internships, coursework/projects, campus activities, competitions and scholarships instead of requiring full-time employment. GPA/ranking are optional; omit unsupported fields. Also ask about independent projects, freelance work, or side projects.

### Section 4: Technical Skills
- Programming languages + proficiency level
- ML/AI frameworks and tools
- Domain expertise
- Software tools and platforms
- Any other technical skills

### Section 5: Publications & Awards (optional)
- Peer-reviewed papers, conference presentations
- Hackathons, competitions, awards
- Skip if not applicable

### Section 6: Behavioral Profile (optional)
If they have a formal assessment (PI, DISC, Myers-Briggs, StrengthsFinder):
- Ask them to describe or share the results

If not, ask behavioral questions:
- "What work environments do you thrive in?"
- "What drains your energy at work?"
- "How do you prefer to work in teams?"
- "How do you make decisions, quickly or deliberately?"
- "What's your communication style?"
- Synthesize answers into a behavioral profile

### Section 7: Career Goals & Preferences
- Target roles and industries
- What excites you in work
- Deal-breakers and must-haves
- Salary expectations/baseline (optional)
- What environments to avoid
- Commute/location constraints

### Section 8: References (optional)
For each reference:
- Name, title, company, email, phone
- Relationship to the user

### Section 9: Job Search Configuration

仅记录目标岗位、城市、语言和确认后的筛选阈值；不启用门户或联网搜索。
中文用户默认 CV language: 中文，英文用户保留 English；没有语言信号先问。


---

## Step 3: Generate Profile Files

Once data collection is complete, generate or finish populating the following files. **For Path A**, the seven skill files are already populated by Step A7; check each before writing and skip if its content is no longer placeholder text.

### 1. Update `CLAUDE.md`
Replace all `[PLACEHOLDER]` tokens with the user's actual information. Keep the structure, workflow, and verification checklist intact.

### 2. Populate `01-candidate-profile.md` *(Path B and C; skip if Path A populated it)*
Write the full candidate profile with structured sections: Identity (including Languages, with levels, Career stage, Student status, Graduation year, Availability), Education, Professional Experience, Independent Projects, Technical Skills, Publications, Awards, References.

### 3. Populate `02-behavioral-profile.md` *(Path B and C; skip if Path A populated it)*
Write the behavioral profile based on assessment results or synthesized answers.

### 4. Update `04-job-evaluation.md` *(Path B and C; skip if Path A populated it)*
Replace skill match areas with the user's actual skills:
- Strong match areas: [their primary skills]
- Moderate match areas: [their secondary skills]
- Weak match areas: [skills they lack]

Update career goals and motivation filters with their actual preferences.

### 5. Update `05-cv-templates.md` *(Path B and C; skip if Path A populated it)*
Add role-specific profile statement templates based on their background, and personalise the contact block inside the file's LaTeX template: replace `[FIRST_NAME]`, `[LAST_NAME]`, `[YOUR_ADDRESS]`, `[YOUR_PHONE]`, `[YOUR_EMAIL]`, `[YOUR_LINKEDIN_URL]` and `[YOUR_GITHUB_URL]` (and `[YOUR_NAME]` in the PDF title) with their actual details. Check this block whichever path ran - Path A extracts profile statements from documents, not the contact block. `/apply` builds every tailored CV from this template, so a placeholder left here reaches a compiled document.

### 6. Update `06-cover-letter-templates.md` *(all paths - Path A does not fill this block)*
Personalise the contact line and the signature inside the file's LaTeX template: replace `[YOUR_NAME]`, `[YOUR_EMAIL]`, `[YOUR_PHONE]` and `[YOUR_LINKEDIN_URL]` in the `\namesection{}` line, and `[YOUR_NAME]` in `\signature{}`. Path A merges only structural patterns (openings, bullets, closings) into this file, never the contact block. `/apply` compiles every cover letter from this template.

### 7. Update `07-interview-prep.md` *(Path B and C; skip if Path A populated it)*
Create STAR examples from their actual experience (aim for 3-4 where supported). For campus/intern profiles, use real coursework, projects, internships and campus contributions; if evidence is incomplete or fewer examples exist, leave questions/stubs rather than inventing employment or results. Path A leaves STAR stubs under "## STAR Candidates (Complete Manually)" rather than full examples; if any stubs are present, mention them in Step 4 so the user knows to flesh them out.

### 8. Update `cv/main_example.tex`
Use the template selected in Step 0 to populate `cv/main_example.tex`: CV language 中文 uses `templates/cn/resume.tex`, or `templates/cn/campus/resume.tex` for campus/intern; CV language English keeps moderncv. Respect any explicit language choice even when conversation language differs. An active custom template wins. Replace placeholder personal data with their actual name, contact info, and add their education and most recent experience entries. Do not personalize the shipped templates or fictional examples in `templates/cn/`. Students without employment use projects/campus evidence, not invented employers. Chinese compile command and exactly-one-page requirement are in `templates/cn/README.md`; reuse its shared style path.

### 8a. Chinese scoring settings (all Chinese paths)
Create or update gitignored `config/cn_filters.json` from the user's **confirmed thresholds only**, never from the fictional example numbers. Leave unknown values null or sections empty. Preserve unrelated existing settings on section updates. Map Career stage to `campus.mode` (`campus`, `intern`, or `experienced`), Graduation year to `campus.graduation_year`, and Student status true/false/unknown to `labor.candidate_is_student` true/false/null. Set `salary.min_daily` in **元/天** for internship expectations, separately from full-time `salary.min_monthly_k` and `min_months`; do not convert daily pay to monthly. Keep name, contacts, credentials and birth date out of this config. This flag does not infer student status from the JD; explicit false takes precedence for contract hints.

Round 5 opt-ins: follow [第五轮产品决策](../../../docs/cn/第五轮产品决策.md). Do not enable new comparisons merely because Availability text exists. Only when the user wants these reminders, copy confirmed internship availability to `availability.days_per_week` (integer 1–7), `availability.duration_months` (positive months), `availability.start_date` (`YYYY-MM-DD`). Each defaults to null; mismatches only flag, never deduct points or reject. Unknown dates stay null; never invent a year. For a separate annual-package reminder, `salary.min_annual_total_k` is positive **千元/年**, default null, only explicit annual totals, mismatch only flag. `salary.compare_annual_as_monthly` defaults true (legacy annual /12 vs monthly floor); set false only at the user's explicit choice to stop that comparison. It does not disable `min_months`, daily or actual monthly salary checks. Never infer guaranteed bonuses from pay-month counts.

`employer.detect_self_description` defaults false; true displays explicit JD self-description with evidence, unverified and info-only, never scored or filtered. `jargon.flexible_work_overtime_only` defaults false (legacy 6-point deduction); true restricts the flexible-work deduction to the same sentence's non-negated overtime wording. 965 is info-only, with no bonus or risk offset. Keep absent keys absent or at these defaults unless the user opts in; never overwrite an existing choice during section updates. Do not put employer preferences or inferred candidate eligibility into these fields.

### 9. 保存本地档案并保留兼容资料

新用户运行 `python tools/jobpilot.py init`，填写 `profile/candidate.example.json` 的副本，
然后运行 `python tools/jobpilot.py setup-profile write --in profile/confirmed.json`。
不传 `--in` 则读标准输入中的 JSON。更新会合并顶层字段，数组以本次完整值替换；
未提供字段保留，student_status 不由职业阶段推断。写入 `profile/candidate.json`
和 `config/cn_filters.json`；原有薪资底线及用户 opt-in 不覆盖。

JSON 最少需 name、city、career_stage；其他字段：student_status（true/false/null）、
graduation_year（四位年份/null）、availability、phone、email、summary、skills（字符串），
education、experience、projects（字符串数组，每条是已确认事实）。示例都是虚构，未知留待确认。
CLI 不调用模型，不自动抽取 PDF 或改写历史 Markdown。宿主完成提取、确认与同步。

新建档案以本地 JSON 为事实来源；上述 1–8 是已有 Markdown 档案的兼容更新说明，
按需使用，不要求首次使用就创建所有历史文件。使用已有档案时先读取、合并，
如已确认的事实互相矛盾，先提问，不能让占位符覆盖真资料。新事实写回 JSON；
如纠正既有 Markdown 中的事实，同步该处，避免未来误判。不要改写发货模板或虚构示例。


---

## Step 4: Confirm & Next Steps

Present a summary in the Step 0 conversation language. For Chinese users, replace the English Try it out block below with:

> 设置完成。CV language: [已选语言，默认中文]；Career stage: [已确认阶段]；模板：[选中的 templates/cn/ 路径或已激活自定义模板]。
> 中文使用说明见 `docs/cn/`；校招/实习面试见 `docs/cn/校招实习面试准备.md`。
> 下一步：`/apply` 后手工粘贴完整 JD。生成的是待审阅草稿，用户自己发送；不自动打招呼或投递。
> 有面试后运行 `/interview <公司>`，以后可用 `/setup --section search` 更新偏好。

Do not show `/scrape`, a Danish URL or portal installation as the next step on this Chinese path. List only the files actually updated; retain the privacy note in Chinese.

English/international summary:

Summarize the files actually changed, including `06-cover-letter-templates.md` when updated.
**Privacy note:** legacy Markdown profile files are tracked by git; keep them local or in a private repository.
New local JSON lives under gitignored `profile/`. No credentials belong in either profile.
Next: paste a full JD for the application step; no portal setup is needed.

If Path A left any STAR stubs in `07-interview-prep.md`, also note:

> Path A flagged [N] STAR candidate stubs in `07-interview-prep.md` that need your situation/task/action/result details before you use them in interviews.

---

## Design Principles

- Three onboarding paths converge on the same skill files. Step 0 picks the right path based on what's in `documents/`. Steps 3 and 4 are shared.
- Path A is read-before-write and idempotent. Re-running it as documents are added does not duplicate or overwrite existing content; conflicts are surfaced for explicit resolution.
- Path A labels inferred behavioral or style additions so the user can review them critically before relying on them.
- Each section in Path C is a natural conversation, not a form. The user can skip optional sections.
- Synthesize answers into structured formats (the user does not need to know markdown or LaTeX).
- Can be re-run with `--section <name>` to update specific sections (e.g., `/setup --section search` to reconfigure job search queries without re-doing the full profile).
- Section 9 (search) in Path C, and the equivalent follow-up questions in Path A, proactively suggest role types the user may not have considered.
- At the end, ask the user to provide a complete local JD in their preferred language.
