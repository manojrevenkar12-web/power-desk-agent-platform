import pytest

from powerdesk.skills import SkillError, catalogue_prompt, load_skills, parse_skill
from powerdesk.tools.specs import BY_NAME


def test_every_skill_follows_the_spec_and_uses_real_tools():
    skills = load_skills()
    assert len(skills) == 6
    for s in skills.values():
        assert s.allowed_tools and set(s.allowed_tools) <= set(BY_NAME), s.name
        assert 1 <= len(s.description) <= 1024


def test_progressive_disclosure_keeps_bodies_out_of_the_prompt():
    skills = load_skills()
    prompt = catalogue_prompt(skills)
    for s in skills.values():
        assert s.name in prompt and s.body[:80] not in prompt


def test_bad_skill_is_rejected(tmp_path):
    d = tmp_path / "Bad_Name"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: Bad_Name\ndescription: x\n---\nbody\n")
    with pytest.raises(SkillError):
        parse_skill(d / "SKILL.md")
