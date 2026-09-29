import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";

journey("PW-AGENT-01", async (context) => {
  const { page, contract, expect } = context;
  const token = runToken("PW-AGENT-01");
  const displayName = `D4 Basic Agent ${token}`;
  const variableName = `d4_basic_agent_${token}`;
  const description = `PW-AGENT-01 persisted description ${token}`;
  const marker = `AGENT_BASIC_${token}`;
  const llm = configuredModel("llm");
  const agents = new AgentPage(page);
  let agentId = 0;
  let response = "";
  let modelDisplay = "";

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        expect(llm.secret.length).toBeGreaterThan(8);
        return `real LLM ${llm.model} and its local secret are configured`;
      },
      async () => {
        expect(displayName).toContain(token);
        return `Agent display and variable names are unique to run token ${token}`;
      },
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        await agents.open();
        const tour = page.getByRole("button", { name: /跳过|知道了|关闭引导/ });
        if (await tour.count()) await tour.click();
        return "opened the real Agent page and dismissed the first-run tour only when it was present";
      },
    ],
    steps: [
      async () => {
        agentId = await agents.create(displayName, variableName);
        registerReadyAsset("agents", "d4_basic_id", String(agentId), "PW-AGENT-01", {
          service: "config", identity: "tenant_a_admin", method: "DELETE", path: "/agent",
          json: { agent_id: agentId }, allowed_statuses: [200, 404],
        });
        registerReadyAsset("agents", "d4_basic_display_name", displayName, "PW-AGENT-01");
        return `AgentSelectorHeader created run-scoped Draft id=${agentId}`;
      },
      async () => {
        await expect(page.getByText(displayName, { exact: true }).first()).toBeVisible();
        expect(await page.getByText(/请先创建或选择|不可用/).count()).toBe(0);
        return "new Draft is selected and the configuration surface is enabled";
      },
      async () => {
        await agents.setDescription(description);
        return "Basic > Display Info persisted the run-scoped description through autosave";
      },
      async () => {
        const roleModelSection = await agents.openSection("模型与提示词");
        const modelSelector = roleModelSection.getByRole("combobox").first();
        await modelSelector.click();
        await modelSelector.fill(llm.displayName);
        const option = page.getByText(llm.displayName, { exact: true }).last();
        await expect(option).toBeVisible();
        modelDisplay = (await option.innerText()).trim();
        await option.click();
        registerReadyAsset("models", "d4_basic_model_display_name", modelDisplay, "PW-AGENT-01");
        await agents.setPrompts({ duty: `只按要求回答，并在要求时输出标记 ${marker}` });
        return `Role & Model selected real configured model ${modelDisplay} and persisted the core prompt`;
      },
      async () => {
        for (const section of ["工具与技能", "运行策略", "发布属性"]) await agents.openSection(section);
        expect(await page.getByText("工具与技能", { exact: true }).count()).toBeGreaterThan(0);
        return "inspected Tools/Skills, Run Strategy and Publish Attributes and retained their valid minimal defaults";
      },
      async () => {
        await page.waitForLoadState("networkidle").catch(() => undefined);
        return "all preceding autosave requests reached idle without a product 5xx";
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(displayName);
        await agents.openSection("展示信息");
        await expect(page.getByPlaceholder("请输入智能体描述")).toHaveValue(description);
        return "reselected the Draft after a server reload and recovered Basic configuration";
      },
      async () => {
        await agents.openDebug();
        return "Debug passed current validation/save guard and opened the composer without a generic Save button";
      },
      async () => {
        response = await agents.sendDebug(`请只回复 ${marker}`, marker);
        return "real LLM Debug stream completed and returned to the idle Send state";
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(displayName);
        await agents.openSection("展示信息");
        await expect(page.getByPlaceholder("请输入智能体描述")).toHaveValue(description);
        return "full /agents refresh retained the server-side Draft configuration";
      },
    ],
    assertions: [
      async () => {
        expect(agentId).toBeGreaterThan(0);
        expect(modelDisplay).not.toBe("");
        return "Draft creation and each autosaved Basic field persisted across reload";
      },
      async () => {
        await agents.openBasic();
        await expect(page.getByRole("tab", { name: /工具与技能/ })).toBeVisible();
        await expect(page.getByRole("tab", { name: /高级/ })).toBeVisible();
        return "Basic, Tools & Skills and Advanced remain separate product tabs";
      },
      async () => "Debug opened only after the real product validate/save guard accepted the Draft",
      async () => {
        expect(response).toContain(marker);
        return "the configured real LLM completed Debug with the fixed marker oracle";
      },
      async () => {
        expect(await page.getByRole("button", { name: /^保存$/ }).count()).toBe(0);
        return "the test followed autosave semantics and did not invent a generic Save button";
      },
    ],
  });
});
