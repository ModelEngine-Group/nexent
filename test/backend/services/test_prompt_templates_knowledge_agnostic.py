from pathlib import Path

import yaml
from jinja2 import Environment


PROMPT_DIR = Path(__file__).parents[3] / "backend" / "prompts" / "utils"
PROMPT_FILES = [
    PROMPT_DIR / "prompt_generate_zh.yaml",
    PROMPT_DIR / "prompt_generate_en.yaml",
    PROMPT_DIR / "prompt_optimize_zh.yaml",
    PROMPT_DIR / "prompt_optimize_en.yaml",
]


def _walk_strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield value


def test_knowledge_prompt_templates_are_valid_yaml_and_jinja():
    environment = Environment()
    for path in PROMPT_FILES:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)
        for value in _walk_strings(parsed):
            if "{{" in value or "{%" in value:
                environment.parse(value)


def test_knowledge_prompt_templates_do_not_embed_resource_ranges():
    for path in PROMPT_FILES:
        source = path.read_text(encoding="utf-8")
        assert "knowledge_base_names" not in source
        assert "aidp_kb_names" not in source
        assert "index_names=" not in source
        assert "kds_list=" not in source
        assert "has_local_knowledge_tool" in source
        assert "has_aidp_knowledge_tool" in source


def test_builtin_prompt_templates_do_not_guide_observation_markers():
    prompt_root = Path(__file__).parents[3] / "backend" / "prompts"
    forbidden_terms = ("Observation", "Observe Results", "观察结果")

    for path in prompt_root.rglob("*.yaml"):
        source = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in source, f"{path} still contains observation guidance: {term}"
