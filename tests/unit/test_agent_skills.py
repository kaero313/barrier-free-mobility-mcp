from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"


def test_skills_have_frontmatter_matching_directory_name() -> None:
    skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))

    assert skill_files
    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\n"), path
        metadata = yaml.safe_load(text.split("---", 2)[1])
        assert metadata["name"] == path.parent.name
        assert metadata["description"].strip()


def test_codex_skill_directory_links_to_claude_skills() -> None:
    link = PROJECT_ROOT / ".agents" / "skills"

    # Codex lists project skills only through this link; a plain-file checkout hides them.
    assert link.is_symlink()
    assert link.resolve() == SKILLS_DIR.resolve()
