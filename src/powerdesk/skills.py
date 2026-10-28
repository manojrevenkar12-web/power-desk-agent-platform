"""Agent skills in the open SKILL.md format (agentskills.io), the format Claude Code and Amazon
Bedrock AgentCore managed harnesses load.

Progressive disclosure: only each skill's name and description go into the system prompt; the
body loads when the agent calls `load_skill`. A loaded skill narrows the tools the agent may call
to its `allowed-tools` (plus `load_skill`), and becomes the `agent` in the policy context, which is
what unlocks that skill's agent-scope knowledge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from powerdesk.settings import ROOT

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    allowed_tools: tuple[str, ...]
    metadata: dict
    path: Path


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise SkillError(f"{path}: SKILL.md needs YAML front matter")
    fm = yaml.safe_load(m.group(1)) or {}
    name = str(fm.get("name", ""))
    desc = str(fm.get("description", ""))
    if not NAME.match(name) or len(name) > 64:
        raise SkillError(f"{path}: name must be lowercase letters, digits and single hyphens, at most 64 characters")
    if name != path.parent.name:
        raise SkillError(f"{path}: name {name!r} must match its directory {path.parent.name!r}")
    if not desc or len(desc) > 1024:
        raise SkillError(f"{path}: description must be 1 to 1024 characters")
    unknown = set(fm) - {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    if unknown:
        raise SkillError(f"{path}: unknown front matter keys {sorted(unknown)}")
    tools = tuple(str(fm.get("allowed-tools", "")).split())
    return Skill(name, desc, m.group(2).strip(), tools, dict(fm.get("metadata") or {}), path)


@lru_cache
def load_skills(root: Path | None = None) -> dict[str, Skill]:
    base = root or ROOT / "skills"
    skills = {}
    for p in sorted(base.glob("*/SKILL.md")):
        s = parse_skill(p)
        skills[s.name] = s
    return skills


def catalogue_prompt(skills: dict[str, Skill]) -> str:
    lines = ["Skills you can load with load_skill(name). Load the one that fits before calling other tools:"]
    lines += [f"- {s.name}: {s.description}" for s in skills.values()]
    return "\n".join(lines)


def agentcore_skill_sources(bucket: str, prefix: str = "skills") -> list[dict]:
    """The managed-harness `skills` configuration for these skills, loaded from S3 (works through
    the S3 gateway endpoint, so the VPC needs no NAT gateway, unlike Git sources)."""
    return [{"s3": {"uri": f"s3://{bucket}/{prefix}/{name}/"}} for name in load_skills()]
