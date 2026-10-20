"""Claude Code model switching stays a placeholder, not a dead OpenAI config.

The tracked example is .claude/settings.local.example.json. Users copy it to
.claude/settings.local.json (gitignored) and fill the token themselves.
No real key, no .env provider variables, no models.example.json.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / ".claude" / "settings.local.example.json"
DOC = REPO / "docs" / "cn" / "模型配置.md"
GITIGNORE = REPO / ".gitignore"
ENV_EXAMPLE = REPO / ".env.example"
DEAD_MODELS = REPO / "config" / "models.example.json"

ENV_KEYS = [
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
]

BASE_URLS = [
    "https://api.deepseek.com/anthropic",
    "https://api.moonshot.cn/anthropic",
    "https://open.bigmodel.cn/api/anthropic",
]

# Real provider keys, not the YOUR_* placeholders this repo is allowed to track.
REAL_KEY = re.compile(
    r"(?i)(?:^sk-[A-Za-z0-9]|sk-ant-|sk-or-|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})"
)

DEAD_NAMES = (
    "MODEL_PROVIDER",
    "DEEPSEEK_API_KEY",
    "MOONSHOT_API_KEY",
    "ZHIPU_API_KEY",
    "models.example",
)


class ModelSwitchExample(unittest.TestCase):
    def setUp(self):
        self.raw = EXAMPLE.read_text(encoding="utf-8")
        self.settings = json.loads(self.raw)
        self.doc = DOC.read_text(encoding="utf-8")

    def test_example_json_parses_with_seven_env_keys(self):
        self.assertIsInstance(self.settings, dict)
        env = self.settings["env"]
        self.assertEqual(list(env), ENV_KEYS)
        for key in ENV_KEYS:
            self.assertIsInstance(env[key], str)
            self.assertTrue(env[key].strip())
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("api_key", self.settings)
        self.assertEqual(env["ANTHROPIC_BASE_URL"], BASE_URLS[0])
        self.assertEqual(env["ANTHROPIC_MODEL"], "deepseek-v4-pro")

    def test_token_is_a_placeholder_not_a_real_key(self):
        token = self.settings["env"]["ANTHROPIC_AUTH_TOKEN"]
        self.assertIn("YOUR_", token)
        self.assertIsNone(REAL_KEY.search(token), token)
        self.assertIsNone(REAL_KEY.search(self.raw))
        self.assertNotIn("api_key", self.raw)

    def test_doc_lists_three_base_urls_and_privacy(self):
        for url in BASE_URLS:
            self.assertIn(url, self.doc)
        self.assertIn("简历", self.doc)
        self.assertIn("身份证", self.doc)
        self.assertIn("settings.local.json", self.doc)
        self.assertIn("不要提交", self.doc)
        self.assertIn("贴进聊天", self.doc)
        self.assertIn("ANTHROPIC_API_KEY", self.doc)
        self.assertIn("2026-10-20", self.doc)
        self.assertIn("不自动投递", self.doc)

    def test_gitignore_ignores_local_settings_but_not_the_example(self):
        text = GITIGNORE.read_text(encoding="utf-8")
        self.assertIn(".claude/settings.local.json\n", text)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "--", ".claude/settings.local.example.json"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(
            ignored.returncode,
            0,
            "the tracked example must not match .gitignore",
        )
        local = subprocess.run(
            ["git", "check-ignore", "-q", "--", ".claude/settings.local.json"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(local.returncode, 0)

    def test_dead_provider_config_is_gone(self):
        self.assertFalse(DEAD_MODELS.exists())
        env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("docs/cn/模型配置.md", env_text)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        # YOUR_DEEPSEEK_API_KEY is a placeholder and must not count as the old env name.
        for name in DEAD_NAMES:
            pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
            for label, text in (
                (".env.example", env_text),
                ("模型配置.md", self.doc),
                ("settings.local.example.json", self.raw),
                ("README.md", readme),
            ):
                self.assertIsNone(pattern.search(text), f"{name} still in {label}")


if __name__ == "__main__":
    unittest.main()
