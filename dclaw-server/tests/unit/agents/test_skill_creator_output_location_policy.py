from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_builtin_skill_creator_declares_safe_output_location_policy():
    zh = (ROOT / "src/qwenpaw/agents/skills/skill_creator-zh/SKILL.md").read_text(
        encoding="utf-8"
    )
    en = (ROOT / "src/qwenpaw/agents/skills/skill_creator-en/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "当前任务工作目录" in zh
    assert "相对路径" in zh
    assert "绝对路径" in zh
    assert "skills/" in zh

    assert "current task workspace" in en
    assert "relative path" in en
    assert "absolute path" in en
    assert "skills/" in en


def test_builtin_skill_creator_forbids_shell_file_operations():
    zh = (ROOT / "src/qwenpaw/agents/skills/skill_creator-zh/SKILL.md").read_text(
        encoding="utf-8"
    )
    en = (ROOT / "src/qwenpaw/agents/skills/skill_creator-en/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "execute_shell_command" in zh
    assert "rm" in zh
    assert "mv" in zh
    assert "write_file" in zh

    assert "execute_shell_command" in en
    assert "rm" in en
    assert "mv" in en
    assert "write_file" in en
