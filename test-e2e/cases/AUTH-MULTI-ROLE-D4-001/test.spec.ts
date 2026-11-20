// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect, type BrowserContext, type Page } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";

/** Uses the current-source isolated identity fixture; never shared tenant accounts. */
journey("AUTH-MULTI-ROLE-D4-001", async ({ page, contract }) => {
  const browser = page.context().browser()!;
  const request = page.request;
  const baseURL = process.env.NEXENT_BASE_URL;
  const config = process.env.NEXENT_CONFIG_URL;
  if (!config || !baseURL)
    throw new Error("Isolated identity fixture and frontend URLs are required");
  const fixtureResponse = await request.get(`${config}/__fixture`);
  expect(fixtureResponse.ok()).toBeTruthy();
  const fixture = await fixtureResponse.json();
  const contexts: BrowserContext[] = [];
  async function login(actor: string) {
    const context =
      actor === "admin1" ? page.context() : await browser.newContext();
    if (actor !== "admin1") contexts.push(context);
    const response = await context.request.post(`${baseURL}/api/user/signin`, {
      data: {
        email: fixture.emails[actor],
        password: fixture.password,
      },
    });
    expect(response.status()).toBe(200);
    return {
      context,
      page: actor === "admin1" ? page : await context.newPage(),
    };
  }
  async function chooseRole(page: Page, role: RegExp) {
    const dropdown = page.locator(".ant-select-dropdown:visible");
    await expect(dropdown).toHaveCount(1);
    await dropdown
      .locator(".ant-select-item-option-content")
      .filter({ hasText: role })
      .click();
  }
  const admin = await login("admin1");
  let invitationCode: string | undefined;
  let invitationRoles: string[] = [];
  let filteredIds: string[] = [];
  let opsEntries: string[] = [];
  let selectedTenant: string | null = null;
  let deniedStatus = 0;
  contract.deferCleanup(async () => {
    try {
      expect(
        (
          await admin.context.request.put(
            `${baseURL}/api/users/${fixture.users.admin1}`,
            {
              data: { roles: ["ADMIN"] },
            },
          )
        ).status(),
      ).toBe(200);
      expect(
        (
          await admin.context.request.put(
            `${baseURL}/api/users/${fixture.users.user}`,
            { data: { roles: ["USER"] } },
          )
        ).status(),
      ).toBe(200);
      if (invitationCode)
        expect(
          (
            await admin.context.request.delete(
              `${baseURL}/api/invitations/${invitationCode}`,
            )
          ).status(),
        ).toBe(200);
    } finally {
      for (const context of contexts) await context.close();
    }
  });
  const preconditions = contract.expectedIds("preconditions");
  await contract.precondition(preconditions[0], async () => {
    expect(fixtureResponse.status()).toBe(200);
  });
  await contract.precondition(preconditions[1], async () => {
    for (const id of ["su", "admin1", "admin2", "user", "foreign", "ops"])
      expect(fixture.users[id]).toBeTruthy();
  });
  await contract.precondition(preconditions[2], async () => {
    expect(fixture.owned_database).toMatch(/^auth_test_[a-f0-9]{32}$/);
  });
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    await admin.page.goto(`${baseURL}/en/resource-manage`);
    const row = admin.page
      .getByRole("row")
      .filter({ hasText: fixture.emails.user });
    await expect(row).toHaveCount(1);
    await row.getByRole("button", { name: "Edit User", exact: true }).click();
    let modal = admin.page.getByRole("dialog");
    await expect(modal).toBeVisible();
    await modal.locator(".ant-select-selection-item-remove").first().click();
    const roles = modal.locator("#roles");
    await roles.click();
    await chooseRole(admin.page, /^Developer$/);
    await roles.click();
    await chooseRole(admin.page, /^Operations$/);
    await admin.page.keyboard.press("Escape");
    await modal.getByRole("button", { name: "Confirm", exact: true }).click();
    await expect(row.getByText("Developer", { exact: true })).toBeVisible();
    await expect(row.getByText("Operations", { exact: true })).toBeVisible();
    await row.getByRole("button", { name: "Edit User", exact: true }).click();
    modal = admin.page.getByRole("dialog");
    await expect(modal.locator(".ant-select-selection-item")).toHaveCount(2);
    await modal.getByRole("button", { name: "Cancel", exact: true }).click();
    const filtered = admin.page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/users/list") &&
        response.request().postDataJSON()?.roles?.includes("OPS"),
    );
    await admin.page.getByRole("combobox").first().click();
    await chooseRole(admin.page, /^Operations$/);
    filteredIds = (await (await filtered).json()).data.map(
      (record: { id: string }) => record.id,
    );
    expect(new Set(filteredIds).size).toBe(2);
    await expect(row).toHaveCount(1);
    await admin.page.keyboard.press("Escape");
  });
  await contract.step(steps[1], async () => {
    let modal;
    await admin.page
      .getByRole("tab", { name: "Invitations", exact: true })
      .click();
    await admin.page
      .getByRole("button", { name: "Create Invitation", exact: true })
      .click();
    modal = admin.page.getByRole("dialog");
    await modal.locator(".ant-select-selection-item-remove").first().click();
    await modal.locator("#roles").click();
    await chooseRole(admin.page, /^Admin$/);
    await modal.locator("#roles").click();
    await chooseRole(admin.page, /^Operations$/);
    await admin.page.keyboard.press("Escape");
    const savedInvitation = admin.page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/invitations") &&
        response.request().method() === "POST",
    );
    await modal.getByRole("button", { name: "Confirm", exact: true }).click();
    const invitation = await savedInvitation;
    expect(invitation.status()).toBe(201);
    const invitationData = (await invitation.json()).data;
    invitationCode = invitationData.invitation_code;
    invitationRoles = invitationData.roles;
    const invitationRow = admin.page
      .getByRole("row")
      .filter({ hasText: invitationCode });
    await expect(
      invitationRow.getByText("Admin", { exact: true }),
    ).toBeVisible();
    await expect(
      invitationRow.getByText("Operations", { exact: true }),
    ).toBeVisible();
    await invitationRow
      .getByRole("button", { name: "Edit", exact: true })
      .click();
    await expect(admin.page.getByRole("dialog").locator("#roles")).toHaveCount(
      0,
    );
    await admin.page
      .getByRole("dialog")
      .getByRole("button", { name: "Cancel", exact: true })
      .click();

    const ops = await login("ops");
    await ops.page.goto(`${baseURL}/en/ops/dashboard`);
    await expect(
      ops.page.getByRole("heading", { name: "Operations dashboard" }),
    ).toBeVisible();
    await expect(
      ops.page.getByRole("navigation").getByRole("button"),
    ).toHaveCount(3);
    opsEntries = await ops.page
      .getByRole("navigation")
      .getByRole("button")
      .evaluateAll((buttons) =>
        buttons.map((button) => button.getAttribute("aria-label") || ""),
      );
    await expect(
      ops.page.getByRole("button", {
        name: "System configuration",
        exact: true,
      }),
    ).toBeVisible();
    await ops.page.goto(`${baseURL}/en/resource-manage`);
    await expect(
      ops.page.getByText("Read-only mode", { exact: true }),
    ).toBeVisible();
    await expect(
      ops.page.getByRole("tab", { name: "Users", exact: true }),
    ).toBeVisible();
    const search = ops.page.getByPlaceholder("Search email");
    await search.fill(fixture.emails.user);
    await expect(ops.page.getByRole("row").filter({ hasText: fixture.emails.user })).toBeVisible();
    await expect(ops.page.getByRole("row").filter({ hasText: fixture.emails.admin1 })).toHaveCount(0);
    await ops.page.getByRole("tab", { name: "Models", exact: true }).click();
    await expect(ops.page.getByText("Owned model", { exact: true })).toBeVisible();
    await expect(
      ops.page.getByRole("button", { name: /Edit|Delete|Create/ }),
    ).toHaveCount(0);
  });
  await contract.step(steps[2], async () => {
    const combined = await login("user");
    await combined.page.goto(`${baseURL}/en/ops/dashboard`);
    await expect(
      combined.page.getByRole("heading", { name: "Operations dashboard" }),
    ).toBeVisible();
    await expect(
      combined.page.getByRole("button", {
        name: "Agent Configuration",
        exact: true,
      }),
    ).toBeVisible();
    const su = await login("su");
    await su.page.goto(`${baseURL}/en/ops/configuration`);
    await expect(su.page.getByLabel("Tenant", { exact: true })).toBeVisible();
    await expect(
      su.page.getByText("All tenants", { exact: true }).first(),
    ).toBeVisible();
    await su.page.getByLabel("Tenant", { exact: true }).click();
    const selectedScope = su.page.waitForResponse(
      (response) =>
        response.url().includes("/ops/scope") &&
        response.url().includes("tenant_id=b"),
    );
    await su.page
      .locator(
        '.ant-select-dropdown:visible .ant-select-item-option[title="b"]',
      )
      .click();
    const scopedResponse = await selectedScope;
    expect(scopedResponse.status()).toBe(200);
    selectedTenant = (await scopedResponse.json()).data.tenant_id;
    await su.page.setViewportSize({ width: 1600, height: 900 });
    await su.page.goto(`${baseURL}/en/resource-manage`);
    await su.page.getByText("Owned b", { exact: true }).click();
    const apiKeyTab = su.page.getByRole("tab", { name: /^API Keys?$/ });
    await expect(
      su.page.getByRole("tablist").getByRole("tab").last(),
    ).toHaveAccessibleName(/^API Keys?$/);
    await apiKeyTab.click();
    const apiKeyPanel = su.page.getByRole("tabpanel", { name: /^API Keys?$/ });
    await expect(
      apiKeyPanel.getByRole("row").filter({ hasText: fixture.emails.foreign }),
    ).toBeVisible();
    await expect(
      apiKeyPanel.getByText("fixture-only-api-key", { exact: true }),
    ).toHaveCount(0);
    await expect(
      apiKeyPanel.getByRole("columnheader", { name: "Actions" }),
    ).toHaveCount(0);
    const revoked = await admin.context.request.put(
      `${baseURL}/api/users/${fixture.users.user}`,
      { data: { roles: ["DEV"] } },
    );
    expect(revoked.status()).toBe(200);
    await combined.page.reload();
    await expect(
      combined.page.getByRole("heading", { name: "Operations dashboard" }),
    ).toHaveCount(0);
    const denied = await combined.context.request.get(
      `${baseURL}/api/ops/authorization`,
    );
    deniedStatus = denied.status();
    expect(deniedStatus).toBe(403);

    await admin.page.goto(`${baseURL}/en/resource-manage`);
    await expect(
      admin.page.getByRole("navigation").getByRole("button", {
        name: "Operations dashboard",
        exact: true,
      }),
    ).toHaveCount(0);
    const selfRow = admin.page
      .getByRole("row")
      .filter({ hasText: fixture.emails.admin1 });
    await selfRow
      .getByRole("button", { name: "Edit User", exact: true })
      .click();
    const selfDialog = admin.page.getByRole("dialog");
    await selfDialog.locator("#roles").click();
    await chooseRole(admin.page, /^Operations$/);
    await admin.page.keyboard.press("Escape");
    await selfDialog
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await expect(
      admin.page.getByRole("navigation").getByRole("button", {
        name: "Operations dashboard",
        exact: true,
      }),
    ).toBeVisible();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    expect(filteredIds.sort()).toEqual(
      [fixture.users.ops, fixture.users.user].sort(),
    );
  });
  await contract.assertion(assertions[1], async () => {
    expect(invitationRoles).toEqual(["ADMIN", "OPS"]);
    expect(opsEntries.sort()).toEqual(
      [
        "Operations dashboard",
        "Resource Management",
        "System configuration",
      ].sort(),
    );
  });
  await contract.assertion(assertions[2], async () => {
    expect(selectedTenant).toBe("b");
    expect(deniedStatus).toBe(403);
  });
});
