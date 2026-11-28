import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillVersionTests(unittest.TestCase):
    def test_entrypoint_matches_latest_release_note(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        notes = (ROOT / "references" / "release-notes.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skill_version = re.search(r"Skill 版本：`(\d+\.\d+\.\d+)`", skill)
        latest_note = re.search(r"^## (\d+\.\d+\.\d+)（", notes, re.MULTILINE)
        self.assertIsNotNone(skill_version)
        self.assertIsNotNone(latest_note)
        self.assertEqual(skill_version.group(1), latest_note.group(1))
        self.assertIn(f"v{skill_version.group(1)}", readme)
        major, minor, patch = map(int, skill_version.group(1).split("."))
        self.assertGreaterEqual(major, 1)
        self.assertLessEqual(minor, 15)
        self.assertLessEqual(patch, 17)

    def test_ec_workspace_uses_local_maintenance_source(self):
        active = [
            ROOT / "SKILL.md",
            ROOT / "README.md",
            ROOT / "references" / "knowledge-base.md",
            ROOT / "references" / "blocker-feedback.md",
            ROOT / "references" / "next-step.md",
        ]
        contents = "\n".join(path.read_text(encoding="utf-8") for path in active)
        self.assertIn("https://dclaw.rouhigh.com", contents)
        self.assertIn("https://api.rouhigh.com", contents)
        self.assertIn("当前 `main`", contents)
        self.assertNotIn("https://dclaw.deepmega.cn", contents)
        self.assertNotIn("https://github.com/zimo528/dclaw-super-agent-porting.git", contents)


if __name__ == "__main__":
    unittest.main()
