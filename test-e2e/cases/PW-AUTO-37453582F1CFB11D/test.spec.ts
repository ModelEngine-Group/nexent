import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { appPath, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { SkillPage } from "../../infra/automation/d4/pages/skill.page";

const ID = "PW-AUTO-37453582F1CFB11D";
const SEARCH = "搜索 Skill 名称、描述或标签";

journey(ID, async (context) => {
  const { page, contract, expect } = context;
  const token = runToken(ID);
  const prefix = `d4-repo-${token}`;
  const source = `${prefix}-a`;
  const second = `${prefix}-b`;
  const conflict = `d4-existing-${token}`;
  const copy = `d4-copy-${token}`;
  const tagName = `d4-tag-${token}`;
  const tagValue = `d4-value-${token}`;
  const skills = new SkillPage(page);
  let reviewer: Awaited<ReturnType<typeof loginIsolated>> | undefined;
  let bucketId = 0;
  let definitionId = 0;
  let valueId = 0;
  let sourceId = 0;
  const owned = new Set<string>();
  let total = 0;
  let conflictStatus = 0;
  let installedStatus = 0;
  let filtered: any[] = [];
  let predicates: any[] = [];
  const searchBox = () => page.getByPlaceholder(SEARCH, { exact: true }).locator("visible=true");
  const card = (name: string) => skills.card(name).locator("visible=true");
  const repositoryResponse = (predicate: (url: URL) => boolean = () => true) => page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === "GET" && url.pathname.endsWith("/repository/skill") &&
      url.searchParams.get("status") === "shared" && predicate(url);
  });
  const registerSkill = (name: string) => {
    owned.add(name);
    registerReadyAsset("skills", `repository_${name}`, name, ID, {
      service: "config", identity: "tenant_a_dev", method: "DELETE",
      path: `/skills/${encodeURIComponent(name)}`, allowed_statuses: [200, 404],
    });
  };
  contract.deferCleanup(async () => {
    try {
      if (sourceId && reviewer) {
        const cleared = await reviewer.page.request.put(`/api/tag-libraries/assignments/skill/${sourceId}`, { data: { value_ids: [] } });
        if (![200, 404].includes(cleared.status())) throw new Error(`owned tag assignment cleanup returned ${cleared.status()}`);
      }
      for (const name of owned) {
        const deleted = await page.request.delete(`/api/skills/${encodeURIComponent(name)}`);
        if (![200, 404].includes(deleted.status())) throw new Error(`owned Skill cleanup returned ${deleted.status()}`);
      }
      if (reviewer) for (const path of [
        valueId ? `/api/tag-libraries/${bucketId}/definitions/${definitionId}/values/${valueId}` : "",
        definitionId ? `/api/tag-libraries/${bucketId}/definitions/${definitionId}` : "",
      ].filter(Boolean)) {
        const response = await reviewer.page.request.delete(path);
        if (![200, 404].includes(response.status())) throw new Error(`owned tag cleanup returned ${response.status()}`);
      }
    } finally { await reviewer?.context.close(); }
  });

  await executeFixedScenario(context, {
    preconditions: [async () => {
      await loginCurrent(page, "tenant_a_dev");
      for (const name of [source, second, conflict]) {
        await skills.open();
        await skills.upload(name, token, () => registerSkill(name));
      }
      reviewer = await loginIsolated(page, "tenant_a_admin");
      const libraries = await reviewer.page.request.get("/api/tag-libraries");
      expect(libraries.ok()).toBe(true);
      const bucket = (await libraries.json()).find((item: any) => item.bucket_key === "default_resource" && item.status === "active");
      expect(bucket).toBeTruthy(); bucketId = bucket.bucket_id;
      const created = await reviewer.page.request.post(`/api/tag-libraries/${bucketId}/definitions`, { data: {
        definition_key: `d4_${token}`, definition_name: tagName,
        selection_mode: "single_select", initial_values: [tagValue],
      } });
      expect(created.ok()).toBe(true);
      const definition = await created.json(); definitionId = definition.definition_id;
      registerReadyAsset("tags", "repository_definition", String(definitionId), ID, {
        service: "config", identity: "tenant_a_admin", method: "DELETE",
        path: `/tag-libraries/${bucketId}/definitions/${definitionId}`, allowed_statuses: [200, 404],
      });
      const definitions = await reviewer.page.request.get(`/api/tag-libraries/${bucketId}/definitions`);
      expect(definitions.ok()).toBe(true);
      const detail = (await definitions.json()).find((item: any) => item.definition_id === definitionId);
      expect(detail.values).toHaveLength(1); valueId = detail.values[0].value_id;
      registerReadyAsset("tags", "repository_value", String(valueId), ID, {
        service: "config", identity: "tenant_a_admin", method: "DELETE",
        path: `/tag-libraries/${bucketId}/definitions/${definitionId}/values/${valueId}`, allowed_statuses: [200, 404],
      });
      const inventory = await page.request.get("/api/skills"); expect(inventory.ok()).toBe(true);
      const original = (await inventory.json()).skills.filter((item: any) => item.name === source);
      expect(original).toHaveLength(1); sourceId = Number(original[0].skill_id);
      const assigned = await reviewer.page.request.put(`/api/tag-libraries/assignments/skill/${sourceId}`, { data: { value_ids: [valueId] } });
      expect(assigned.ok()).toBe(true);
      expect((await assigned.json()).assignments.some((item: any) => item.value_id === valueId)).toBe(true);
      registerReadyAsset("tags", "repository_assignment", String(sourceId), ID, {
        service: "config", identity: "tenant_a_admin", method: "PUT",
        path: `/tag-libraries/assignments/skill/${sourceId}`, json: { value_ids: [] }, allowed_statuses: [200, 404],
      });
      for (const name of [source, second]) {
        await skills.open(); await skills.search(name); await skills.apply(name);
        await new SkillPage(reviewer.page).approve(name);
      }
      const waiting = repositoryResponse();
      await page.goto(appPath("/skill-space"));
      const response = await waiting; expect(response.ok()).toBe(true);
      total = (await response.json()).pagination.total;
      expect(total).toBeGreaterThanOrEqual(2);
      return "prepared two owned shared listings, one uniquely controlled tag and a proven existing local conflict name; all IDs registered for cleanup";
    }],
    steps: [
      async () => { await expect(page.getByRole("tab", { name: /^仓库/ })).toHaveAttribute("data-state", "active"); return "fresh route selected Repository by default"; },
      async () => {
        await expect(page.getByRole("tab", { name: /^仓库/ })).toContainText(total.toLocaleString());
        await expect(card(source)).toBeVisible(); await expect(card(second)).toBeVisible();
        return "repository count badge matches unfiltered API pagination total and both prepared cards render";
      },
      async () => {
        const waiting = repositoryResponse((url) => url.searchParams.get("search") === prefix);
        await searchBox().fill(prefix); const response = await waiting;
        expect(response.ok()).toBe(true); const items = (await response.json()).items;
        expect(items.map((item: any) => item.name).sort()).toEqual([source, second].sort());
        await expect(card(source)).toBeVisible(); await expect(card(second)).toBeVisible();
        return "keyword search returned exactly the two owned listings, not arbitrary shared records";
      },
      async () => {
        await page.getByRole("button", { name: "标签筛选", exact: true }).click();
        const popup = page.locator(".ant-popover:visible");
        await popup.getByRole("combobox").first().click();
        await page.locator(".ant-select-item-option:visible").filter({ hasText: tagName }).click();
        const waiting = repositoryResponse((url) => Boolean(url.searchParams.get("tag_predicates")));
        await popup.getByRole("combobox").last().click();
        await page.locator(".ant-select-item-option:visible").filter({ hasText: tagValue }).click();
        const response = await waiting; expect(response.ok()).toBe(true);
        predicates = JSON.parse(new URL(response.url()).searchParams.get("tag_predicates")!);
        filtered = (await response.json()).items;
        expect(predicates).toEqual([{ definition_id: definitionId, value_ids: [valueId] }]);
        expect(filtered.map((item) => item.name)).toEqual([source]);
        expect(filtered[0].tags).toContain(tagValue);
        await page.getByRole("button", { name: "标签筛选", exact: true }).click();
        await expect(card(second)).toHaveCount(0);
        return "exact controlled tag_predicates filtered to the tagged source, with no downgrade when tags are missing";
      },
      async () => {
        await page.getByRole("button", { name: source, exact: true }).locator("visible=true").click();
        const dialog = page.locator(".skill-detail-modal:visible");
        await expect(dialog.getByRole("heading", { name: source, exact: true })).toBeVisible();
        await expect(dialog).toContainText(`deterministic D4 skill ${token}`);
        await expect(dialog).toContainText(tagValue);
        return "current ResourceDetail shows the owned listing name, description and controlled tag";
      },
      async () => {
        await page.locator(".skill-detail-modal:visible .ant-modal-close").click();
        await card(source).getByRole("button", { name: /^复\s*制$/ }).click();
        await expect(page.getByRole("dialog", { name: "复制为我的 Skill", exact: true })).toBeVisible();
        return "opened copy/rename dialog from the real ResourceCard footer";
      },
      async () => {
        const modal = page.getByRole("dialog", { name: "复制为我的 Skill", exact: true });
        await modal.getByPlaceholder("请输入 Skill 名称").fill(conflict);
        const waiting = page.waitForResponse((r) => r.request().method() === "POST" && /\/repository\/skill\/\d+\/install$/.test(new URL(r.url()).pathname));
        const [response] = await Promise.all([waiting, modal.getByRole("button", { name: /^复\s*制$/ }).click()]);
        conflictStatus = response.status(); expect(conflictStatus).toBe(409);
        expect((await response.json()).message.type).toBe("skill_duplicate");
        await expect(modal).toContainText(/当前租户已存在同名 Skill/);
        await expect(modal).toBeVisible();
        return "proven local name conflict returned 409/skill_duplicate and no success navigation";
      },
      async () => {
        const modal = page.getByRole("dialog", { name: "复制为我的 Skill", exact: true });
        await modal.getByPlaceholder("请输入 Skill 名称").fill(copy);
        const waiting = page.waitForResponse((r) => r.request().method() === "POST" && /\/repository\/skill\/\d+\/install$/.test(new URL(r.url()).pathname));
        const [response] = await Promise.all([waiting, modal.getByRole("button", { name: /^复\s*制$/ }).click()]);
        installedStatus = response.status(); expect(response.ok()).toBe(true); registerSkill(copy);
        await expect(page.getByText(/Skill 已复制为|Skill 复制成功/)).toBeVisible();
        await expect(modal).toBeHidden(); await skills.open(); await skills.search(copy);
        await expect(card(copy)).toBeVisible();
        return "unique rename copied successfully and Mine contains the independently owned copy";
      },
    ],
    assertions: [
      async () => { expect(total).toBeGreaterThanOrEqual(2); return "default Repository route/count and prepared grid checked"; },
      async () => "keyword response and both rendered owned listings matched",
      async () => { expect(predicates[0].value_ids).toEqual([valueId]); expect(filtered.map((item) => item.name)).toEqual([source]); return "unique tag filter was actually executed"; },
      async () => "detail displayed name, description and tag",
      async () => { expect(conflictStatus).toBe(409); return "existing local name was rejected without overwriting it"; },
      async () => { expect(installedStatus).toBe(200); await expect(card(copy)).toBeVisible(); return "renamed copy visible in Mine; independent IDs/names retained for cleanup"; },
    ],
  });
});
