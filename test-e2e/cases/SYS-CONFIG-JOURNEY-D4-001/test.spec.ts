// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";

const KEYS = [
  "MAX_TENANT_COUNT",
  "MAX_USERS_PER_TENANT",
  "MAX_GROUPS_PER_TENANT",
  "MAX_SUPER_ADMIN_COUNT",
  "MAX_ADMINS_PER_TENANT",
  "MAX_KNOWLEDGE_BASES_PER_TENANT",
  "MAX_KNOWLEDGE_BASES_PER_USER",
  "MAX_PRIVILEGED_KNOWLEDGE_BASES_PER_USER",
  "MAX_KNOWLEDGE_FILE_SIZE_MB",
  "MAX_CONVERSATION_TURNS",
  "MAX_CONVERSATIONS_PER_USER",
  "MAX_MCP_SERVICES_PER_TENANT",
  "MCP_REQUEST_TIMEOUT_SECONDS",
  "MAX_EVALUATION_SET_FILE_SIZE_MB",
  "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS",
  "RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS",
  "LLM_INCLUDE_LOGPROBS",
  "MAX_SKILLS_PER_TENANT",
  "MAX_SKILL_UPLOAD_SIZE_MB",
];

function item(key: string, value: number | boolean = 100) {
  const kind =
    key === "LLM_INCLUDE_LOGPROBS"
      ? "boolean"
      : key.includes("TIMEOUT")
        ? "number"
        : "integer";
  const group =
    key.includes("TIMEOUT") || key === "LLM_INCLUDE_LOGPROBS"
      ? "runtime"
      : key.includes("SIZE")
        ? "upload"
        : key.includes("KNOWLEDGE") ||
            key === "MAX_MCP_SERVICES_PER_TENANT" ||
            key === "MAX_SKILLS_PER_TENANT" ||
            key.includes("CONVERSATION")
          ? "capacity"
          : "tenant";
  const defaultValue =
    key === "LLM_INCLUDE_LOGPROBS"
      ? false
      : key === "MAX_TENANT_COUNT"
        ? 4
        : 100;
  const unitKey = key.includes("TIMEOUT")
    ? "systemConfig.unit.second"
    : key.includes("SIZE")
      ? "systemConfig.unit.mb"
      : null;
  return {
    key,
    value,
    default_value: defaultValue,
    kind,
    group,
    label_key: `systemConfig.param.${key}.label`,
    description_key: `systemConfig.param.${key}.desc`,
    unit_key: unitKey,
    effect_key: "systemConfig.effect.nextRun",
    recommendation_available: false,
  };
}

