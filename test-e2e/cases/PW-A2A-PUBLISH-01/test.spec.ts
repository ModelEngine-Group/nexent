import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { a2aProbe } from "../../infra/automation/d4/runner/a2a";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-A2A-PUBLISH-01", async (context) => {
  const { page, contract, expect } = context;
  const caseId = "PW-A2A-PUBLISH-01";
  const nonce = `${caseId}-${runToken(caseId)}`;
  const display = `A2A Publish ${runToken(caseId)}`;
  const marker = `A2A_PUBLISHED_${runToken(caseId)}`;
  const agents = new AgentPage(page);
  let agentId = 0;
  let endpoint = "";
  let version = "";
  let card: any;
  let called = false;
  let northboundUrl = "";
  contract.deferCleanup(async () => {
    if (!agentId) return;
    expect([200, 404]).toContain((await page.request.post(`/api/a2a/management/agents/${agentId}/disable`)).status());
    await agents.delete(agentId);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(configuredModel("llm").model).not.toBe(""); await loginCurrent(page, "tenant_a_admin"); await agents.open(); return "configured real LLM and editable Agent page are available"; },
      async () => { const settings = await a2aProbe(["config"]); northboundUrl = settings.northbound_url; return "controlled stack and configured Northbound service are available"; },
      async () => { expect(northboundUrl).toMatch(/^https?:\/\//); return "independent Python client uses configured endpoints and does not expose credentials to browser traces"; },
    ],
    steps: [
      async () => {
        agentId = await agents.create(display, `a2a_publish_${runToken(caseId)}`);
        registerReadyAsset("owned_a2a_local", String(agentId), String(agentId), caseId, {
          service: "config", identity: "tenant_a_admin", method: "DELETE", path: "/agent",
          json: { agent_id: agentId }, allowed_statuses: [200, 404],
        });
        await agents.selectModel(configuredModel("llm").displayName);
        await agents.setDescription(`Published A2A smoke ${nonce}`);
        await agents.setPrompts({ duty: `严格按用户要求输出标记，测试标记是 ${marker}。` });
        await agents.ensureAuthor(); await agents.openAdvanced(); await agents.openSection("发布属性");
        return "created a valid owned Draft and located current Publish Attributes under Advanced";
      },
      async () => {
        const section = await agents.openSection("发布属性");
        const row = section.locator(".ant-form-item").filter({ has: page.locator("label", { hasText: "启用 A2A" }) });
        const toggle = row.getByRole("switch"); await expect(toggle).toBeVisible();
        if (await toggle.getAttribute("aria-checked") !== "true") {
          const saved = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/api/agent/update") && r.request().postDataJSON()?.is_a2a === true);
          await toggle.click(); expect((await saved).status()).toBe(200);
        }
        return "enabled A2A through UI and awaited the actual autosave response";
      },
      async () => {
        const publication = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes(`/api/agent/${agentId}/publish`));
        await agents.publishVersion(`a2a-${runToken(caseId)}`, "Owned A2A external smoke");
        const body = await (await publication).json(); const data = body.data || body;
        endpoint = String(data.a2a_agent_card?.endpoint_id || data.a2a_agent?.endpoint_id || "");
        version = String(data.version_no || "");
        expect(endpoint).not.toBe(""); expect(version).not.toBe("");
        registerReadyAsset("owned_a2a_server", String(agentId), String(agentId), caseId, {
          service: "config", identity: "tenant_a_admin", method: "POST",
          path: `/a2a/management/agents/${agentId}/disable`, allowed_statuses: [200, 404],
        });
        return "published a real version and captured its dynamic A2A endpoint";
      },
      async () => { const response = await page.request.get(`/api/a2a/management/agents/${agentId}/settings`); expect(response.status()).toBe(200); const row = (await response.json()).data; expect(row.endpoint_id).toBe(endpoint); expect(String(row.version)).toBe(version); return "A2A registration refers to the published Agent version"; },
      async () => { card = await a2aProbe(["card", "--endpoint", endpoint, "--version", version]); return "independent client discovered the actual published Agent Card"; },
      async () => { expect(String(card.version)).toBe(version); expect(card.interfaces.length).toBeGreaterThan(0); expect(card.interfaces.some((row: any) => row.url.includes(endpoint))).toBe(true); return "the Card exposes this exact endpoint and published version"; },
      async () => { const result = await a2aProbe(["call", "--endpoint", endpoint, "--version", version, "--nonce", nonce, "--marker", marker]); expect(result.marker_verified).toBe(true); called = true; return "independent authenticated external call returned the required real-model marker"; },
      async () => {
        expect((await page.request.post(`/api/a2a/management/agents/${agentId}/disable`)).status()).toBe(200);
        const absent = await page.request.get(`${northboundUrl}/nb/a2a/${endpoint}/.well-known/agent-card.json`);
        expect(absent.status()).toBe(404);
        return "disabled only the owned endpoint and confirmed it is no longer discoverable";
      },
    ],
    assertions: [
      async () => { expect(agentId).toBeGreaterThan(0); expect(endpoint).not.toBe(""); expect(String(card.version)).toBe(version); return "publication and A2A registration refer to the same owned version"; },
      async () => { expect(called).toBe(true); return "external discovery and invocation both completed against the real service"; },
      async () => { const response = await page.request.get(`${northboundUrl}/nb/a2a/${endpoint}/.well-known/agent-card.json`); expect(response.status()).toBe(404); return "unpublished endpoint remains undiscoverable"; },
    ],
  });
});
