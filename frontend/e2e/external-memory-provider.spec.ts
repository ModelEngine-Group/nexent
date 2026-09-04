import { expect, test, type Page, type Route } from "@playwright/test";

type Provider = {
  provider_config_id: number;
  tenant_id: string;
  provider_name: string;
  connection_type: "plugin";
  enabled: boolean;
  timeout_seconds: number;
  last_error_code: string | null;
  params: Record<string, string>;
  create_time: string;
  update_time: string;
};

const plugin = {
  name: "mem0",
  version: "1.2.0",
  description: "Mem0 provider",
  implements: ["searchable", "ingestible"],
  config_schema: [
    { key: "api_key", label: "API key", type: "secret", required: true },
    {
      key: "endpoint",
      label: "Endpoint",
      type: "string",
      required: true,
      default: "https://memory.test",
    },
  ],
};

const makeProvider = (
  id: number,
  name: string,
  enabled: boolean,
  error: string | null = null
): Provider => ({
  provider_config_id: id,
  tenant_id: "tenant-test",
  provider_name: name,
  connection_type: "plugin",
  enabled,
  timeout_seconds: 30,
  last_error_code: error,
  params: {
    "plugin.name": "mem0",
    "plugin.api_key": "••••••••",
    "plugin.endpoint": "https://memory.test",
  },
  create_time: "2026-08-28T00:00:00Z",
  update_time: "2026-08-28T00:00:00Z",
});

