import asyncio
from threading import Thread

from smolagents import ToolCollection

from .nexent_agent import NexentAgent
from .agent_model import AgentRunInfo


def agent_run_thread(agent_run_info: AgentRunInfo):
    if not isinstance(agent_run_info, AgentRunInfo):
        raise TypeError("agent_run_info must be a AgentRunInfo object")

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
        raise ValueError(f"Error in agent_run_thread: {e}")


async def agent_run(agent_run_info: AgentRunInfo):
    if not isinstance(agent_run_info, AgentRunInfo):
        raise TypeError("agent_run_info must be a AgentRunInfo object")

    observer = agent_run_info.observer

    thread_agent = Thread(target=agent_run_thread, args=(agent_run_info,))
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