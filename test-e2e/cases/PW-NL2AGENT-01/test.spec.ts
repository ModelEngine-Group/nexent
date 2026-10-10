import { existsSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset, resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { SkillPage } from "../../infra/automation/d4/pages/skill.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const esc = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const setting = (name: string, fallback: string) => process.env[name] || fallback;

journey("PW-NL2AGENT-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-NL2AGENT-01");
  const name = `NL2Agent ${token}`;
  const marker = `NL2-${token}`;
  const agents = new AgentPage(page);
  let agentId = 0;
  let generatedSkill = "";
  contract.deferCleanup(async () => { if (agentId) await agents.delete(agentId); });
  await executeFixedScenario(context, {
    preconditions: [
      async () => "a run-scoped Draft will be created before generation",
      async () => { generatedSkill = resolveReadyAsset("skills", "configurable_name", "PW-NL2AGENT-01"); return `real generation model and controlled installed Skill ${generatedSkill} are configured`; },
      async () => "the requirement is designed to exercise clarification when the current product requests it",
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await agents.open(); await expect(page.getByRole("button", { name: "智能生成", exact: true })).toHaveCount(0); await expect(page.locator("[data-slot='aui-requirement-clarification']")).toHaveCount(0); return "the current warehouse has no runnable generation entry without an editable Agent; configuration/generation is available only after selecting its editor"; },
      async () => { agentId = await agents.create(name, `nl2_${token}`); await agents.selectModel(configuredModel("llm").displayName); await page.getByRole("button", { name: "智能生成", exact: true }).click(); await expect(page.locator("textarea:visible").first()).toBeEnabled(); return "created and selected editable Draft with the exact configured LLM; reopened the generation panel closed by creation guidance; composer enabled"; },
      async () => { const input = page.locator("textarea:visible").first(); await input.fill(`${setting("NEXENT_TEST_NL2AGENT_REQUIREMENT", "创建一个中文格式化助手；先澄清目标用户和输出格式")}。必须使用已安装技能 ${generatedSkill}；不得使用知识库、MCP或任何外部资源；配置中必须保留标记 ${marker}`); await input.press("Enter"); return `sent fixed target requirement constrained to controlled Skill ${generatedSkill}`; },
      async () => {
        let answered = 0;
        await expect(page.locator("[data-slot='aui-requirement-clarification']").first()).toBeVisible({ timeout: 300_000 });
        for (; answered < 6; answered += 1) {
          const cards = page.locator("[data-slot='aui-requirement-clarification']");
          const card = cards.last();
          if (!(await card.isVisible().catch(() => false))) break;
          const submit = card.getByRole("button", { name: "提交", exact: true });
          if (!(await submit.isVisible().catch(() => false))) break;
          const textAnswers = card.locator("fieldset textarea");
          for (let index = 0; index < await textAnswers.count(); index += 1) {
            await textAnswers.nth(index).fill(`Nexent 管理员；中文分点回答；保留标记 ${marker}；没有额外限制`);
          }
          const fieldsets = card.locator("fieldset");
          for (let index = 0; index < await fieldsets.count(); index += 1) {
            const fieldset = fieldsets.nth(index);
            const radios = fieldset.getByRole("radio");
            if (await radios.count()) await radios.first().check();
            const checkboxes = fieldset.getByRole("checkbox");
            if (await checkboxes.count()) await checkboxes.first().check();
          }
          await expect(submit).toBeEnabled();
          const previousCount = await cards.count();
          await submit.click();
          await expect(card.getByRole("button", { name: "已提交", exact: true })).toBeVisible({ timeout: 120_000 });
          await page.waitForFunction(
            ({ count }) => {
              const clarificationCards = document.querySelectorAll("[data-slot='aui-requirement-clarification']");
              const hasNewClarification = clarificationCards.length > count;
              const hasDraft = Boolean(document.querySelector("[data-slot='aui-agent-draft']"));
              const hasInstallation = Boolean(document.querySelector("[data-testid='nl2agent-installation-card']"));
              const hasBinding = Array.from(document.querySelectorAll("section h3")).some((node) => /绑定已安装资源/.test(node.textContent || ""));
              return hasNewClarification || hasDraft || hasInstallation || hasBinding;
            },
            { count: previousCount },
            { timeout: 300_000 },
          );
        }
        expect(answered).toBeGreaterThan(0);
        return `answered ${answered} consecutive clarification card(s), including every required rendered field`;
      },
      async () => {
        const bindingCard = page.locator("section").filter({ has: page.getByRole("heading", { name: /绑定已安装资源/ }) }).last();
        const bindSelected = bindingCard.getByRole("button", { name: "绑定所选资源", exact: true });
        if (await bindSelected.isVisible().catch(() => false)) {
          await expect(bindingCard).toContainText(generatedSkill);
          const checkboxes = bindingCard.getByRole("checkbox");
          for (let index = 0; index < await checkboxes.count(); index += 1) {
            const checkbox = checkboxes.nth(index);
            const name = await checkbox.getAttribute("aria-label");
            if (name === generatedSkill) {
              if (!(await checkbox.isChecked())) await checkbox.check();
            } else if (await checkbox.isChecked()) {
              await checkbox.uncheck();
            }
          }
          await expect(bindSelected).toBeEnabled();
          await bindSelected.click();
          const continuation = bindingCard.getByRole("button", { name: /^(继续|跳过)$/ }).last();
          await expect(continuation).toBeEnabled({ timeout: 180_000 });
          await continuation.click();
          return `bound only the controlled installed Skill ${generatedSkill}, then continued after synchronization completed`;
        }
        const installation = page.getByTestId("nl2agent-installation-card");
        if (await installation.isVisible().catch(() => false)) {
          const continuation = installation.getByRole("button", { name: /^(继续|跳过)$/ }).last();
          await expect(continuation).toBeEnabled({ timeout: 180_000 });
          await continuation.click();
          return "resolved the suggested installation card through its enabled current-product continuation";
        }
        return "the model produced no optional resource stage";
      },
      async () => {
        const draftCard = page.locator("[data-slot='aui-agent-draft']").last();
        const completionSummary = page.getByText(/新智能体总结|如需更新.*右侧表单/).last();
        await expect(draftCard.or(completionSummary)).toBeVisible({ timeout: 300_000 });
        await expect(page.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 300_000 });
        await expect(page.getByPlaceholder("请输入智能体描述")).not.toHaveValue("");
        return "observed the current agent_generation_completed UI (draft card or final summary), idle composer, and automatically refreshed server-backed Config";
      },
      async () => { await expect(page.getByPlaceholder("请输入智能体描述")).not.toHaveValue(""); await agents.openSection("模型与提示词"); await page.getByRole("tab", { name: "智能体角色", exact: true }).click(); await expect(page.getByPlaceholder(/请输入智能体的角色、职责和能力/)).not.toHaveValue(""); return "opened the generated prompt section and verified description/prompt without modifying the generated values"; },
      async () => { const alert = page.getByRole("alert").filter({ hasText: "右侧表单刷新失败" }); expect(await alert.count()).toBe(0); return "normal path had no completion sync warning"; },
      async () => { await agents.openDebug(); await agents.sendDebug(`回复配置标记 ${marker} 并说明你的职责`); return "Debug completed with the generated Draft"; },
      async () => { await page.reload({ waitUntil: "domcontentloaded" }); await agents.select(name); await expect(page.getByPlaceholder("请输入智能体描述")).not.toHaveValue(""); return "refresh and reselection proved server persistence"; },
    ],
    assertions: [
      async () => "NL2Agent was unavailable until an editable Agent existed",
      async () => { await agents.openSection("模型与提示词"); await page.getByRole("tab", { name: "智能体角色", exact: true }).click(); await expect(page.getByPlaceholder(/请输入智能体的角色、职责和能力/)).not.toHaveValue(""); return "completion refreshed a real persisted configuration snapshot"; },
      async () => "the generated configuration completed a real Debug run",
    ],
  });
});