async function baseRoutes(
  page: Page,
  permissions = [
    "MEM.PROVIDER:CREATE",
    "MEM.PROVIDER:READ",
    "MEM.PROVIDER:UPDATE",
    "MEM.PROVIDER:DELETE",
  ]
) {
  await page.route("**/api/**", async (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
  );
  await page.route("**/api/tenant_config/deployment_version", (route) =>
    json(route, {
      deployment_version: "speed",
      app_version: "test",
      status: "success",
    })
  );
  await page.route("**/api/user/current_user_info", (route) =>
    json(route, {
      data: {
        user: {
          user_id: "speed-user",
          group_ids: [],
          tenant_id: "tenant-test",
          user_email: "speed@nexent.test",
          user_role: "SPEED",
          auth_provider: "local",
          permissions,
          accessibleRoutes: ["/memory"],
        },
      },
    })
  );
  await page.route("**/api/groups/list", (route) =>
    json(route, { data: [], total: 0 })
  );
  await page.route("**/api/memory/config/load", (route) =>
    json(route, {
      MEMORY_SWITCH: "N",
      DREAMING_SWITCH: "N",
      EXTERNAL_PROVIDER_TOP_K: "20",
    })
  );
  await page.route("**/api/memory/config/embedding-status", (route) =>
    json(route, { configured: true, current_es_index_name: "test-index" })
  );
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function gotoMemory(page: Page, locale = "en") {
  await page.goto(`http://127.0.0.1:3000/${locale}/memory`);
  await expect(
    page.getByText(locale === "en" ? "External memory" : "外部记忆", {
      exact: true,
    })
  ).toBeVisible();
}

test("AC-P3-27/28/33/34 statuses, card grid, responsive layout, and advanced settings", async ({
  page,
}) => {
  await baseRoutes(page);
  let savedTopK: Record<string, unknown> | null = null;
  const providers = [
    makeProvider(1, "Healthy", true),
    makeProvider(2, "Auth failed", false, "unauthorized"),
    makeProvider(3, "Forbidden provider", false, "forbidden"),
    makeProvider(4, "Slow provider", true, "timeout"),
    makeProvider(5, "Broken provider", true, "unexpected"),
    makeProvider(6, "Paused provider", false),
  ];
  await page.route("**/api/memory/providers", (route) =>
    json(route, { items: providers, count: providers.length })
  );
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [plugin], count: 1 })
  );
  await page.route("**/api/memory/config/set", (route) => {
    savedTopK = route.request().postDataJSON();
    return json(route, { success: true });
  });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await gotoMemory(page);
  const providerGrid = page.locator(".external-provider-list");
  await expect(providerGrid).toHaveCSS(
    "grid-template-columns",
    /^(\d+(\.\d+)?px ){3}\d+(\.\d+)?px$/
  );
  const firstProviderCard = page.locator(".external-provider-row").first();
  await expect(firstProviderCard).toHaveCSS("min-height", "0px");
  await expect(firstProviderCard).toHaveCSS("padding", "12px");
  await page.setViewportSize({ width: 1200, height: 1000 });
  await expect(providerGrid).toHaveCSS(
    "grid-template-columns",
    /^\d+(\.\d+)?px \d+(\.\d+)?px$/
  );
  await page.setViewportSize({ width: 900, height: 1000 });
  await expect(providerGrid).toHaveCSS(
    "grid-template-columns",
    /^\d+(\.\d+)?px$/
  );
  await expect(page.getByLabel("Maximum results per provider")).toBeHidden();
  await expect(page.locator(".external-memory-advanced")).toHaveCount(0);
  const advancedButton = page.getByRole("button", {
    name: "Advanced settings",
  });
  const addProviderButton = page
    .getByRole("button", { name: "Add provider" })
    .first();
  const [advancedBox, addBox] = await Promise.all([
    advancedButton.boundingBox(),
    addProviderButton.boundingBox(),
  ]);
  expect(advancedBox?.x).toBeLessThan(addBox?.x ?? 0);
  await advancedButton.click();
  const topKInput = page.getByLabel("Maximum results per provider");
  await expect(topKInput).toBeVisible();
  await topKInput.fill("24");
  await topKInput.blur();
  await expect
    .poll(() => savedTopK)
    .toEqual({
      key: "EXTERNAL_PROVIDER_TOP_K",
      value: 24,
    });
  await expect(
    page.getByText("Memory is turned off.", { exact: false })
  ).toBeVisible();
  for (const status of [
    "Normal",
    "Unauthorized",
    "Forbidden",
    "Timeout",
    "Error",
    "Disabled",
  ]) {
    await expect(page.getByText(status, { exact: true })).toBeVisible();
  }
  await page.getByText("Needs attention", { exact: true }).click();
  await expect(page.getByText("Auth failed", { exact: true })).toBeVisible();
  await expect(page.getByText("Paused provider", { exact: true })).toBeHidden();
  await page.getByText("All", { exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  const siderToggle = page.locator(".ant-layout-sider button.ant-btn");
  if (await siderToggle.isVisible()) await siderToggle.click();
  await expect(page.getByText("Healthy", { exact: true })).toBeVisible();
  await expect(providerGrid).toHaveCSS(
    "grid-template-columns",
    /^\d+(\.\d+)?px$/
  );
});

test("AC-P3-29 drawer create, edit, secret preservation, and save-and-test", async ({
  page,
}) => {
  await baseRoutes(page);
  let providers: Provider[] = [];
  let createdBody: Record<string, unknown> | null = null;
  let updatedBody: Record<string, unknown> | null = null;
  let updatedParams: Record<string, string> = {};
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [plugin], count: 1 })
  );
  await page.route("**/api/memory/providers", async (route) => {
    if (route.request().method() === "POST") {
      createdBody = route.request().postDataJSON();
      const created = makeProvider(
        11,
        String(createdBody?.provider_name),
        Boolean(createdBody?.enabled)
      );
      created.params = createdBody?.params as Record<string, string>;
      providers = [created];
      return json(route, created);
    }
    return json(route, { items: providers, count: providers.length });
  });
  await page.route("**/api/memory/providers/11", async (route) => {
    if (route.request().method() === "PUT") {
      const payload = route.request().postDataJSON() as Record<string, unknown>;
      updatedBody = payload;
      updatedParams =
        (payload.params as Record<string, string> | undefined) ?? {};
      providers[0] = { ...providers[0], ...payload } as Provider;
      return json(route, providers[0]);
    }
    return json(route, providers[0]);
  });
  await gotoMemory(page);
  await page.getByRole("button", { name: "Add provider" }).first().click();
  await expect(page.getByText("Provider", { exact: true })).toBeVisible();
  await expect(page.getByText("Connection", { exact: true })).toBeVisible();
  await expect(page.getByText("Activation", { exact: true })).toBeVisible();
  await page.getByLabel("Provider name").fill("Primary Mem0");
  await page.getByLabel("Plugin").click();
  await page.getByText("mem0 (v1.2.0)").click();
  await page.getByLabel("API key").fill("secret-value");
  await page.getByLabel("Enable after saving").click();
  await page.getByRole("button", { name: "Save and test" }).click();
  await expect(
    page.getByText("Test Primary Mem0", { exact: true })
  ).toBeVisible();
  expect(createdBody).toMatchObject({
    provider_name: "Primary Mem0",
    enabled: true,
    params: {
      "plugin.name": "mem0",
      "plugin.api_key": "secret-value",
      "plugin.endpoint": "https://memory.test",
    },
  });
  await page.locator("button").filter({ hasText: "Close" }).click();
  await expect(
    page.getByText("Test Primary Mem0", { exact: true })
  ).toBeHidden();
  const row = page
    .locator(".external-provider-row")
    .filter({ hasText: "Primary Mem0" });
  await row.getByRole("button", { name: "More provider actions" }).click();
  await page.getByText("Edit", { exact: true }).click();
  await expect(page.getByLabel("Plugin")).toBeDisabled();
  await expect(page.getByLabel("API key")).toHaveValue("••••••••");
  await page.getByLabel("Provider name").fill("Primary Mem0 Updated");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(
    page.getByText("Primary Mem0 Updated", { exact: true })
  ).toBeVisible();
  expect(updatedBody).toMatchObject({ provider_name: "Primary Mem0 Updated" });
  expect(updatedParams["plugin.api_key"]).toBeUndefined();
});

