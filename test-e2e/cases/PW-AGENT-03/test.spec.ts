import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-AGENT-03", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-AGENT-03");
  const toolName = "get_test_code";
  const agents = new AgentPage(page);
  const wirePath = process.env.NEXENT_TEST_MCP_WIRE_LOG || "";
  let agentDisplay = "";
  let skillName = "";
  let alternateId = 0;
  let alternateDisplay = "";
  let wireOffset = 0;
  let toolAnswer = "";
  let skillAnswer = "";
  let agentId = 0;
  let serviceName = "";
  let expectedToolId = 0;

  const assertOwnedToolBinding = async () => {
    const response = await page.request.post("/api/agent/search_info", {
      data: { agent_id: agentId, version_no: 0 },
    });
    expect(response.ok()).toBe(true);
    const payload = await response.json();
    const agent = payload.data || payload;
    expect(agent.tools.some((tool: any) => Number(tool.tool_id || tool.id) === expectedToolId)).toBe(true);
  };

  contract.deferCleanup(async () => {
    if (alternateId > 0) await agents.delete(alternateId);
    if (agentId > 0) await agents.delete(agentId);
  });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        agentDisplay = `D4 Tool Skill ${token}`;
        await agents.open();
        agentId = await agents.create(agentDisplay, `d4_tool_skill_${token.replace(/[^a-z0-9_]/gi, "_")}`);
        const modelName = configuredModel("llm").displayName;
        await agents.selectModel(modelName);
        await agents.setDescription(`Tool and Skill binding validation ${token}`);
        await agents.setPrompts({ duty: `按要求调用工具并遵循已绑定技能；case=${token}` });
        expect(toolName).toBe("get_test_code");
        return `created isolated Draft with exact model ${modelName}; controlled Test MCP tool ${toolName} is expected from the locally managed service`;
      },
      async () => {
        skillName = resolveReadyAsset("skills", "configurable_name", "PW-AGENT-03");
        expect(skillName).not.toBe("");
        return `resolved fixed READY Skill ${skillName}`;
      },
      async () => {
        serviceName = resolveReadyAsset("mcp", "service_name", "PW-AGENT-03");
        const listed = await page.request.get("/api/tool/list");
        expect(listed.ok()).toBe(true);
        const payload = await listed.json();
        const tools = Array.isArray(payload) ? payload : payload.data || payload.tools || [];
        const matches = tools.filter((tool: any) => tool.source === "mcp"
          && tool.usage === serviceName && tool.origin_name === toolName);
        expect(matches).toHaveLength(1);
        expectedToolId = Number(matches[0].tool_id || matches[0].id);
        expect(expectedToolId).toBeGreaterThan(0);
        expect(wirePath).not.toBe("");
        wireOffset = existsSync(wirePath) ? readFileSync(wirePath, "utf8").length : 0;
        return `real LLM tool calling is configured; wire evidence will be read from ${wirePath}`;
      },
    ],
    steps: [
      async () => {
        await agents.openBasic();
        return `selected editable Draft ${agentDisplay} in Basic configuration`;
      },
      async () => {
        await agents.openToolsSkills();
        return "opened the product Tools & Skills tab";
      },
      async () => {
        await agents.bindToolFromService(serviceName, toolName);
        await assertOwnedToolBinding();
        return `selected ${toolName} from the current-case service ${serviceName}; persisted tool id=${expectedToolId}`;
      },
      async () => {
        await agents.bindSkill(skillName);
        return `searched and bound READY Skill ${skillName}`;
      },
      async () => {
        alternateDisplay = `D4 Switch ${token}`;
        await agents.open();
        alternateId = await agents.create(alternateDisplay, `d4_switch_${token}`);
        await agents.select(agentDisplay);
        await agents.openToolsSkills();
        await assertOwnedToolBinding();
        await expect(page.getByText(toolName, { exact: true }).first()).toBeVisible();
        await expect(page.getByText(skillName, { exact: true }).first()).toBeVisible();
        return "switched to a second Draft and back; both Tool and Skill autosaves were recovered";
      },
      async () => {
        await agents.openDebug();
        toolAnswer = await agents.sendDebug(`必须调用工具 ${toolName}，然后只回复工具返回的测试编号。`, "NX-92831");
        return "Debug submitted an explicit real tool-call request through the configured LLM";
      },
      async () => {
        expect(toolAnswer).toContain("NX-92831");
        await expect(page.getByText(toolName, { exact: true }).last()).toBeVisible();
        return "the visible tool execution reached a terminal state and final answer contained NX-92831";
      },
      async () => {
        skillAnswer = await agents.sendDebug(`根据当前绑定技能的指导回答，并在答案中原样包含技能名称：${skillName}`, skillName);
        return `a second completed Debug turn used the bound Skill context and returned ${skillName}`;
      },
      async () => {
        const delta = readFileSync(wirePath, "utf8").slice(wireOffset);
        const events = delta.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
        expect(events.some((event) => event.tool === toolName && event.result === "NX-92831")).toBe(true);
        return `Test MCP wire JSONL contains a real ${toolName} invocation and NX-92831 result`;
      },
    ],
    assertions: [
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        await agents.openToolsSkills();
        await assertOwnedToolBinding();
        await expect(page.getByText(toolName, { exact: true }).first()).toBeVisible();
        await expect(page.getByText(skillName, { exact: true }).first()).toBeVisible();
        return "Tool and Skill bindings survived a full refresh";
      },
      async () => {
        expect(toolAnswer).toContain("NX-92831");
        return "the real LLM produced a usable tool call and the deterministic marker";
      },
      async () => {
        const delta = readFileSync(wirePath, "utf8").slice(wireOffset);
        expect(delta).toContain('"tool": "get_test_code"');
        expect(skillAnswer).toContain(skillName);
        return "wire evidence proves the request reached Test MCP and the Skill turn completed independently";
      },
    ],
  });
});
