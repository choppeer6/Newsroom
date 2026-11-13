"""YAML + Jinja2 prompt loader."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

_PROMPT_ROOT = Path(__file__).resolve().parent
_AGENTS_DIR = _PROMPT_ROOT / "agents"
_SHARED_DIR = _PROMPT_ROOT / "shared"
_SHARED_NAMES = ("output_rules", "safety_rules", "source_rules")

_ENV = Environment(
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class PromptSpec:
    key: str
    version: str
    name: str
    system: str
    user_template: str
    temperature: float
    max_tokens: int

    def render(self, **context: Any) -> str:
        return _ENV.from_string(self.user_template).render(**context)


@lru_cache
def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Prompt 文件格式错误：{path.name}")
    return data


@lru_cache
def _shared_rules() -> str:
    rules: list[str] = []
    for name in _SHARED_NAMES:
        data = _read_yaml(_SHARED_DIR / f"{name}.yaml")
        text = str(data.get("rules") or "").strip()
        if text:
            rules.append(text)
    return "\n\n".join(rules)


@lru_cache
def load_prompt(agent: str, name: str) -> PromptSpec:
    path = _AGENTS_DIR / f"{agent}.yaml"
    data = _read_yaml(path)
    prompts = data.get("prompts")
    if not isinstance(prompts, dict) or name not in prompts:
        raise ValueError(f"未找到 Prompt：{agent}.{name}")

    entry = prompts[name]
    if not isinstance(entry, dict):
        raise ValueError(f"Prompt 配置格式错误：{agent}.{name}")

    system = str(entry.get("system") or "").strip()
    user_template = str(entry.get("user_template") or "").strip()
    if not system or not user_template:
        raise ValueError(f"Prompt 缺少 system 或 user_template：{agent}.{name}")

    shared = _shared_rules()
    if shared:
        system = f"{system}\n\n{shared}"

    return PromptSpec(
        key=str(data.get("key") or agent),
        version=str(data.get("version") or "v1"),
        name=name,
        system=system,
        user_template=user_template,
        temperature=float(entry.get("temperature", 0.2)),
        max_tokens=int(entry.get("max_tokens", 4000)),
    )
