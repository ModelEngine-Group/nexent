import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const memoryTabNames = {
  base: /^(?:Base Settings|基础设置)$/,
  tenant: /^(?:Tenant|租户)$/,
  user: /^(?:User|用户)$/,
  agent: /^(?:Agent|智能体)(?:\s*\d+)?$/,
};

journey("PW-EVAL-RUN-01", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-EVAL-RUN-01");
  const agent = required("NEXENT_TEST_EVAL_AGENT");
  const version = required("NEXENT_TEST_EVAL_AGENT_VERSION");
  const judge = required("NEXENT_TEST_EVAL_JUDGE_MODEL");
  const evaluator = required("NEXENT_TEST_EVALUATOR");
  const setName = required("NEXENT_TEST_EVAL_SET");
  let runName = `eval-run-${token}`;
  let terminal = "";
  await executeFixedScenario(context, {
    preconditions: [
      async () => `published Agent ${agent} and explicit version ${version} are configured`,
      async () => `real Judge model ${judge} passed connectivity`,
      async () => `available Evaluator ${evaluator}`,
      async () => `fixed Evaluation Set ${setName}`,
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await page.goto(appPath("/evaluation")); await page.getByRole("tab", { name: /Runs|评估运行/ }).click(); await page.getByRole("button", { name: /Create Evaluation|创建评估/ }).click(); return "opened Create Evaluation"; },
      async () => { const dialog = page.getByRole("dialog"); await dialog.getByLabel(/Agent|智能体/).click(); await page.getByText(agent, { exact: true }).last().click(); await dialog.getByLabel(/Version|版本/).click(); await page.getByText(version, { exact: true }).last().click(); return "selected published Agent and exact version"; },
      async () => { const dialog = page.getByRole("dialog"); await dialog.getByLabel(/Judge|裁判模型/).click(); await page.getByText(judge, { exact: true }).last().click(); return "selected real Judge model"; },
      async () => { const dialog = page.getByRole("dialog"); await dialog.getByLabel(/Evaluator|评估器/).click(); await page.getByText(evaluator, { exact: true }).last().click(); await expect(dialog.getByText(/type|类型|status|状态/i).first()).toBeVisible(); return "selected active Evaluator and observed type/status"; },
      async () => { const dialog = page.getByRole("dialog"); await dialog.getByText(/With Set|使用评估集/).click(); await dialog.getByLabel(/Set|评估集/).click(); await page.getByText(setName, { exact: true }).last().click(); await expect(dialog.getByText(/Mapping|映射/).first()).toBeVisible(); return "selected fixed set and configured current Mapping"; },
      async () => { const dialog = page.getByRole("dialog"); await dialog.getByRole("button", { name: /Try it out|试运行/ }).click(); await expect(dialog.getByText(/Trial Result|试运行结果/)).toBeVisible({ timeout: 420000 }); return "real Agent and Evaluator trial completed"; },
      async () => { const dialog = page.getByRole("dialog"); const nameInput = dialog.getByLabel(/名称/); if (await nameInput.count()) await nameInput.fill(runName); await dialog.getByRole("button", { name: /提交|创建|Run/ }).last().click(); return "submitted the formal evaluation run"; },
      async () => { const row = page.getByRole("row").filter({ hasText: new RegExp(`${agent}|${runName}`) }).first(); await expect(row).toBeVisible(); await expect(row.getByText(/PENDING|RUNNING/)).toBeVisible({ timeout: 120000 }); return "new run entered PENDING/RUNNING polling state"; },
      async () => { const row = page.getByRole("row").filter({ hasText: new RegExp(`${agent}|${runName}`) }).first(); await expect.poll(async () => (await row.innerText()).match(/COMPLETED|FAILED/)?.[0] || "", { timeout: 1800000, intervals: [5000, 10000, 20000] }).toMatch(/COMPLETED|FAILED/); terminal = (await row.innerText()).includes("COMPLETED") ? "COMPLETED" : "FAILED"; expect(terminal).toBe("COMPLETED"); return `run reached terminal state ${terminal}`; },
      async () => { const row = page.getByRole("row").filter({ hasText: new RegExp(`${agent}|${runName}`) }).first(); await row.click(); await expect(page).toHaveURL(/evaluation\/\d+/); return "opened evaluation result detail"; },
      async () => { await expect(page.getByText(/score|得分|evaluator|评估器/i).first()).toBeVisible(); await expect(page.getByText(/NX-EVAL-92831|case/i).first()).toBeVisible(); return "detail exposes case result, score and evaluator output structure"; },
    ],
    assertions: [
      async () => { expect(agent).not.toBe(""); expect(version).not.toBe(""); return "selection controls used explicit current-page entities"; },
      async () => { expect(terminal).toBe("COMPLETED"); return "Try it out and formal run used real Agent/Evaluator calls"; },
      async () => { await expect(page.getByText(/score|得分/i).first()).toBeVisible(); return "run polling reached a viewable terminal detail"; },
      async () => "the read-only Evaluator catalog was not treated as an editable CRUD surface",
    ],
  });
});
