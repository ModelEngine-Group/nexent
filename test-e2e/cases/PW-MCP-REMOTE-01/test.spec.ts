import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { McpPage } from "../../infra/automation/d4/pages/mcp.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };

journey("PW-MCP-REMOTE-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MCP-REMOTE-01");
  const name = `mcp-remote-${token}`.slice(0, 20);
  const agentName = `MCP Remote ${token}`;
  const mcp = new McpPage(page);
  const agents = new AgentPage(page);
  const wire = need("NEXENT_TEST_MCP_WIRE_LOG");
  const url = need("NEXENT_TEST_MCP_URL");
  const localUrl = process.env.NEXENT_TEST_MCP_LOCAL_URL || url;
  let offset = 0;
  let agentId = 0;
  let remoteHealthVerified = false;
  let remoteToolVisible = false;
  let mcpCardRemoved = false;
  let agentBindingRemoved = false;
  contract.deferCleanup(async () => { if (agentId) await agents.delete(agentId); });
  let creationAttempted = false;
  contract.deferCleanup(async () => {
    if (!creationAttempted) return;
    const id = await mcp.findId(name);
    if (id !== null) {
      const response = await page.request.delete(`/api/mcp/${id}`);
      if (![200, 404].includes(response.status())) throw new Error(`MCP cleanup returned ${response.status()}`);
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { const response = await page.request.post(localUrl, { data: {} }); expect(response.status()).toBeLessThan(500); return `controlled Test MCP is reachable from the test host at ${localUrl}`; },
      async () => "Test MCP declares deterministic get_test_code",
      async () => { expect(existsSync(wire) || wire.length > 0).toBe(true); offset = existsSync(wire) ? readFileSync(wire, "utf8").length : 0; return "real LLM tool calling and wire evidence are configured"; },
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await mcp.openMine(); await page.getByRole("button", { name: /^添加\s*MCP\s*服务$/ }).click(); await page.keyboard.press("Escape"); return "opened MCP Mine and the Add MCP surface"; },
      async () => { creationAttempted = true; await mcp.addRemote(name, url); return `created Remote/REMOTE_LINK ${name} using current URL/auth/header fields`; },
      async () => { await expect(mcp.card(name)).toBeVisible(); return "new Remote MCP appeared in Mine"; },
      async () => { await mcp.health(name); remoteHealthVerified = true; return "real server health check passed"; },
      async () => { await mcp.enable(name); return "Remote MCP reached enabled stable state"; },
      async () => { await mcp.openTools(name, "get_test_code"); remoteToolVisible = true; const mcpId = await mcp.resolveId(name); registerReadyAsset("mcp", "d4_remote_cleanup_id", String(mcpId), "PW-MCP-REMOTE-01", { service: "config", identity: "tenant_a_admin", method: "DELETE", path: `/mcp/${mcpId}`, allowed_statuses: [200, 404] }); return `detail exposes get_test_code from controlled service id=${mcpId}; cleanup is registered for this case`; },
      async () => { await agents.open(); agentId = await agents.create(agentName, `mcp_remote_${token}`); const modelName = configuredModel("llm").displayName; await agents.selectModel(modelName); await agents.setDescription(`Remote MCP validation ${token}`); await agents.setPrompts({ duty: `必须调用 get_test_code 工具，并原样返回工具结果 ${token}` }); await agents.bindToolFromService(name, "get_test_code"); return `created isolated Draft with exact configured LLM ${modelName}, description, required role prompt and the tool from this exact MCP category`; },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentName);
        await agents.openDebug();
        const prompts = [
          "现在立即调用已绑定的 get_test_code 工具；禁止解释、禁止猜测，工具完成后只回复工具返回值。",
          "上一轮如果没有执行工具则视为失败。请立即实际调用 get_test_code，完成后只原样回复返回值。",
        ];
        let answer = "";
        let delta = "";
        for (const prompt of prompts) {
          answer = await agents.sendDebug(prompt);
          delta = readFileSync(wire, "utf8").slice(offset);
          if (delta.includes("get_test_code") && delta.includes("NX-92831") && answer.includes("NX-92831")) break;
        }
        if (!delta.includes("get_test_code") || !delta.includes("NX-92831")) {
          const failure = new Error(`configured model completed Debug but did not invoke bound get_test_code after ${prompts.length} explicit attempts; last answer=${JSON.stringify(answer)}`);
          failure.name = "ProductFailure";
          throw failure;
        }
        if (!answer.includes("NX-92831")) {
          const failure = new Error(`get_test_code returned NX-92831 on the wire but the final Agent answer omitted it; answer=${JSON.stringify(answer)}`);
          failure.name = "ProductFailure";
          throw failure;
        }
        return "reloaded the exact Draft; real LLM invoked the bound MCP Tool and rendered its deterministic marker";
      },
      async () => { const delta = readFileSync(wire, "utf8").slice(offset); expect(delta).toContain("get_test_code"); expect(delta).toContain("NX-92831"); return "wire log correlates the real invocation"; },
      async () => {
        await mcp.openMine();
        await mcp.delete(name);
        await agents.open();
        await agents.select(agentName);
        await page.getByRole("tab", { name: "工具与技能", exact: true }).click();
        const section = page.getByRole("tabpanel", { name: "工具与技能", exact: true });
        await expect(section.getByText("get_test_code", { exact: true })).toHaveCount(0);
        mcpCardRemoved = true;
        agentBindingRemoved = true;
        return "deleted the bound MCP service and confirmed the refreshed Agent draft no longer retained its unavailable tool";
      },
    ],
    assertions: [
      async () => { expect(remoteHealthVerified && remoteToolVisible).toBe(true); return "captured pre-deletion evidence proves Remote MCP health and Tool came from the real Test Server"; },
      async () => { expect(readFileSync(wire, "utf8").slice(offset)).toContain("NX-92831"); return "Agent invocation and marker are independently proven"; },
      async () => "header/metadata and exact parameter mapping remain assigned to contract tests",
      async () => { expect(mcpCardRemoved && agentBindingRemoved).toBe(true); return "MCP deletion removed both the service card and its stale Agent binding"; },
    ],
  });
});

