import asyncio
import logging
from threading import Thread
from typing import Any, Dict, Union

from smolagents import ToolCollection

from .agent_model import AgentRunInfo
from .nexent_agent import NexentAgent, ProcessType
from ...monitor import get_monitoring_manager

logger = logging.getLogger("run_agent")
logger.setLevel(logging.DEBUG)
monitoring_manager = get_monitoring_manager()


def _detect_transport(url: str) -> str:
    """
    Auto-detect MCP transport type based on URL format.
    
    Args:
        url: MCP server URL
        
    Returns:
        Transport type: 'sse' or 'streamable-http'
    """
    url_stripped = url.strip()
    
    # Check URL ending to determine transport type
    if url_stripped.endswith("/sse"):
        return "sse"
    elif url_stripped.endswith("/mcp"):
        return "streamable-http"
    
    # Default to streamable-http for unrecognized formats
    return "streamable-http"


def _normalize_mcp_config(mcp_host_item: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Normalize MCP host configuration to a dictionary format.
    
    Args:
        mcp_host_item: Either a string URL or a dict with 'url' and optional 'transport'
        
    Returns:
        Dictionary with 'url' and 'transport' keys
    """
    if isinstance(mcp_host_item, str):
        url = mcp_host_item
        transport = _detect_transport(url)
        return {"url": url, "transport": transport}
    elif isinstance(mcp_host_item, dict):
        url = mcp_host_item.get("url")
        if not url:
            raise ValueError("MCP host dict must contain 'url' key")
        transport = mcp_host_item.get("transport")
        if not transport:
            transport = _detect_transport(url)
        if transport not in ("sse", "streamable-http"):
            raise ValueError(f"Invalid transport type: {transport}. Must be 'sse' or 'streamable-http'")
        return {"url": url, "transport": transport}
    else:
        raise ValueError(f"Invalid MCP host item type: {type(mcp_host_item)}. Must be str or dict")


@monitoring_manager.monitor_endpoint("agent_run_thread", "agent_run_thread")
def agent_run_thread(agent_run_info: AgentRunInfo):
    try:
        mcp_host = agent_run_info.mcp_host
        if mcp_host is None or len(mcp_host) == 0:
            nexent = NexentAgent(
                observer=agent_run_info.observer,
                model_config_list=agent_run_info.model_config_list,
                stop_event=agent_run_info.stop_event
            )
            agent = nexent.create_single_agent(agent_run_info.agent_config)
            nexent.set_agent(agent)
            nexent.add_history_to_agent(agent_run_info.history)
            nexent.agent_run_with_observer(
                query=agent_run_info.query, reset=False)
        else:
            agent_run_info.observer.add_message(
                "", ProcessType.AGENT_NEW_RUN, "<MCP_START>")
            # Normalize MCP host configurations to support both string and dict formats
            mcp_client_list = [_normalize_mcp_config(item) for item in mcp_host]

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
                nexent.agent_run_with_observer(
                    query=agent_run_info.query, reset=False)

    except Exception as e:
        if "Couldn't connect to the MCP server" in str(e):
            mcp_connect_error_str = "MCP服务器连接超时。" if agent_run_info.observer.lang == "zh" else "Couldn't connect to the MCP server."
            agent_run_info.observer.add_message(
                "", ProcessType.FINAL_ANSWER, mcp_connect_error_str)
        else:
            agent_run_info.observer.add_message(
                "", ProcessType.FINAL_ANSWER, f"Run Agent Error: {e}")
        raise ValueError(f"Error in agent_run_thread: {e}")


@monitoring_manager.monitor_endpoint("agent_run", "agent_run")
async def agent_run(agent_run_info: AgentRunInfo):
    observer = agent_run_info.observer

    monitoring_manager.add_span_event("agent_run.started")
    thread_agent = Thread(target=agent_run_thread, args=(agent_run_info,))
    thread_agent.start()
    monitoring_manager.add_span_event("agent_run.thread_started")

    while thread_agent.is_alive():
        monitoring_manager.add_span_event("agent_run.get_cached_message")
        cached_message = observer.get_cached_message()
        monitoring_manager.add_span_event(
            "agent_run.get_cached_message_completed")
        for message in cached_message:
            yield message
            monitoring_manager.add_span_event("agent_run.yield_message")
            # Prevent artificial slowdown of model streaming output
            if len(cached_message) < 8:
                # Ensure streaming output has some time interval
                await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)

    # Ensure all messages are sent
    cached_message = observer.get_cached_message()
    for message in cached_message:
        yield message
