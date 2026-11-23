# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace

import pytest

from local_auth_http import native_runtime, runtime


@pytest.mark.case_id("EVOLUTION-TOOL-MAPPING-D3-001")
@pytest.mark.stage("D3")
def test_versioned_mapping(runtime):
    from fastapi import HTTPException
    from contracts.agentos import ToolBinding
    from infrastructure.mcp_execution import build_mcp_tool, mcp_execution_revision, select_mcp_server
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.rdb.mcp_execution_records import McpRecord, ToolInfo, ToolInstance, read_bound_mcp_tools, read_mcp_execution_servers
    from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, argument_digest
    from nexent.core.agents.resources.tools import ToolResources
    from runtime.agentos.prepared_mcp import PreparedMCP

    _, _, _, models = runtime
    models.TableBase.metadata.create_all(db_client.engine)
    tenant, agent, instance, name = "mapping-test", 34, 29, "lookup"
    mapping = {"day":{"kind":"iso_date"}}
    with get_db_session() as session:
        session.add(McpRecord(tenant_id=tenant,mcp_name="calendar",mcp_server="http://127.0.0.1:19976/mcp",enabled=True,status=True))
        info = ToolInfo(name=name,class_name=name,origin_name=name,author=tenant,source="mcp",usage="calendar",params=[],
                        inputs='{"day":{"type":"string","format":"date"}}',is_available=True)
        session.add(info)
        session.flush()
        for version, formats in [(1,None),(2,mapping)]:
            session.add(ToolInstance(agent_id=agent,tenant_id=tenant,tool_instance_id=instance,tool_id=info.tool_id,
                                     version_no=version,enabled=True,released_argument_formats=formats))
    def resource(version, formats):
        row, = read_bound_mcp_tools(agent,version,tenant,[name])
        sid, host = select_mcp_server(read_mcp_execution_servers(tenant),"calendar",tenant)
        rev = mcp_execution_revision(tenant,agent,version,instance,build_mcp_tool(row),name,sid,host)
        parameters = {"instance_id":instance,"tool_name":name,"server_id":sid,"revision":rev}
        if formats:
            parameters["argument_formats"] = formats
        return SimpleNamespace(agent_id=agent,version_no=version,skill_refs=[],tools=[
            ToolBinding(tool_id="mcp",version="1",parameters=parameters)])
    actor = SimpleNamespace(tenant_id=tenant)
    for version, trial, formats, actual in [(1,False,None,"2028/02/29"),(1,True,mapping,"2028-02-29"),(2,False,mapping,"2028-02-29")]:
        config, = PreparedMCP(actor,mapping_trial=trial).materialize(resource(version,formats))
        recorder = ReplayToolRecorder(SimpleNamespace(tools=[config]), {name:["day"]})
        sent = []
        template = SimpleNamespace(name=name,inputs={"day":{}, "tenant_id":{}},_nexent_mcp_formats=mapping,
                                   forward=lambda **values: sent.append(values))
        resources = ToolResources()
        resources.mcp_tool_collection=SimpleNamespace(tools=[template])
        resources.user_context={"tenant_id":tenant}
        resources.observer=SimpleNamespace(replay_tool_recorder=recorder)
        resources.create_tool(config).forward(day="2028/02/29",tenant_id="untrusted")
        call, = recorder.receipt()["calls"]
        assert sent == [{"tenant_id":tenant, "day":actual}]
        assert call["arguments"] == {"day":argument_digest(actual)}
        assert call["requested_arguments"] == {"day":argument_digest("2028/02/29")}
    for version, injected in ((1,mapping),(2,None)):
        with pytest.raises(ValueError,match="not published"):
            PreparedMCP(actor).materialize(resource(version,injected))
    with pytest.raises(HTTPException) as denied:
        PreparedMCP(SimpleNamespace(tenant_id="another")).materialize(resource(2,mapping))
    assert denied.value.status_code == 404
