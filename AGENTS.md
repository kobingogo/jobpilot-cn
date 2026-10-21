---
framework_version: 1.0.0
---

# Agent Guidelines: AI Job Search

This workspace is structured to manage job search activities, scraper tools, CVs, cover letters, and interview preparation.

## Thin-Pointer Design (Single Source of Truth)

To prevent duplication and configuration drift across different AI agent frameworks (Claude Code, Google Antigravity, Codex, Cursor, Gemini CLI, etc.), this workspace uses a unified thin-pointer design. All agent runtimes should load the canonical specifications and candidate profiles from the files and directories below:

1. **Personal Candidate Profile:**
   - New confirmed candidate profiles live in local, gitignored `profile/candidate.json`. Existing profiles in [CLAUDE.md](CLAUDE.md) and the methodology files under [.claude/skills/job-application-assistant/](.claude/skills/job-application-assistant/) (specifically `01-*.md` etc.) remain compatible sources; read and reconcile them before updating.
2. **Canonical Chinese Workflow (any local agent):**
   - Start with [skills/jobpilot-cn/SKILL.md](skills/jobpilot-cn/SKILL.md), then read only the matching `steps/` file. It works directly from the repository root with shell and file read/write.
   - Use [tools/jobpilot.py](tools/jobpilot.py) for local deterministic operations. New confirmed profiles live in gitignored `profile/candidate.json`; existing Markdown profiles above remain compatible sources. Resolve conflicts before merging; placeholders and fictional examples are never facts.
   - `.claude/commands/{setup,apply,interview,rank}.md` route the Chinese/local path to the Skill and retain the full upstream international Claude Code workflows, including posting fetch, portal CLI escalation, subagents and company research. Those international workflows remain outside the Chinese Skill.
   - For the Chinese/local Skill path, JD input is a user-pasted local file or stdin. Never fetch job sites, send greetings or submit applications on that path. Use the host agent's model; keep credentials in its own configuration.
   - Installation and host configuration: [安装与使用（各平台）](docs/cn/安装与使用（各平台）.md).
3. **Portal Search Skills:**
   - Job-portal search CLIs live under [.agents/skills/](.agents/skills/) in the portable Agent Skills format (with a `SKILL.md` per portal). Codex and Antigravity discover these automatically; the `/scrape` workflow in [.claude/skills/job-scraper/](.claude/skills/job-scraper/) orchestrates them.
