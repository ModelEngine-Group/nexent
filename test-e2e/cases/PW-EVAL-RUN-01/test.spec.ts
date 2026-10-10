import type { Locator } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";

const required = (name: string) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required from the controller's evaluation preparation`);
  return value;
};
const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

journey("PW-EVAL-RUN-01", async (context) => {
  const { page, expect, contract } = context;
  const agent = required("NEXENT_TEST_EVAL_AGENT");
  const version = required("NEXENT_TEST_EVAL_AGENT_VERSION");
  const judge = required("NEXENT_TEST_EVAL_JUDGE_MODEL");
  const evaluator = required("NEXENT_TEST_EVALUATOR");
  const setName = required("NEXENT_TEST_EVAL_SET");
  let runId = 0;
  let terminal = "";
  let trialAnswer = "";
  let runScore: number | undefined;
  const drawer = page.getByRole("dialog", { name: "创建评测", exact: true });
  const card = (title: RegExp) => drawer.locator(".ant-card").filter({
    has: page.locator(".ant-card-head-title").filter({ hasText: title }),
  });
  const choose = async (control: Locator, label: string | RegExp) => {
    await control.click();
    // Some product Selects filter numeric option values, not display labels.
    // Traverse the virtualized list with real keyboard input instead of
    // filtering the desired label away or injecting a DOM selection.
    const listId = await control.getAttribute("aria-controls");
    if (!listId) throw new Error("Select omitted its linked option list");
    const popup = page.locator(".ant-select-dropdown").filter({ has: page.locator(`[id='${listId}']`) });
    const option = popup.locator(".ant-select-item-option:visible").filter({
      has: page.locator(".ant-select-item-option-content").getByText(label, { exact: typeof label === "string" }),
    });
    await expect(popup).toBeVisible();
    await control.press("Home");
    for (let index = 0; index < 500 && !(await option.count()); index += 1) {
      await control.press("ArrowDown");
    }
    await expect(option).toHaveCount(1);
    await option.click();
    await page.keyboard.press("Escape");
    await expect(popup).toBeHidden();
  };
  const ownedRow = () => page.locator(`tr[data-row-key='${runId}']`);
  contract.deferCleanup(async () => {
    if (!runId) return;
    const response = await page.request.delete(`/api/agent-evaluations/${runId}`);
    if (![200, 404].includes(response.status())) throw new Error(`owned evaluation cleanup returned ${response.status()}`);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => `controller prepared published Agent ${agent} version ${version}`,
      async () => `real configured Judge model ${judge}`,
      async () => `published deterministic Evaluator ${evaluator}`,
      async () => `owned one-case Evaluation Set ${setName}`,
    ],
    steps: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        await page.goto(appPath("/evaluation"));
        await page.getByRole("tab", { name: "评测", exact: true }).click();
        await page.getByRole("button", { name: "创建评测", exact: true }).click();
        await expect(drawer).toBeVisible();
        return "opened the current Create Evaluation drawer";
      },
      async () => {
        const controls = card(/^智能体配置$/).getByRole("combobox");
        await choose(controls.nth(0), agent);
        await choose(controls.nth(1), new RegExp(`^v\\d+ \\(${escape(version)}\\)$`));
        return `selected exact published Agent and version ${version}`;
      },
      async () => {
        await choose(card(/^评测配置$/).getByRole("combobox").last(), judge);
        return `selected configured real Judge ${judge}`;
      },
      async () => {
        const response = await page.request.get("/api/evaluators");
        expect(response.ok()).toBe(true);
        const payload = await response.json();
        const selected = (payload.data || payload.items || []).filter((item: any) => item.name === evaluator);
        expect(selected).toHaveLength(1);
        expect(selected[0].status).toBe("PUBLISHED");
        expect(selected[0].evaluator_type).toBe("code");
        await choose(card(/^评估器/).getByRole("combobox"), evaluator);
        return "selected published code Evaluator and verified catalog type/status without inventing CRUD controls";
      },
      async () => {
        // Ant RadioButton hides the native input; click its visible label.
        await drawer.getByText("有评测集评测", { exact: true }).click();
        await expect(drawer.getByRole("radio", { name: "有评测集评测", exact: true })).toBeChecked();
        await choose(card(/^评测配置$/).getByRole("combobox").first(), `${setName} (1)`);
        // Switching modes intentionally clears evaluators and field mappings.
        await choose(card(/^评估器/).getByRole("combobox"), evaluator);
        await expect(card(/^评估器/).locator(".ant-select-selection-item")).toContainText(evaluator);
        return "selected owned one-case Set; query/expected/actual use the product's automatic mappings";
      },
      async () => {
        await expect(card(/^评估器/).locator(".ant-select-selection-item")).toContainText(evaluator);
        const [response] = await Promise.all([
          page.waitForResponse((r) => r.request().method() === "POST" && /\/agent-evaluations\/trial-run$/.test(new URL(r.url()).pathname), { timeout: 420000 }),
          (async () => {
            const submitted = page.waitForRequest((r) => r.method() === "POST" && /\/agent-evaluations\/trial-run$/.test(new URL(r.url()).pathname), { timeout: 30000 });
            await drawer.getByRole("button", { name: "试运行", exact: true }).click();
            const request = await submitted;
            expect(request.postDataJSON().evaluator_ids).toHaveLength(1);
          })(),
        ]);
        expect(response.ok()).toBe(true);
        const payload = await response.json();
        const result = payload.data || payload;
        trialAnswer = String(result.answer || "");
        expect(trialAnswer).toContain("NX-EVAL-92831");
        expect(Object.keys(result.scores || {})).toContain(evaluator);
        const modal = page.getByRole("dialog", { name: "试运行结果", exact: true });
        await expect(modal).toContainText("NX-EVAL-92831");
        await expect(modal).toContainText(evaluator);
        await modal.getByRole("button", { name: "Close", exact: true }).click();
        return "real Agent/Evaluator trial returned fixed answer and score in the separate result modal";
      },
      async () => {
        const created = page.waitForResponse((r) => r.request().method() === "POST" && /\/agent-evaluations$/.test(new URL(r.url()).pathname));
        await drawer.getByRole("button", { name: "发起评测", exact: true }).click();
        const response = await created;
        expect(response.ok()).toBe(true);
        const payload = await response.json();
        const result = payload.data || payload;
        runId = Number(result.agent_evaluation_id);
        expect(Number.isInteger(runId) && runId > 0).toBe(true);
        expect(["PENDING", "RUNNING", "COMPLETED"]).toContain(result.status);
        await expect(drawer).toBeHidden();
        return `created formal run id=${runId}; ownership captured before polling or UI assertions`;
      },
      async () => {
        await expect(ownedRow()).toBeVisible();
        await expect(ownedRow()).toContainText(/等待中|运行中|已完成|失败/);
        return "located only the created row; fast completion is not mistaken for missing pending state";
      },
      async () => {
        let last: any = {};
        await expect.poll(async () => {
          const response = await page.request.get(`/api/agent-evaluations/${runId}`);
          expect(response.ok()).toBe(true);
          const payload = await response.json();
          last = payload.data || payload;
          return last.status;
        }, { timeout: 420000, intervals: [5000, 10000] }).toMatch(/^(COMPLETED|FAILED)$/);
        terminal = last.status;
        if (terminal !== "COMPLETED") {
          const error = new Error(`owned evaluation run ${runId} failed: ${last.error_message || "no detail"}`);
          error.name = "ProductFailure";
          throw error;
        }
        runScore = Number(last.score_overall);
        expect(runScore).toBe(1);
        await expect(ownedRow()).toContainText("已完成", { timeout: 30000 });
        return `run ${runId} reached COMPLETED and scored 1 against the fixed marker`;
      },
      async () => {
        await ownedRow().locator("button:has(svg.lucide-eye)").click();
        await expect(page).toHaveURL(new RegExp(`/evaluation/${runId}$`));
        return "opened exact owned run detail through its view button";
      },
      async () => {
        await expect(page.getByText("NX-EVAL-92831", { exact: true }).first()).toBeVisible();
        await expect(page.getByRole("cell", {name:`${evaluator}:1.00`,exact:true})).toBeVisible();
        await expect(page.getByRole("columnheader", {name:"得分",exact:true})).toBeVisible();
        return "detail exposes actual case output, evaluator and score for this owned run";
      },
    ],
    assertions: [
      async () => `explicit prepared entities selected: ${agent}, ${version}, ${setName}`,
      async () => { expect(trialAnswer).toContain("NX-EVAL-92831"); expect(terminal).toBe("COMPLETED"); return "trial and formal run used real runtime calls"; },
      async () => { expect(runScore).toBe(1); await expect(page).toHaveURL(new RegExp(`/evaluation/${runId}$`)); return "completed detail and expected deterministic score are consistent"; },
      async () => "Evaluator catalog used read-only; no invented edit action executed",
    ],
  });
});
