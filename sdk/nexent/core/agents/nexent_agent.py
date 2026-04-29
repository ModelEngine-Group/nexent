import json
import re
import time
from threading import Event
from typing import List

from smolagents import ActionStep, AgentText, TaskStep, Timing
from smolagents.tools import Tool

from ..models.openai_llm import OpenAIModel
from ..tools import *  # Used for tool creation, do not delete!!!
from ..utils.constants import THINK_TAG_PATTERN, THINK_PREFIX_PATTERN
from ..utils.observer import MessageObserver, ProcessType
from .agent_model import AgentConfig, AgentHistory, ModelConfig, ToolConfig
from .core_agent import CoreAgent, convert_code_format
from .agent_context import ContextManager


class NexentAgent:
    def __init__(self, observer: MessageObserver,
                 model_config_list: List[ModelConfig],
                 stop_event: Event,
                 mcp_tool_collection=None):
        """
        init the agent create factory

        Args:
            mcp_tool_collection:
            observer:
            model_config_list:
        """
        if not isinstance(observer, MessageObserver):
            raise TypeError("Create Observer Object with MessageObserver")

        self.observer = observer
        self.model_config_list = model_config_list
        self.stop_event = stop_event
        self.mcp_tool_collection = mcp_tool_collection

        self.agent = None

    def create_model(self, model_cite_name: str):
        """create a model instance"""
        # Filter out None values and find matching model config
        model_config = next(
            (model_config for model_config in self.model_config_list
             if model_config is not None and model_config.cite_name == model_cite_name),
            None
        )
        if model_config is None:
            raise ValueError(f"Model {model_cite_name} not found")
        model = OpenAIModel(
            observer=self.observer,
            model_id=model_config.model_name,
            api_key=model_config.api_key,
            api_base=model_config.url,
            temperature=model_config.temperature,
            top_p=model_config.top_p,
            ssl_verify=model_config.ssl_verify if model_config.ssl_verify is not None else True,
            model_factory=model_config.model_factory,
            display_name=model_config.cite_name,
        )
        model.stop_event = self.stop_event
        return model


    def create_local_tool(self, tool_config: ToolConfig):
        class_name = tool_config.class_name
        params = tool_config.params
        tool_class = globals().get(class_name)
        if tool_class is None:
            raise ValueError(f"{class_name} not found in local")
        else:
            if class_name == "KnowledgeBaseSearchTool":
                # Filter out conflicting parameters from params to avoid conflicts
                # These parameters have exclude=True and cannot be passed to __init__
                # due to smolagents.tools.Tool wrapper restrictions
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["vdb_core", "embedding_model", "observer", "rerank_model", "display_name_to_index_map"]}
                # Create instance with only non-excluded parameters
                tools_obj = tool_class(**filtered_params)
                # Set excluded parameters directly as attributes after instantiation
                # This bypasses smolagents wrapper restrictions
                tools_obj.observer = self.observer
                tools_obj.vdb_core = tool_config.metadata.get(
                    "vdb_core", None) if tool_config.metadata else None
                tools_obj.embedding_model = tool_config.metadata.get(
                    "embedding_model", None) if tool_config.metadata else None
                tools_obj.rerank_model = tool_config.metadata.get(
                    "rerank_model", None) if tool_config.metadata else None
                tools_obj.display_name_to_index_map = tool_config.metadata.get(
                    "display_name_to_index_map", {}) if tool_config.metadata else {}
            elif class_name in ["DifySearchTool", "DataMateSearchTool"]:
                # These parameters have exclude=True and cannot be passed to __init__
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["observer", "rerank_model"]}
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
                tools_obj.rerank_model = tool_config.metadata.get(
                    "rerank_model", None) if tool_config.metadata else None
            elif class_name == "HaotianSearchTool":
                # Haotian uses reranking_enable/reranking_model_name (not rerank/rerank_model_name)
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["observer", "rerank_model", "rerank"]}
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
            elif class_name == "AnalyzeTextFileTool":
                # Extract validate_url_access from metadata if it's callable
                validate_url_access = tool_config.metadata.get("validate_url_access") if tool_config.metadata else None
                if validate_url_access is not None and not callable(validate_url_access):
                    validate_url_access = None
                tools_obj = tool_class(observer=self.observer,
                                       llm_model=tool_config.metadata.get("llm_model", []),
                                       storage_client=tool_config.metadata.get("storage_client", []),
                                       data_process_service_url=tool_config.metadata.get("data_process_service_url", []),
                                       validate_url_access=validate_url_access,
                                       **params)
            elif class_name == "AnalyzeImageTool":
                # Extract validate_url_access from metadata if it's callable
                validate_url_access = tool_config.metadata.get("validate_url_access") if tool_config.metadata else None
                if validate_url_access is not None and not callable(validate_url_access):
                    validate_url_access = None
                tools_obj = tool_class(observer=self.observer,
                                       vlm_model=tool_config.metadata.get("vlm_model", []),
                                       storage_client=tool_config.metadata.get("storage_client", []),
                                       validate_url_access=validate_url_access,
                                       **params)
            else:
                tools_obj = tool_class(**params)
                if hasattr(tools_obj, 'observer'):
                    tools_obj.observer = self.observer
            return tools_obj

    def create_langchain_tool(self, tool_config: ToolConfig):
        tool_obj = tool_config.metadata
        return Tool.from_langchain(tool_obj)

    def create_mcp_tool(self, class_name):
        if self.mcp_tool_collection is None:
            raise ValueError("MCP tool collection is not initialized")
        tool_obj = next(
            (tool for tool in self.mcp_tool_collection.tools if tool.name == class_name),
            None
        )
        if tool_obj is None:
            raise ValueError(f"{class_name} not found in MCP server")
        return tool_obj

    def create_builtin_tool(self, tool_config: ToolConfig):
        """Create a builtin tool instance.

        Args:
            tool_config: Tool configuration with class_name, params, and optional metadata.

        Returns:
            Tool instance

        Raises:
            ValueError: If builtin tool is not found
        """
        class_name = tool_config.class_name
        params = tool_config.params or {}

        if class_name == "RunSkillScriptTool":
            from nexent.core.tools.run_skill_script_tool import get_run_skill_script_tool
            metadata = tool_config.metadata or {}
            get_run_skill_script_tool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
            from nexent.core.tools.run_skill_script_tool import run_skill_script
            return run_skill_script
        elif class_name == "ReadSkillMdTool":
            from nexent.core.tools.read_skill_md_tool import get_read_skill_md_tool
            metadata = tool_config.metadata or {}
            get_read_skill_md_tool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
            from nexent.core.tools.read_skill_md_tool import read_skill_md
            return read_skill_md
        elif class_name == "WriteSkillFileTool":
            from nexent.core.tools.write_skill_file_tool import get_write_skill_file_tool
            metadata = tool_config.metadata or {}
            get_write_skill_file_tool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
            from nexent.core.tools.write_skill_file_tool import write_skill_file
            return write_skill_file
        elif class_name == "ReadSkillConfigTool":
            from nexent.core.tools.read_skill_config_tool import get_read_skill_config_tool
            metadata = tool_config.metadata or {}
            get_read_skill_config_tool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
            from nexent.core.tools.read_skill_config_tool import read_skill_config
            return read_skill_config
        else:
            raise ValueError(f"Unknown builtin tool: {class_name}")

    def create_tool(self, tool_config: ToolConfig):
        """create a tool instance according to the tool config"""
        if not isinstance(tool_config, ToolConfig):
            raise TypeError("tool_config must be a ToolConfig object")
        try:
            class_name = tool_config.class_name
            source = tool_config.source

            if source == "local":
                tool_obj = self.create_local_tool(tool_config)
            elif source == "mcp":
                tool_obj = self.create_mcp_tool(class_name)
            elif source == "langchain":
                tool_obj = self.create_langchain_tool(tool_config)
            elif source == "builtin":
                tool_obj = self.create_builtin_tool(tool_config)
            else:
                raise ValueError(f"unsupported tool source: {source}")
            return tool_obj
        except Exception as e:
            raise ValueError(f"Error in creating tool: {e}")

    def create_single_agent(self, agent_config: AgentConfig):
        if not isinstance(agent_config, AgentConfig):
            raise TypeError("agent_config must be a AgentConfig object")

        try:
            model = self.create_model(agent_config.model_name)
            prompt_templates = agent_config.prompt_templates

            try:
                tool_list = [self.create_tool(tool_config) for tool_config in agent_config.tools]
            except Exception as e:
                raise ValueError(f"Error in creating tool: {e}")

            try:
                # Create internal managed agents recursively
                managed_agents_list = [
                    self.create_single_agent(sub_agent_config)
                    for sub_agent_config in agent_config.managed_agents
                ]
            except Exception as e:
                raise ValueError(f"Error in creating managed agent: {e}")

            # Create wrapper agents for external A2A agents - add them to managed_agents
            # so model can call them like: external_agent_name(task="...")
            if agent_config.external_a2a_agents:
                try:
                    from .a2a_agent_proxy import ExternalA2AAgentWrapper
                    for ext_agent_config in agent_config.external_a2a_agents:
                        a2a_agent_info = ext_agent_config.to_a2a_agent_info()
                        wrapper = ExternalA2AAgentWrapper(
                            agent_info=a2a_agent_info,
                            stop_event=self.stop_event,
                            observer=self.observer
                        )
                        managed_agents_list.append(wrapper)
                except Exception as e:
                    raise ValueError(f"Error in creating external A2A agent wrapper: {e}")

            # Create the agent
            agent = CoreAgent(
                observer=self.observer,
                tools=tool_list,
                model=model,
                name=agent_config.name,
                description=agent_config.description,
                max_steps=agent_config.max_steps,
                prompt_templates=prompt_templates,
                provide_run_summary=agent_config.provide_run_summary,
                managed_agents=managed_agents_list,
                additional_authorized_imports=["*"],
                instructions=agent_config.instructions,
            )
            agent.stop_event = self.stop_event

            # Mount context manager if config provided
            ctx_config = getattr(agent_config, 'context_manager_config', None)
            if ctx_config:
                agent.context_manager = ContextManager(
                    config=ctx_config,
                    max_steps=agent_config.max_steps
                )

            return agent
        except Exception as e:
            raise ValueError(f"Error in creating agent, agent name: {agent_config.name}, Error: {e}")

    def add_history_to_agent(self, history: List[AgentHistory]):
        """
        Add conversation history to agent's memory

        Args:
            history: List of conversation messages with role and content
        """
        if history is None:
            return

        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        if not all(isinstance(msg, AgentHistory) for msg in history):
            raise TypeError("history must be a list of AgentHistory objects")

        self.agent.memory.reset()
        # Add conversation history to memory sequentially
        for msg in history:
            if msg.role == 'user':
                # Create task step for user message
                self.agent.memory.steps.append(TaskStep(task=msg.content))
            elif msg.role == 'assistant':
                self.agent.memory.steps.append(ActionStep(step_number=len(self.agent.memory.steps) + 1,
                                                          timing=Timing(start_time=time.time()),
                                                          action_output=msg.content, model_output=msg.content))

        self.agent._history_step_count = len(self.agent.memory.steps)
    def agent_run_with_observer(self, query: str, reset=True):
        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        observer = self.agent.observer
        total_output_tokens = 0
        try:
            for step_log in self.agent.run(query, stream=True, reset=reset):
                # Add content to observer
                print(f"DEBUG step_log type: {type(step_log)}")
                if not isinstance(step_log, ActionStep):
                    continue
                # Emit token stats after each action step
                step_duration = getattr(step_log.timing, "duration", None)
                step_input = None
                step_output = None
                if hasattr(step_log, "token_usage") and step_log.token_usage is not None:
                    step_input = getattr(step_log.token_usage, "input_tokens", None)
                    step_output = getattr(step_log.token_usage, "output_tokens", None)
                if step_output:
                    total_output_tokens += step_output

                estimated_context = None
                if hasattr(self.agent, "step_metrics") and self.agent.step_metrics:
                    estimated_context = self.agent.step_metrics[-1].get(
                        "memory_state", {}
                    ).get("estimated_input_tokens")

                token_threshold = None
                if (
                    hasattr(self.agent, "context_manager")
                    and self.agent.context_manager is not None
                ):
                    token_threshold = self.agent.context_manager.config.token_threshold

                token_data = {
                    "step_number": step_log.step_number,
                    "duration": round(float(step_duration), 2) if step_duration is not None else 0.0,
                    "step_input_tokens": step_input,
                    "step_output_tokens": step_output,
                    "total_output_tokens": total_output_tokens,
                    "estimated_context_tokens": estimated_context,
                    "token_threshold": token_threshold,
                }
                print(f"Step {step_log.step_number} token data: {token_data}")
                observer.add_message("", ProcessType.TOKEN_COUNT, json.dumps(token_data))

                if hasattr(step_log, "error") and step_log.error is not None:
                    observer.add_message("", ProcessType.ERROR, str(step_log.error))

            final_answer = step_log.output  # Last log is the run's final_answer

            if isinstance(final_answer, AgentText):
                final_answer_str = convert_code_format(final_answer.to_string())
            else:
                # prepare for multi-modal final_answer
                final_answer_str = convert_code_format(str(final_answer))
            final_answer_str = re.sub(
                THINK_TAG_PATTERN, "", final_answer_str, flags=re.DOTALL | re.IGNORECASE)
            # Remove thinking prefix content (until two newlines)
            final_answer_str = re.sub(
                THINK_PREFIX_PATTERN, "", final_answer_str, flags=re.DOTALL)
            observer.add_message(self.agent.agent_name,
                                 ProcessType.FINAL_ANSWER, final_answer_str)

            # Check if we need to stop from external stop_event
            if self.agent.stop_event.is_set():
                observer.add_message(self.agent.agent_name, ProcessType.ERROR,
                                     "Agent execution interrupted by external stop signal")
        except Exception as e:
            observer.add_message(agent_name=self.agent.agent_name, process_type=ProcessType.ERROR,
                                 content=f"Error in interaction: {str(e)}")
            raise ValueError(f"Error in interaction: {str(e)}")

        finally:
            self._log_step_metrics()

    def set_agent(self, agent: CoreAgent):
        if not isinstance(agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(agent)}")
        self.agent = agent

    def _log_step_metrics(self):
        """Output step_metrics to log or local file for quantitative analysis of context management."""
        if not hasattr(self.agent, "step_metrics") or not self.agent.step_metrics:
            return

        metrics = self.agent.step_metrics

        # Pre-collect all values
        real_i_vals = [m['main_llm']['input_tokens'] for m in metrics]
        real_o_vals = [m['main_llm']['output_tokens'] for m in metrics]
        comp_i_vals = [m['compression']['input_tokens'] for m in metrics]
        comp_o_vals = [m['compression']['output_tokens'] for m in metrics]
        est_i_vals  = [m['memory_state']['estimated_input_tokens'] for m in metrics]
        est_o_vals  = [m['memory_state']['estimated_output_tokens'] for m in metrics]
        raw_i_vals  = [m['uncompressed_mem_est_input'] for m in metrics]
        save_vals   = [f"{m['compression_ratio']}%" for m in metrics]
        hit_vals    = [str(m['cache_hit']) for m in metrics]

        # Total summary
        total_ri   = sum(real_i_vals)
        total_ro   = sum(real_o_vals)
        total_ci   = sum(comp_i_vals)
        total_co   = sum(comp_o_vals)
        total_ei   = sum(est_i_vals)
        total_eo   = sum(est_o_vals)
        total_raw  = sum(raw_i_vals)
        hit_count  = sum(1 for m in metrics if m['cache_hit'])

        if total_raw > 0:
            total_save_str = f"{round((1 - total_ei / total_raw) * 100, 1)}%"
        else:
            total_save_str = "N/A"
        hit_total_str = f"{hit_count}/{len(metrics)}"

        # Column widths based on max value width
        def _val_width(vals, extra_val=None):
            w = 0
            for v in vals:
                w = max(w, len(str(v)))
            if extra_val is not None:
                w = max(w, len(str(extra_val)))
            return w

        w_ri   = _val_width(real_i_vals, total_ri)
        w_ro   = _val_width(real_o_vals, total_ro)
        w_ci   = _val_width(comp_i_vals, total_ci)
        w_co   = _val_width(comp_o_vals, total_co)
        w_ei   = _val_width(est_i_vals, total_ei)
        w_eo   = _val_width(est_o_vals, total_eo)
        w_raw  = _val_width(raw_i_vals, total_raw)
        w_save = _val_width(save_vals, total_save_str)
        w_hit  = _val_width(hit_vals, hit_total_str)

        # Prefix formatting
        max_step_digits = max(len(str(m['step_number'])) for m in metrics)
        step_prefix_fmt = f"Step {{:>{max_step_digits}}}:  "
        total_prefix = "Total:  " + " " * max_step_digits

        lines = []
        for i, m in enumerate(metrics):
            lines.append(
                step_prefix_fmt.format(m['step_number']) +
                f"real_i={real_i_vals[i]:>{w_ri}}  real_o={real_o_vals[i]:>{w_ro}} | "
                f"comp_i={comp_i_vals[i]:>{w_ci}}  comp_o={comp_o_vals[i]:>{w_co}} | "
                f"est_i={est_i_vals[i]:>{w_ei}}  est_o={est_o_vals[i]:>{w_eo}} | "
                f"est_raw_i={raw_i_vals[i]:>{w_raw}}  save={save_vals[i]:>{w_save}} | "
                f"hit={hit_vals[i]:>{w_hit}}"
            )

        lines.append(
            total_prefix +
            f"real_i={total_ri:>{w_ri}}  real_o={total_ro:>{w_ro}} | "
            f"comp_i={total_ci:>{w_ci}}  comp_o={total_co:>{w_co}} | "
            f"est_i={total_ei:>{w_ei}}  est_o={total_eo:>{w_eo}} | "
            f"est_raw_i={total_raw:>{w_raw}}  save={total_save_str:>{w_save}} | "
            f"hit={hit_total_str:>{w_hit}}"
        )
        if self.agent.context_manager:
            lines.append(f"Context Manager Global: {self.agent.context_manager.get_all_compression_stats()}")

        lines.append(
            "-----"
        )
        print("\n".join(lines))

        # Optional: write to local file
        with open("nexent_context_metrics.log", "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")