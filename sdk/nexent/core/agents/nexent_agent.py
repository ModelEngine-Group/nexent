import re
import time
from threading import Event
from typing import List

from smolagents import ActionStep, AgentText, TaskStep, Timing
from smolagents.tools import Tool

from ..models.openai_llm import OpenAIModel
from ..tools import *  # Used for tool creation, do not delete!!!
from ..utils.constants import THINK_TAG_PATTERN
from ..utils.observer import MessageObserver, ProcessType
from .agent_model import AgentConfig, AgentHistory, ModelConfig, ToolConfig
from .core_agent import CoreAgent, convert_code_format


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
            model_factory=model_config.model_factory
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
                                   if k not in ["index_names", "vdb_core", "embedding_model", "observer"]}
                # Create instance with only non-excluded parameters
                tools_obj = tool_class(**filtered_params)
                # Set excluded parameters directly as attributes after instantiation
                # This bypasses smolagents wrapper restrictions
                tools_obj.observer = self.observer
                index_names = tool_config.metadata.get(
                    "index_names", None) if tool_config.metadata else None
                tools_obj.index_names = [] if index_names is None else index_names
                tools_obj.vdb_core = tool_config.metadata.get(
                    "vdb_core", None) if tool_config.metadata else None
                tools_obj.embedding_model = tool_config.metadata.get(
                    "embedding_model", None) if tool_config.metadata else None
                name_resolver = tool_config.metadata.get(
                    "name_resolver", None) if tool_config.metadata else None
                tools_obj.name_resolver = {} if name_resolver is None else name_resolver
            elif class_name == "DataMateSearchTool":
                tools_obj = tool_class(**params)
                tools_obj.observer = self.observer
                index_names = tool_config.metadata.get(
                    "index_names", None) if tool_config.metadata else None
                tools_obj.index_names = [] if index_names is None else index_names
            elif class_name == "AnalyzeTextFileTool":
                tools_obj = tool_class(observer=self.observer,
                                       llm_model=tool_config.metadata.get("llm_model", []),
                                       storage_client=tool_config.metadata.get("storage_client", []),
                                       data_process_service_url=tool_config.metadata.get("data_process_service_url", []),
                                       **params)
            elif class_name == "AnalyzeImageTool":
                tools_obj = tool_class(observer=self.observer,
                                       vlm_model=tool_config.metadata.get("vlm_model", []),
                                       storage_client=tool_config.metadata.get("storage_client", []),
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
                managed_agents_list = [self.create_single_agent(sub_agent_config) for sub_agent_config in agent_config.managed_agents]
            except Exception as e:
                raise ValueError(f"Error in creating managed agent: {e}")

            # create the agent
            agent = CoreAgent(
                observer=self.observer,
                tools=tool_list,
                model=model,
                name=agent_config.name,
                description=agent_config.description,
                max_steps=agent_config.max_steps,
                prompt_templates=prompt_templates,
                provide_run_summary=agent_config.provide_run_summary,
                managed_agents=managed_agents_list
            )
            agent.stop_event = self.stop_event

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

    def agent_run_with_observer(self, query: str, reset=True):
        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        observer = self.agent.observer
        try:
            for step_log in self.agent.run(query, stream=True, reset=reset):
                # Add content to observer
                if not isinstance(step_log, ActionStep):
                    continue
                # Keep duration
                if hasattr(step_log, "duration"):
                    observer.add_message("", ProcessType.TOKEN_COUNT, str(round(float(step_log.duration), 2)))

                if hasattr(step_log, "error") and step_log.error is not None:
                    observer.add_message("", ProcessType.ERROR, str(step_log.error))

            final_answer = step_log.output  # Last log is the run's final_answer

            if isinstance(final_answer, AgentText):
                final_answer_str = convert_code_format(final_answer.to_string())
            else:
                # prepare for multi-modal final_answer
                final_answer_str = convert_code_format(str(final_answer))
            final_answer_str = re.sub(THINK_TAG_PATTERN, "", final_answer_str, flags=re.DOTALL | re.IGNORECASE)
            observer.add_message(self.agent.agent_name, ProcessType.FINAL_ANSWER, final_answer_str)

            # Check if we need to stop from external stop_event
            if self.agent.stop_event.is_set():
                observer.add_message(self.agent.agent_name, ProcessType.ERROR,
                                     "Agent execution interrupted by external stop signal")
        except Exception as e:
            observer.add_message(agent_name=self.agent.agent_name, process_type=ProcessType.ERROR,
                                 content=f"Error in interaction: {str(e)}")
            raise ValueError(f"Error in interaction: {str(e)}")

    def set_agent(self, agent: CoreAgent):
        if not isinstance(agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(agent)}")
        self.agent = agent