journey("SYS-CONFIG-JOURNEY-D4-001", async ({ page, contract }) => {
  const writes: Record<string, number | boolean>[] = [];
  const savedValues: Record<string, number | boolean> = Object.fromEntries(
    KEYS.map((key) => [key, key === "LLM_INCLUDE_LOGPROBS" ? false : 100]),
  );
  const leaveWarnings: string[] = [];
  let releaseSave: (() => void) | undefined;
  let releaseQuery: (() => void) | undefined;
  let holdSave = false;
  let delayQuery = false;
  let failSave = false;
  let authorized = true;
  let actorRole = "OPS";
  let deniedActorChecked = false;
  let notification: "published" | "degraded" = "published";
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: process.env.NEXENT_BASE_URL ?? "http://localhost:3000",
    },
  ]);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/user/current_user_info") {
      return route.fulfill({
        json: {
          data: {
            user: {
              user_id: authorized ? "ops-user" : "denied-user",
              tenant_id: "ops-tenant",
              user_email: authorized
                ? "ops@example.invalid"
                : "denied@example.invalid",
              user_role: authorized ? actorRole : "USER",
              roles: authorized ? [actorRole] : ["USER"],
              auth_provider: "local",
              groupIds: [],
              permissions: authorized
                ? ["ops.configuration:read", "ops.configuration:update"]
                : [],
              accessibleRoutes: authorized
                ? ["/ops/configuration"]
                : ["/newchat"],
            },
          },
        },
      });
    }
    if (pathname === "/api/system_configurations") {
      if (!authorized) {
        return route.fulfill({
          status: 403,
          json: { detail: { code: "FORBIDDEN", message: "Access denied" } },
        });
      }
      if (request.method() === "GET") {
        if (delayQuery) {
          delayQuery = false;
          await new Promise<void>((resolve) => {
            releaseQuery = resolve;
          });
        }
        return route.fulfill({
          json: {
            items: KEYS.map((key) => item(key, savedValues[key])),
            total: 19,
          },
        });
      }
      const changes = request.postDataJSON().changes as Record<
        string,
        number | boolean
      >;
      writes.push(changes);
      if (failSave) {
        failSave = false;
        return route.abort("failed");
      }
      if (holdSave) {
        holdSave = false;
        await new Promise<void>((resolve) => {
          releaseSave = resolve;
        });
      }
      Object.assign(savedValues, changes);
      return route.fulfill({
        json: {
          saved: true,
          notification,
          items: Object.keys(changes).map((key) => item(key, savedValues[key])),
        },
      });
    }
    if (pathname === "/api/tenant_config/deployment_version") {
      return route.fulfill({
        json: {
          deployment_version: "full",
          app_version: "test",
          status: "success",
        },
      });
    }
    if (pathname === "/api/groups/list") {
      return route.fulfill({ json: { data: [], total: 0, message: "ok" } });
    }
    if (pathname === "/api/notifications") {
      return route.fulfill({
        json: {
          message: "OK",
          data: { items: [], pagination: { total: 0 } },
        },
      });
    }
    if (pathname.endsWith("/quota/usage")) {
      return route.fulfill({ json: { warning_enabled: false } });
    }
    return route.fulfill({ json: { data: {} } });
  });

  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto("/zh/ops/configuration");
      await expect(
        page.getByRole("heading", { name: "系统配置", exact: true }),
      ).toBeVisible();
      await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(
        19,
      );
    },
  );

  await contract.step(contract.expectedIds("steps")[0], async () => {
    await page.goto("/zh/users");
    await expect(page).toHaveURL(/\/zh\/users$/);
    await expect(
      page.getByRole("heading", { name: "个人信息", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("无权限访问", { exact: true })).toHaveCount(0);

    await page.goto("/zh/ops/configuration");
    await expect(
      page.getByRole("heading", { name: "系统配置", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("推荐", { exact: true })).toHaveCount(0);
    await expect(page.getByText("应用详情", { exact: true })).toHaveCount(0);
    await expect(page.getByText("当前版本", { exact: true })).toHaveCount(0);
    await page
      .getByPlaceholder("搜索参数名称或环境变量键")
      .fill("MAX_TENANT_COUNT");
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(1);
    await page.getByPlaceholder("搜索参数名称或环境变量键").fill("");
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(19);
    await page.getByText("文件与上传 3", { exact: true }).click();
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(3);
    await page.getByText("全部 19", { exact: true }).click();
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(19);

    await page.goto("/en/ops/configuration");
    await expect(
      page.getByRole("heading", { name: "System Configuration", exact: true }),
    ).toBeVisible();
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(19);
    await page
      .getByPlaceholder("Search by setting name or environment key")
      .fill("Tenant limit");
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(1);
    await expect(page.getByText("Tenant limit", { exact: true })).toBeVisible();

    authorized = false;
    await page.goto("/zh/ops/configuration");
    await expect(page.getByText("无权限访问", { exact: true })).toBeVisible();
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "系统配置", exact: true }),
    ).toHaveCount(0);
    const deniedResponse = await page.evaluate(async () => {
      const response = await fetch("/api/system_configurations");
      return { status: response.status, body: await response.text() };
    });
    expect(deniedResponse.status).toBe(403);
    expect(deniedResponse.body).not.toContain("MAX_TENANT_COUNT");
    deniedActorChecked = true;

    authorized = true;
    await page.goto("/zh/ops/configuration");
    await expect(
      page.getByRole("heading", { name: "系统配置", exact: true }),
    ).toBeVisible();
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(19);
  });

  await contract.step(contract.expectedIds("steps")[1], async () => {
    const input = page.getByRole("spinbutton", {
      name: "租户数量上限",
      exact: true,
    });
    const otherInput = page.getByRole("spinbutton", {
      name: "单租户用户上限",
      exact: true,
    });
    await otherInput.fill("123");
    const filterBox = await page.getByTestId("config-filter").boundingBox();
    const saveBarBox = await page
      .getByRole("button", { name: "保存修改", exact: true })
      .locator("xpath=../..")
      .boundingBox();
    expect(filterBox).not.toBeNull();
    expect(saveBarBox).not.toBeNull();
    if (!filterBox || !saveBarBox)
      throw new Error("Save bar alignment requires visible layout boxes");
    expect({
      left: saveBarBox.x,
      right: saveBarBox.x + saveBarBox.width,
    }).toEqual({
      left: filterBox.x,
      right: filterBox.x + filterBox.width,
    });
    await page.getByRole("button", { name: "放弃", exact: true }).click();
    await expect(otherInput).toHaveValue("100");
    await expect(
      page.getByRole("button", { name: "保存修改", exact: true }),
    ).toHaveCount(0);

    await page
      .getByTestId("config-row-MAX_TENANT_COUNT")
      .getByRole("button", {
        name: "展开租户数量上限详情",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", {
        name: "将租户数量上限恢复为默认值",
        exact: true,
      })
      .click();
    await expect(input).toHaveValue("4");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page.getByRole("button", { name: "确认保存", exact: true }).click();
    await expect(
      page.getByText("已保存 1 项参数，消费者将自动刷新", { exact: true }),
    ).toBeVisible();
    expect(writes[0]).toEqual({ MAX_TENANT_COUNT: 4 });
    await expect(input).toHaveValue("4");

    notification = "degraded";
    holdSave = true;
    await input.fill("5");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page.getByRole("button", { name: "确认保存", exact: true }).click();
    await input.fill("7");
    await expect.poll(() => Boolean(releaseSave)).toBe(true);
    releaseSave?.();
    await expect(input).toHaveValue("7");
    expect(writes[1]).toEqual({ MAX_TENANT_COUNT: 5 });
    await expect(
      page.getByText(
        "已保存，消费者将自动刷新；当前 Redis 通知不可用，将依赖定时刷新。",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.getByTestId("config-row-MAX_TENANT_COUNT")).toContainText(
      "原值 5",
    );
  });

  await contract.step(contract.expectedIds("steps")[2], async () => {
    failSave = true;
    const input = page.getByRole("spinbutton", {
      name: "租户数量上限",
      exact: true,
    });
    await input.fill("9");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page.getByRole("button", { name: "确认保存", exact: true }).click();
    await expect(input).toHaveValue("9");
    await expect(
      page.getByText("Server connection error, please try again later", {
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "取消", exact: true }).click();
    await page
      .getByPlaceholder("搜索参数名称或环境变量键")
      .fill("MAX_TENANT_COUNT");
    await expect(input).toHaveValue("9");
    await page.getByPlaceholder("搜索参数名称或环境变量键").fill("");

    savedValues.MAX_TENANT_COUNT = 50;
    delayQuery = true;
    await page.getByRole("button", { name: "刷新状态", exact: true }).click();
    await expect.poll(() => Boolean(releaseQuery)).toBe(true);
    await input.fill("10");
    releaseQuery?.();
    await expect(input).toHaveValue("10");
    await expect(page.getByTestId("config-row-MAX_TENANT_COUNT")).toContainText(
      "原值 50",
    );

    await page.evaluate(() => {
      const testWindow = window as Window & {
        __systemConfigLeaveWarnings?: string[];
      };
      testWindow.__systemConfigLeaveWarnings = [];
      testWindow.confirm = (message) => {
        testWindow.__systemConfigLeaveWarnings?.push(String(message));
        return false;
      };
    });
    await page
      .locator('a[href="/"]')
      .first()
      .evaluate((anchor: HTMLAnchorElement) => anchor.click());
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (
              window as Window & {
                __systemConfigLeaveWarnings?: string[];
              }
            ).__systemConfigLeaveWarnings?.length,
        ),
      )
      .toBe(1);
    await expect(page).toHaveURL(/\/zh\/ops\/configuration$/);
    await expect(input).toHaveValue("10");
    await page.goBack();
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (
              window as Window & {
                __systemConfigLeaveWarnings?: string[];
              }
            ).__systemConfigLeaveWarnings?.length,
        ),
      )
      .toBe(2);
    leaveWarnings.push(
      ...(await page.evaluate(
        () =>
          (
            window as Window & {
              __systemConfigLeaveWarnings?: string[];
            }
          ).__systemConfigLeaveWarnings ?? [],
      )),
    );
    expect(leaveWarnings[0]).toBe("存在未保存的修改，确定离开当前页面吗？");
    await expect(page).toHaveURL(/\/zh\/ops\/configuration$/);
    await expect(input).toHaveValue("10");
  });

  const assertionIds = contract.expectedIds("assertions");
  await contract.assertion(assertionIds[0], async () => {
    expect(deniedActorChecked).toBe(true);
    await expect(page.locator("[data-testid^='config-row-']")).toHaveCount(19);
    await expect(page.getByText("推荐", { exact: true })).toHaveCount(0);
    await expect(page.getByText("应用详情", { exact: true })).toHaveCount(0);
  });
  await contract.assertion(assertionIds[1], async () => {
    expect(writes[0]).toEqual({ MAX_TENANT_COUNT: 4 });
    expect(writes[1]).toEqual({ MAX_TENANT_COUNT: 5 });
    expect(writes[2]).toEqual({ MAX_TENANT_COUNT: 9 });
    expect(
      writes.every((change) =>
        Object.keys(change).every((key) => KEYS.includes(key)),
      ),
    ).toBe(true);
  });
  await contract.assertion(assertionIds[2], async () => {
    await expect(
      page.getByRole("spinbutton", { name: "租户数量上限", exact: true }),
    ).toHaveValue("10");
    expect(leaveWarnings).toEqual([
      "存在未保存的修改，确定离开当前页面吗？",
      "存在未保存的修改，确定离开当前页面吗？",
    ]);
    await expect(page.getByText("全部已生效", { exact: true })).toHaveCount(0);
  });
});
