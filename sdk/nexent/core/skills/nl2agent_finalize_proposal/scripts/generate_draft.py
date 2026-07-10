#!/usr/bin/env python3
"""Validate and normalise a draft agent specification produced by the LLM.

This script is invoked by RunSkillScriptTool. It strips any markdown fences from
the LLM output, parses the JSON, validates and clamps each field to its allowed
range, and writes a normalised JSON blob to stdout. It does NOT call any backend
services.

Args (sys.argv):
    1  draft_agent_id      — integer
    2  llm_output          — raw output string (may contain markdown fences)
    3  tool_configs_json   — JSON object: { tool_id (int-or-str): { param: value } }
    4  skill_configs_json  — JSON object: { skill_id (int-or-str): { config_key: value } }

Exit: prints normalised JSON to stdout; on error prints {"error": "..."}.
"""

import json
import re
import sys
from typing import Any, Dict


def _snake_case(name: str) -> str:
    """Convert a display name to a valid snake_case identifier."""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _clamp(val: Any, lo: int, hi: int) -> Any:
    """Clamp an integer value between lo and hi; return None if not numeric."""
    try:
        v = int(val)
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return None


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: generate_draft.py <draft_agent_id> <llm_output> [...]"}))
        return

    try:
        agent_id = int(sys.argv[1])
    except ValueError:
        print(json.dumps({"error": f"draft_agent_id must be an integer, got: {sys.argv[1]}"}))
        return

    raw = sys.argv[2]

    # Strip markdown fences (e.g. ```nl2agent-finalize\n...\n```)
    raw = re.sub(r"^```nl2agent-finalize\s*\n?", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"\n?```$", "", raw.strip())

    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid JSON: {exc}"}))
        return

    # Always preserve the draft agent ID from context
    result: Dict[str, Any] = {"agent_id": agent_id}

    # ── Identity ──────────────────────────────────────────────────────────────
    display_name = str(draft.get("display_name", "")).strip()
    result["display_name"] = display_name[:50]

    name = draft.get("name", "").strip()
    if not name:
        name = _snake_case(display_name)
    result["name"] = re.sub(r"[^a-zA-Z0-9_]", "_", name)[:50]

    # ── LLM models ───────────────────────────────────────────────────────────
    bl_model = _clamp(draft.get("business_logic_model_id"), 1, None)
    result["business_logic_model_id"] = bl_model or None
    result["business_logic_model_name"] = str(draft.get("business_logic_model_name", ""))

    raw_model_ids = draft.get("model_ids", [])
    model_ids = [int(x) for x in raw_model_ids if str(x).isdigit()][:5]
    result["model_ids"] = model_ids

    # ── Task & template ───────────────────────────────────────────────────────
    result["business_description"] = str(draft.get("business_description", ""))[:2000]
    result["prompt_template_id"] = _clamp(draft.get("prompt_template_id"), 1, None) or 1
    result["prompt_template_name"] = str(draft.get("prompt_template_name", "General"))[:100]

    # ── Prompt sections ───────────────────────────────────────────────────────
    result["duty_prompt"] = str(draft.get("duty_prompt", ""))[:8000]
    result["constraint_prompt"] = str(draft.get("constraint_prompt", ""))[:4000]
    result["few_shots_prompt"] = str(draft.get("few_shots_prompt", ""))[:8000]

    # ── UI greeting & examples ────────────────────────────────────────────────
    result["greeting_message"] = str(draft.get("greeting_message", ""))[:500]
    raw_qs = draft.get("example_questions", [])
    questions = [str(q).strip() for q in raw_qs if str(q).strip()][:6]
    result["example_questions"] = questions

    # ── Runtime behaviour ────────────────────────────────────────────────────
    result["max_steps"] = _clamp(draft.get("max_steps"), 1, 30) or 15
    result["requested_output_tokens"] = _clamp(draft.get("requested_output_tokens"), 1, None) or 2048
    result["provide_run_summary"] = bool(draft.get("provide_run_summary", False))

    vcfg = draft.get("verification_config", {})
    if isinstance(vcfg, dict):
        result["verification_config"] = {
            "enabled": bool(vcfg.get("enabled", False)),
            "mode": str(vcfg.get("mode", "basic")),
        }
    else:
        result["verification_config"] = {"enabled": False, "mode": "basic"}

    result["enable_context_manager"] = bool(draft.get("enable_context_manager", True))

    # ── Resources ────────────────────────────────────────────────────────────
    def _parse_int_array(val: Any) -> list:
        if not val:
            return []
        if isinstance(val, list):
            return [int(x) for x in val if str(x).strip().lstrip("-").isdigit()]
        return []

    result["selected_tools"] = _parse_int_array(draft.get("selected_tools"))
    result["selected_skills"] = _parse_int_array(draft.get("selected_skills"))
    result["sub_agent_ids"] = _parse_int_array(draft.get("sub_agent_ids", []))

    # ── Tool & skill configs ─────────────────────────────────────────────────
    def _parse_config_dict(val: Any) -> Dict[str, Dict[str, Any]]:
        """Normalise a config dict: keys are str(tool_id), values are param dicts."""
        if not val or not isinstance(val, dict):
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in val.items():
            key = str(int(k)) if str(k).lstrip("-").isdigit() else str(k)
            if isinstance(v, dict):
                out[key] = {str(pk): pv for pk, pv in v.items()}
            else:
                out[key] = {}
        return out

    # Priority: sys.argv overrides > draft JSON
    if len(sys.argv) > 3 and sys.argv[3].strip():
        try:
            result["tool_configs"] = _parse_config_dict(json.loads(sys.argv[3]))
        except json.JSONDecodeError:
            result["tool_configs"] = _parse_config_dict(draft.get("tool_configs", {}))
    else:
        result["tool_configs"] = _parse_config_dict(draft.get("tool_configs", {}))

    if len(sys.argv) > 4 and sys.argv[4].strip():
        try:
            result["skill_configs"] = _parse_config_dict(json.loads(sys.argv[4]))
        except json.JSONDecodeError:
            result["skill_configs"] = _parse_config_dict(draft.get("skill_configs", {}))
    else:
        result["skill_configs"] = _parse_config_dict(draft.get("skill_configs", {}))

    # ── Meta ─────────────────────────────────────────────────────────────────
    result["description"] = str(draft.get("description", ""))[:500]
    result["author"] = ""

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
