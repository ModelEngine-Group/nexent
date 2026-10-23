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
  const skillMarker = `SKILL_RESULT_${token}`;
  let skillCreated = false;
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
    if (!skillCreated) return;
    const removed = await page.request.delete(`/api/skills/${encodeURIComponent(skillName)}`);
    expect([200, 404]).toContain(removed.status());
    const absent = await page.request.get(`/api/skills/${encodeURIComponent(skillName)}`);
    expect(absent.status()).toBe(404);
  });
  // Cleanup callbacks run in reverse: detach/delete Agents before the Skill.
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
        skillName = `d4-verify-${token}`;
        const created = await page.request.post("/api/skills", { data: {
          name: skillName, description: "Use this verification skill when asked to run the bound validation skill.",
          content: `---\nname: ${skillName}\ndescription: Run the bound validation skill.\n---\n\n`
            + "# Validation procedure\nRead references/check.txt with read_skill_md before answering. "
            + "Return exactly its verification result. Do not reuse a previous Tool answer or call get_test_code.\n",
          source: "custom", tags: ["automation"],
          files: [{ path: "references/check.txt", content: `Verification result: ${skillMarker}\n` }],
        } });
        expect(created.status()).toBe(201);
        skillCreated = true;
        return `created owned Skill ${skillName} with an independent reference-only result; the answer is absent from the question`;
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
        // A page reload resets the debug-only local runtime. The prior Tool
        // turn's "reply only with the code" instruction must not contaminate
        // an independent Skill-consumption acceptance.
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        await agents.openDebug();
        const panel = page.getByRole("heading", { name: /^(调试|Debug)$/ }).locator("xpath=ancestor::section[1]");
        await expect(panel.locator("[data-slot='aui_assistant-message-root']")).toHaveCount(0);
        skillAnswer = await agents.sendDebug("执行当前绑定的验证技能：先读取技能指南及 references/check.txt，再只回复其中规定的验证结果。", skillMarker);
        return "an independent fresh Debug session returned the reference-only Skill result, not a question echo or previous Tool result";
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
        return "wire evidence proves the request reached Test MCP";
      },
      async () => {
        expect(skillAnswer).toContain(skillMarker);
        return "the independent Skill turn returned its reference-only answer; owned resources are covered by deferred cleanup";
      },
    ],
  });
});
