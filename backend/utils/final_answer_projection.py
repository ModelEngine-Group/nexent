"""Project accepted answer roles into the existing buffered message units."""

from typing import Any


def resolve_answer_completion(units: list[dict[str, Any]], event: dict[str, Any]) -> bool:
    """Remove explicitly reclassified bodies; return whether completion has a body."""
    invocation = event.get("invocation_id")
    if event.get("answer_phase") == "delta" and event.get("step_id"):
        units[:] = [unit for unit in units if not (
            unit.get("invocation_id") == invocation and unit["type"] == "final_answer"
            and unit.get("_step_id") != event["step_id"]
        )]
    if event.get("reclassify_step") and event.get("step_id"):
        original = [unit for unit in units if (
            unit.get("invocation_id") == invocation
            and unit.get("_step_id") == event["step_id"]
            and unit["type"] in {"model_output_thinking", "model_output_code"}
        )]
        if original and not event.get("content"):
            first = original[0]
            fragments = [fragment for unit in original for fragment in
                         unit.get("_content_fragments", [unit.get("content", "")])]
            first.update(type="final_answer", unit_type="final_answer", _content_fragments=fragments,
                         content="", unit_content="")
            units[:] = [unit for unit in units if unit is first or not any(unit is item for item in original)]
            return False
        units[:] = [unit for unit in units if not (
            unit.get("invocation_id") == invocation
            and unit.get("_step_id") == event["step_id"]
            and unit["type"] in {"model_output_thinking", "model_output_code"}
        )]
    if event.get("answer_phase") == "complete" and event.get("content"):
        units[:] = [unit for unit in units if not (
            unit.get("invocation_id") == invocation and unit["type"] == "final_answer"
        )]
    return bool(event.get("content"))


def remove_answer_only_steps(units: list[dict[str, Any]]) -> None:
    """Keep markers only for steps with meaningful reasoning or actions."""
    answers = {(unit.get("invocation_id"), unit.get("_step_id"))
               for unit in units if unit["type"] == "final_answer"}
    actual = set()
    for unit in units:
        content = "".join(unit.get("_content_fragments", [])) or unit.get("content", "")
        if unit["type"] in {"model_output_thinking", "model_output_deep_thinking", "model_output_code"}:
            meaningful = bool(str(content).strip())
        else:
            meaningful = unit["type"] in {"tool", "tool-call", "parse"}
        if meaningful:
            actual.add((unit.get("invocation_id"), unit.get("_step_id")))
    units[:] = [unit for unit in units if not (
        unit["type"] == "step_count"
        and (unit.get("invocation_id"), unit.get("_step_id")) in answers - actual
    )]
    for unit in units:
        unit.pop("_step_id", None)
