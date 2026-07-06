"""HistoryProjector: projects conversation history from database into ContextItem instances."""

from typing import Any, Callable, Dict, List, Optional

from .context_item import AuthorityTier, ContextItem, ContextItemType, RepresentationTier
from .item_handler_registry import ItemHandlerRegistry
from nexent.monitor import get_monitoring_manager, OPENINFERENCE_SPAN_KIND_CHAIN, OPENINFERENCE_SPAN_KIND_RETRIEVER


class HistoryProjector:
    """Projects conversation history from database into ContextItem instances.

    Uses dependency injection for database queries to maintain SDK/backend separation.
    Produces HISTORY_TURN, TOOL_CALL_RESULT, and WORKING_MEMORY ContextItems.
    """

    def __init__(self, query_units_fn: Callable[[int, Optional[int]], List[Dict[str, Any]]]):
        """Initialize with a database query function.

        Args:
            query_units_fn: Function that takes (conversation_id, run_id) and returns
                           a list of unit dictionaries ordered by run_id, step_id, unit_index.
                           This is typically get_message_units_by_run from conversation_db.
        """
        self.query_units_fn = query_units_fn

    def project(
        self,
        conversation_id: int,
        run_id: Optional[int] = None,
        purpose: str = "model_context",
    ) -> List[ContextItem]:
        """Project conversation history into ContextItem instances.

        Args:
            conversation_id: The conversation to project.
            run_id: Optional specific run to project (None = all runs).
            purpose: Projection purpose - "model_context", "resume", or "chat".

        Returns:
            List of ContextItem instances.

        Raises:
            ValueError: If purpose is not recognized.
        """
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_operation(
            "context.history_project",
            OPENINFERENCE_SPAN_KIND_CHAIN,
            **{
                "context.conversation_id": conversation_id,
                "context.run_id": run_id,
                "context.purpose": purpose,
            },
        ):
            with monitoring_manager.trace_operation(
                "context.history_query",
                OPENINFERENCE_SPAN_KIND_RETRIEVER,
                **{
                    "context.conversation_id": conversation_id,
                    "context.run_id": run_id,
                },
            ):
                units = self.query_units_fn(conversation_id, run_id)
            
            if monitoring_manager.is_enabled:
                monitoring_manager.add_span_event(
                    "context.history_query.completed",
                    {"context.unit_count": len(units)},
                )

            if purpose == "model_context":
                items = self._project_model_context(units)
            elif purpose == "resume":
                items = self._project_resume_context(units)
            elif purpose == "chat":
                items = self._project_chat_context(units)
            else:
                raise ValueError(f"Unknown purpose: {purpose}")
            
            if monitoring_manager.is_enabled:
                monitoring_manager.add_span_event(
                    "context.history_project.completed",
                    {"context.item_count": len(items)},
                )
            
            return items

    def _project_model_context(self, units: List[Dict[str, Any]]) -> List[ContextItem]:
        """Project units into HISTORY_TURN and TOOL_CALL_RESULT items for model context.

        Groups units by run_id and step_id, then:
        - Pairs user messages with assistant final_answer -> HISTORY_TURN
        - Pairs tool calls with execution_logs via tool_call_id -> TOOL_CALL_RESULT
        - Excludes model_output_thinking and model_output_deep_thinking
        """
        items: List[ContextItem] = []

        runs = self._group_by_run(units)

        for run_id, steps in runs.items():
            for step_id, step_units in steps.items():
                history_turn = self._extract_history_turn(step_units, run_id, step_id)
                if history_turn:
                    items.append(history_turn)

                tool_results = self._extract_tool_call_results(step_units, run_id, step_id)
                items.extend(tool_results)

        for item in items:
            ItemHandlerRegistry.get(item.item_type)

        return items

    def _project_resume_context(self, units: List[Dict[str, Any]]) -> List[ContextItem]:
        """Project units into WORKING_MEMORY items for resume context.

        Extracts:
        - Active goals from the last user query
        - Incomplete tool calls (tool without execution_logs)
        """
        items: List[ContextItem] = []

        if not units:
            return items

        runs = self._group_by_run(units)
        if not runs:
            return items

        last_run_id = max(runs.keys())
        last_run_steps = runs[last_run_id]

        last_step_id = max(last_run_steps.keys())
        last_step_units = last_run_steps[last_step_id]

        user_units = [u for u in last_step_units if u.get("unit_type") == "user_input"]
        if user_units:
            goal_content = user_units[-1].get("unit_content", "")
            items.append(
                ContextItem(
                    item_id=f"working_memory:goal:{last_run_id}:{last_step_id}",
                    item_type=ContextItemType.WORKING_MEMORY,
                    source_refs=[f"unit:{user_units[-1]['unit_id']}"],
                    authority_tier=AuthorityTier.USER,
                    minimum_fidelity=RepresentationTier.STRUCTURED,
                    current_representation=RepresentationTier.FULL,
                    content={"type": "active_goal", "text": goal_content},
                    token_estimate=len(goal_content) // 4,
                    metadata={"run_id": last_run_id, "step_id": last_step_id},
                )
            )

        all_units = [u for step_units in last_run_steps.values() for u in step_units]
        incomplete_tools = self._find_incomplete_tool_calls(all_units)
        for tool_unit in incomplete_tools:
            items.append(
                ContextItem(
                    item_id=f"working_memory:pending_tool:{tool_unit['unit_id']}",
                    item_type=ContextItemType.WORKING_MEMORY,
                    source_refs=[f"unit:{tool_unit['unit_id']}"],
                    authority_tier=AuthorityTier.TOOL_RESULT,
                    minimum_fidelity=RepresentationTier.STRUCTURED,
                    current_representation=RepresentationTier.FULL,
                    content={
                        "type": "pending_tool_call",
                        "tool_call_id": tool_unit.get("tool_call_id"),
                        "tool_content": tool_unit.get("unit_content", ""),
                    },
                    token_estimate=len(tool_unit.get("unit_content", "")) // 4,
                    metadata={"tool_call_id": tool_unit.get("tool_call_id")},
                )
            )

        return items

    def _project_chat_context(self, units: List[Dict[str, Any]]) -> List[ContextItem]:
        """Project units into HISTORY_TURN items for chat display.

        Similar to model_context but includes thinking units for full transparency.
        """
        items: List[ContextItem] = []

        runs = self._group_by_run(units)

        for run_id, steps in runs.items():
            for step_id, step_units in steps.items():
                chat_turn = self._extract_chat_turn(step_units, run_id, step_id)
                if chat_turn:
                    items.append(chat_turn)

        return items

    def _group_by_run(
        self, units: List[Dict[str, Any]]
    ) -> Dict[int, Dict[int, List[Dict[str, Any]]]]:
        """Group units by run_id and step_id.

        Returns:
            Dict[run_id, Dict[step_id, List[unit]]]
        """
        runs: Dict[int, Dict[int, List[Dict[str, Any]]]] = {}
        for unit in units:
            run_id = unit.get("run_id") or 0
            step_id = unit.get("step_id") or 0

            if run_id not in runs:
                runs[run_id] = {}
            if step_id not in runs[run_id]:
                runs[run_id][step_id] = []

            runs[run_id][step_id].append(unit)

        return runs

    def _extract_history_turn(
        self,
        units: List[Dict[str, Any]],
        run_id: int,
        step_id: int,
    ) -> Optional[ContextItem]:
        """Extract a HISTORY_TURN item from user input and final_answer units.

        Returns None if no user input or final_answer found.
        """
        user_units = [u for u in units if u.get("unit_type") == "user_input"]
        answer_units = [u for u in units if u.get("unit_type") == "final_answer"]

        if not user_units or not answer_units:
            return None

        user_content = user_units[0].get("unit_content", "")
        answer_content = answer_units[0].get("unit_content", "")

        content = {
            "user_query": user_content,
            "assistant_response": answer_content,
        }

        source_refs = [
            f"unit:{user_units[0]['unit_id']}",
            f"unit:{answer_units[0]['unit_id']}",
        ]

        return ContextItem(
            item_id=f"history_turn:{run_id}:{step_id}",
            item_type=ContextItemType.HISTORY_TURN,
            source_refs=source_refs,
            authority_tier=AuthorityTier.AGENT_INFERENCE,
            minimum_fidelity=RepresentationTier.STRUCTURED,
            current_representation=RepresentationTier.FULL,
            content=content,
            token_estimate=(len(user_content) + len(answer_content)) // 4,
            metadata={"run_id": run_id, "step_id": step_id},
        )

    def _extract_tool_call_results(
        self,
        units: List[Dict[str, Any]],
        run_id: int,
        step_id: int,
    ) -> List[ContextItem]:
        """Extract TOOL_CALL_RESULT items by pairing tool and execution_logs via tool_call_id."""
        items: List[ContextItem] = []

        tool_calls: Dict[str, Dict[str, Optional[Dict[str, Any]]]] = {}
        for unit in units:
            tool_call_id = unit.get("tool_call_id")
            if not tool_call_id:
                continue

            if tool_call_id not in tool_calls:
                tool_calls[tool_call_id] = {"tool": None, "logs": None}

            if unit.get("unit_type") == "tool":
                tool_calls[tool_call_id]["tool"] = unit
            elif unit.get("unit_type") == "execution_logs":
                tool_calls[tool_call_id]["logs"] = unit

        for tool_call_id, pair in tool_calls.items():
            if pair["tool"] and pair["logs"]:
                tool_content = pair["tool"].get("unit_content", "")
                logs_content = pair["logs"].get("unit_content", "")

                content = {
                    "tool_call": tool_content,
                    "execution_result": logs_content,
                }

                source_refs = [
                    f"unit:{pair['tool']['unit_id']}",
                    f"unit:{pair['logs']['unit_id']}",
                ]

                items.append(
                    ContextItem(
                        item_id=f"tool_call_result:{tool_call_id}",
                        item_type=ContextItemType.TOOL_CALL_RESULT,
                        source_refs=source_refs,
                        authority_tier=AuthorityTier.TOOL_RESULT,
                        minimum_fidelity=RepresentationTier.STRUCTURED,
                        current_representation=RepresentationTier.FULL,
                        content=content,
                        token_estimate=(len(tool_content) + len(logs_content)) // 4,
                        metadata={
                            "tool_call_id": tool_call_id,
                            "run_id": run_id,
                            "step_id": step_id,
                        },
                    )
                )

        return items

    def _find_incomplete_tool_calls(self, units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find tool units without matching execution_logs (incomplete tool calls)."""
        tool_units = [
            u for u in units if u.get("unit_type") == "tool" and u.get("tool_call_id")
        ]
        logs_units = [
            u for u in units if u.get("unit_type") == "execution_logs" and u.get("tool_call_id")
        ]

        logs_tool_call_ids = {u["tool_call_id"] for u in logs_units}

        return [u for u in tool_units if u["tool_call_id"] not in logs_tool_call_ids]

    def _extract_chat_turn(
        self,
        units: List[Dict[str, Any]],
        run_id: int,
        step_id: int,
    ) -> Optional[ContextItem]:
        """Extract a chat turn including thinking for display purposes."""
        relevant_types = {
            "user_input",
            "model_output_thinking",
            "model_output_code",
            "final_answer",
        }
        relevant_units = [u for u in units if u.get("unit_type") in relevant_types]

        if not relevant_units:
            return None

        content = {
            "units": [
                {
                    "type": u.get("unit_type"),
                    "content": u.get("unit_content", ""),
                }
                for u in relevant_units
            ]
        }

        source_refs = [f"unit:{u['unit_id']}" for u in relevant_units]

        return ContextItem(
            item_id=f"chat_turn:{run_id}:{step_id}",
            item_type=ContextItemType.HISTORY_TURN,
            source_refs=source_refs,
            authority_tier=AuthorityTier.AGENT_INFERENCE,
            minimum_fidelity=RepresentationTier.FULL,
            current_representation=RepresentationTier.FULL,
            content=content,
            token_estimate=sum(len(u.get("unit_content", "")) for u in relevant_units) // 4,
            metadata={"run_id": run_id, "step_id": step_id, "includes_thinking": True},
        )
