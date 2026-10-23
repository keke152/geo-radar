from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills"


def load_active_skills() -> list[dict[str, Any]]:
    active = []
    for path in sorted(SKILL_DIR.glob("*.yaml")):
        try:
            skill = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if skill.get("status") == "pending-human-review":
                continue
            active.append(skill)
        except (OSError, yaml.YAMLError):
            continue
    return active