test("AC-P3-30/35 sequential ingest-search workflow, samples, result, and sanitized error", async ({
  page,
}) => {
  await baseRoutes(page);
  const provider = makeProvider(1, "Mem0 Production", true);
  await page.route("**/api/memory/providers", (route) =>
    json(route, { items: [provider], count: 1 })
  );
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [plugin], count: 1 })
  );
  let searchAttempts = 0;
  const requestOrder: string[] = [];
  await page.route("**/api/memory/providers/1/test-search", async (route) => {
    requestOrder.push("search");
    searchAttempts += 1;
    if (searchAttempts === 2)
      return json(route, { detail: "secret upstream body" }, 500);
    expect(route.request().postDataJSON()).toEqual({
      query: "blue dashboard",
      top_k: 3,
    });
    return json(route, { count: 2 });
  });
  await page.route("**/api/memory/providers/1/test-ingest", async (route) => {
    requestOrder.push("ingest");
    const body = route.request().postDataJSON();
    expect(body.units[0].unit_type).toBe("user_message");
    return json(route, { accepted: 1, rejected: 0 });
  });
  await gotoMemory(page);
  await page.getByRole("button", { name: "More provider actions" }).click();
  await page.getByText("Test connection", { exact: true }).click();
  const testDrawer = page.locator(".ant-drawer-content").filter({
    hasText: "Test Mem0 Production",
  });
  await expect(testDrawer.getByRole("tab")).toHaveCount(0);
  await expect(page.getByLabel("Test memory content")).toHaveValue(
    "My preferred dashboard color is ocean blue."
  );
  await expect(page.getByLabel("Test query")).toHaveValue(
    "What color do I prefer for dashboards?"
  );
  await page.getByLabel("Test memory content").fill("temporary test memory");
  await page.getByLabel("Test query").fill("blue dashboard");
  await page.getByRole("button", { name: "Write and search" }).click();
  await expect(page.locator(".ant-modal-confirm-title")).toHaveText(
    "Write test memory?"
  );
  await page
    .locator(".ant-modal-confirm")
    .getByRole("button", { name: "Write and search" })
    .click();
  await expect(page.getByText("Connection test succeeded")).toBeVisible();
  await expect(page.getByText("Accepted")).toBeVisible();
  await expect(page.getByText("Rejected")).toBeVisible();
  await expect(page.getByText("Hits")).toBeVisible();
  expect(requestOrder).toEqual(["ingest", "search"]);
  await expect(page.locator(".ant-modal-confirm")).toBeHidden();
  await page.getByLabel("Test query").fill("will fail");
  await page
    .getByLabel("Test Mem0 Production")
    .getByRole("button", { name: "Write and search" })
    .click();
  await page
    .locator(".ant-modal-confirm")
    .getByRole("button", { name: "Write and search" })
    .click();
  await expect(page.getByText("Connection test failed")).toBeVisible();
  await expect(page.getByText("The provider request failed.")).toBeVisible();
  await expect(page.getByText("secret upstream body")).toBeHidden();
  expect(requestOrder).toEqual(["ingest", "search", "ingest", "search"]);
});

test("AC-P3-31 loading, empty, no-plugin, and inline retry states", async ({
  page,
}) => {
  await baseRoutes(page);
  let releaseProviders: (() => void) | undefined;
  let failProviders = false;
  const gate = new Promise<void>((resolve) => {
    releaseProviders = resolve;
  });
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [plugin], count: 1 })
  );
  await page.route("**/api/memory/providers", async (route) => {
    await gate;
    if (failProviders) return json(route, { detail: "failed" }, 500);
    return json(route, { items: [], count: 0 });
  });
  const navigation = page.goto("http://127.0.0.1:3000/en/memory");
  await expect(
    page.locator(".external-memory-card .ant-skeleton")
  ).toBeVisible();
  releaseProviders?.();
  await navigation;
  await expect(
    page.getByText("No external memory providers are configured.")
  ).toBeVisible();

  await page.unroute("**/api/memory/provider-plugins");
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [], count: 0 })
  );
  await page.reload();
  await expect(
    page.getByText("No plugins are installed.", { exact: false })
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Add provider" })
  ).toBeDisabled();

  failProviders = true;
  await page.unroute("**/api/memory/provider-plugins");
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [plugin], count: 1 })
  );
  await page.reload();
  await expect(
    page.getByText("External memory providers failed to load.")
  ).toBeVisible();
  failProviders = false;
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(
    page.getByText("No external memory providers are configured.")
  ).toBeVisible();
});

test("AC-P3-32 Chinese locale and read-only permissions", async ({ page }) => {
  await baseRoutes(page, ["MEM.PROVIDER:READ"]);
  const provider = makeProvider(1, "只读 Mem0", true);
  await page.route("**/api/memory/providers", (route) =>
    json(route, { items: [provider], count: 1 })
  );
  await page.route("**/api/memory/provider-plugins", (route) =>
    json(route, { items: [plugin], count: 1 })
  );
  await gotoMemory(page, "zh");
  const advancedButton = page.getByRole("button", { name: "高级设置" });
  await expect(advancedButton).toBeVisible();
  await advancedButton.click();
  await expect(page.getByText("每个 Provider 的最大结果数")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "添加 Provider" })
  ).toBeHidden();
  await expect(page.getByLabel("启用 Provider")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "更多 Provider 操作" })
  ).toBeHidden();
});
