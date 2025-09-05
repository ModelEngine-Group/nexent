import asyncio
import logging
from threading import Thread

from smolagents import ToolCollection

from .agent_model import AgentRunInfo, MemoryContext
from .nexent_agent import NexentAgent, ProcessType


logger = logging.getLogger("run_agent")
logger.setLevel(logging.DEBUG)


def agent_run_thread(agent_run_info: AgentRunInfo, memory_context: MemoryContext):
    try:
        mcp_host = agent_run_info.mcp_host
        if mcp_host is None or len(mcp_host)==0:
            nexent = NexentAgent(
                observer=agent_run_info.observer,
                model_config_list=agent_run_info.model_config_list,
                stop_event=agent_run_info.stop_event
            )
            agent = nexent.create_single_agent(agent_run_info.agent_config)
            nexent.set_agent(agent)
            nexent.add_history_to_agent(agent_run_info.history)
            nexent.agent_run_with_observer(query=agent_run_info.query, reset=False)
        else:
            agent_run_info.observer.add_message("", ProcessType.AGENT_NEW_RUN, "<MCP_START>")
            mcp_client_list = [{"url": mcp_url} for mcp_url in mcp_host]

            with ToolCollection.from_mcp(mcp_client_list, trust_remote_code=True) as tool_collection:
                nexent = NexentAgent(
                    observer=agent_run_info.observer,
                    model_config_list=agent_run_info.model_config_list,
                    stop_event=agent_run_info.stop_event,
                    mcp_tool_collection=tool_collection
                )
                agent = nexent.create_single_agent(agent_run_info.agent_config)
                nexent.set_agent(agent)
                nexent.add_history_to_agent(agent_run_info.history)
                nexent.agent_run_with_observer(query=agent_run_info.query, reset=False)

    except Exception as e:
        if "Couldn't connect to the MCP server" in str(e):
            mcp_connect_error_str = "MCP服务器连接超时。" if agent_run_info.observer.lang == "zh" else "Couldn't connect to the MCP server."
            agent_run_info.observer.add_message("", ProcessType.FINAL_ANSWER, mcp_connect_error_str)
        else:
            agent_run_info.observer.add_message("", ProcessType.FINAL_ANSWER, f"Run Agent Error: {e}")
        raise ValueError(f"Error in agent_run_thread: {e}")


async def agent_run(agent_run_info: AgentRunInfo, memory_context: MemoryContext):
    observer = agent_run_info.observer

    thread_agent = Thread(target=agent_run_thread, args=(agent_run_info, memory_context))
    thread_agent.start()

    while thread_agent.is_alive():
        cached_message = observer.get_cached_message()
        for message in cached_message:
            yield message

            # Prevent artificial slowdown of model streaming output
            if len(cached_message) < 8:
                # Ensure streaming output has some time interval
                 await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)

    # Ensure all messages are sent
    cached_message = observer.get_cached_message()
    for message in cached_message:
        yield message
