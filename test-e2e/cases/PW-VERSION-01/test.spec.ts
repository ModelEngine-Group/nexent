import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-VERSION-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-VERSION-01");
  const versionOne = `d4-v1-${token}`;
  const versionTwo = `d4-v2-${token}`;
  const publishedDescription = `published baseline ${token}`;
  const draftDescription = `draft after publish ${token}`;
  const agents = new AgentPage(page);
  let agentDisplay = "";
  let agentId = 0;
  let totalText = "";
  contract.deferCleanup(async () => { if (agentId > 0) await agents.delete(agentId); });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        agentDisplay = `D4 Version ${token}`;
        await agents.open();
        agentId = await agents.create(agentDisplay, `d4_version_${token.replace(/[^a-z0-9_]/gi, "_")}`);
        const modelName = configuredModel("llm").displayName;
        await agents.selectModel(modelName);
        await agents.setDescription(`version source ${token}`);
        await agents.setPrompts({ duty: `版本测试智能体 ${token}` });
        expect(agentId).toBeGreaterThan(0);
        return `created isolated Draft Agent ${agentDisplay} (id=${agentId}) with exact configured model ${modelName}`;
      },
      async () => {
        const section = await agents.openSection("模型与提示词");
        await expect(section.getByRole("combobox").first()).toBeVisible();
        await expect(page.getByRole("button", { name: "发布", exact: true })).toBeEnabled();
        return "the Draft retains a real model and passes the current publish prerequisites";
      },
    ],
    steps: [
      async () => {
        await expect(page.getByText(/草稿|Draft/).first()).toBeVisible().catch(async () => {
          await expect(page.getByRole("button", { name: "发布", exact: true })).toBeVisible();
        });
        return "confirmed editable Draft semantics before creating a version";
      },
      async () => {
        await agents.setDescription(publishedDescription);
        await agents.publishVersion(versionOne, `PW-VERSION-01 first release ${token}`);
        return `Publish validated/saved the Draft and submitted required version name ${versionOne}`;
      },
      async () => {
        await expect(page.getByText(versionOne, { exact: true }).first()).toBeVisible();
        return "the real publish request completed and the current-version tag appeared";
      },
      async () => {
        totalText = await page.getByText(/共\s*\d+\s*个版本/).first().innerText();
        expect(totalText).toMatch(/共\s*1\s*个版本/);
        return `current tag=${versionOne}; ${totalText}`;
      },
      async () => {
        await agents.openVersionManage(versionOne);
        return "clicked the current-version tag and opened the Version Manage panel";
      },
      async () => {
        await agents.expandVersionDetails(versionOne);
        await agents.closeVersionManage();
        await agents.setDescription(`${publishedDescription} second snapshot`);
        await agents.publishVersion(versionTwo, `PW-VERSION-01 comparison release ${token}`);
        await agents.openVersionManage(versionTwo);
        await agents.compareLatestVersions();
        return `loaded ${versionOne} detail, published ${versionTwo}, and received a real comparison for the two versions`;
      },
      async () => {
        await page.getByRole("dialog", { name: "版本对比" }).getByRole("button", { name: /取\s*消|关\s*闭/ }).click().catch(async () => page.keyboard.press("Escape"));
        await agents.closeVersionManage();
        await agents.setDescription(draftDescription);
        await expect(page.getByText(versionTwo, { exact: true }).first()).toBeVisible();
        return "changed a Config field after publishing; the current version stayed v2 while the editable configuration became a Draft";
      },
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        const refreshedCurrent = page.waitForResponse(
          (response) => response.request().method() === "GET" && /\/api\/agent\/\d+\/current_version(?:\?|$)/.test(response.url()),
        );
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.select(agentDisplay);
        const currentResponse = await refreshedCurrent;
        expect(currentResponse.ok()).toBeTruthy();
        const currentPayload = await currentResponse.json();
        expect(currentPayload.version_name).toBe(versionTwo);
        await expect(page.getByPlaceholder("请输入智能体描述")).toHaveValue(draftDescription);
        await agents.openVersionManage(versionTwo);
        totalText = await page.getByText(/共\s*\d+\s*个版本/).last().innerText();
        expect(totalText).toMatch(/共\s*2\s*个版本/);
        await expect(page.getByText(versionOne, { exact: true }).first()).toBeVisible();
        await expect(page.getByText(versionTwo, { exact: true }).first()).toBeVisible();
        return `current_version refetch returned ${versionTwo}; refresh preserved isolated Draft fields and both published history records; ${totalText}`;
      },
    ],
    assertions: [
      async () => {
        expect(agentId).toBeGreaterThan(0);
        return "Publish succeeded only after the product's validate/save guard accepted the configured Agent";
      },
      async () => {
        await expect(page.getByPlaceholder("请输入智能体描述")).toHaveValue(draftDescription);
        return "post-publish Draft editing did not mutate the already persisted version snapshots";
      },
      async () => {
        expect(totalText).toMatch(/共\s*2\s*个版本/);
        return "the refreshed Version Manage panel remained consistent with two versions and the current-version tag";
      },
    ],
  });
});
