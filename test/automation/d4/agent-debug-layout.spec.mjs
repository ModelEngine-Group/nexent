// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  makeDraft,
  fulfillEditorReadFixture,
} from "./fixtures/agent-editor-fixtures.mjs";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  expect,
  test,
} from "../../../frontend/node_modules/@playwright/test/index.mjs";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../",
);
const baseUrl = process.env.NEXENT_E2E_BASE_URL ?? "http://127.0.0.1:3000";
const messages = JSON.parse(
  fs
    .readFileSync(
      path.join(repositoryRoot, "frontend/public/locales/zh/common.json"),
      "utf8",
    )
    .replace(/^\uFEFF/, ""),
);
const label = (key) => {
  if (typeof messages[key] !== "string")
    throw new Error(`Missing localized test label: ${key}`);
  return messages[key];
};

test.beforeEach(async ({ page }) => {
  page.on("pageerror", (error) =>
    console.error("Browser runtime error:", error.message),
  );
  page.on("console", (message) => {
    if (message.type() === "error")
      console.error("Browser console error:", message.text());
  });
  page.on("requestfailed", (request) =>
    console.error(
      "Failed browser request:",
      new URL(request.url()).pathname,
      request.failure()?.errorText,
    ),
  );
});

async function installFixtures(page, permission = "EDIT") {
  let draft = makeDraft(permission);
  const updates = [];
  const iconUploads = [];
  const unexpectedWrites = [];
  const fulfill = (route, body, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.replace(/^.*\/api/, "");
    const payload = request
      .headers()
      ["content-type"]?.includes("application/json")
      ? request.postDataJSON()
      : undefined;
    if (endpoint === "/agent/42/icon") {
      if (request.method() === "POST") {
        if (permission === "READ_ONLY") unexpectedWrites.push(endpoint);
        iconUploads.push(request.headers()["content-type"]);
        draft = { ...draft, icon_url: "/agent/42/icon?v=fixture-revision" };
        return fulfill(route, { icon_url: draft.icon_url });
      }
      return route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jmQAAAABJRU5ErkJggg==",
          "base64",
        ),
      });
    }
    if (await fulfillEditorReadFixture(route, endpoint)) return;
    if (endpoint === "/agent/run" || endpoint.startsWith("/agent/stop/"))
      return route.fallback();
    if (endpoint === "/agent/search_info") return fulfill(route, draft);
    if (endpoint === "/agent/update") {
      if (permission === "READ_ONLY") unexpectedWrites.push(endpoint);
      updates.push(payload);
      draft = {
        ...draft,
        ...payload,
        model_names: payload.model_ids?.length
          ? ["Fixture Model"]
          : draft.model_names,
      };
      return fulfill(route, { agent_id: draft.agent_id, status: "success" });
    }
    if (endpoint === "/agent/check_name")
      return fulfill(
        route,
        (payload?.items ?? []).map(() => ({
          name_conflict: false,
          display_name_conflict: false,
        })),
      );
    if (endpoint === "/agent/published_list")
      return fulfill(route, [{ ...draft, current_version_no: 1 }]);
    if (endpoint === "/agent/list") return fulfill(route, []);
    if (/^\/agent\/\d+\/versions$/.test(endpoint))
      return fulfill(route, { items: [], total: 0 });
    if (/^\/agent\/\d+\/publish$/.test(endpoint)) {
      unexpectedWrites.push(endpoint);
      return fulfill(
        route,
        { detail: "Publication is intentionally outside this fixture journey" },
        400,
      );
    }
    if (endpoint.startsWith("/tag-assignments/"))
      return fulfill(route, {
        resource_type: "agent",
        resource_id: String(draft.agent_id),
        assignment_count: 0,
        assignment_capacity: 100,
        assignments: [],
      });
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method()))
      unexpectedWrites.push(endpoint);
    return fulfill(route, { data: [], items: [], total: 0, status: "success" });
  });
  return { updates, iconUploads, unexpectedWrites, getDraft: () => draft };
}

async function box(locator) {
  const bounds = await locator.boundingBox();
  expect(bounds).not.toBeNull();
  return bounds;
}
async function assertNoOverflow(page) {
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
}

test("AGENT-DEBUG-D4-001 measured draft debug and preserved chat controls", async ({
  page,
}) => {
  const runs = [];
  const stops = [];
  let hold = false;
  const server = http.createServer(async (request, response) => {
    response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Access-Control-Allow-Headers", "*");
    response.setHeader("Access-Control-Expose-Headers", "run_id");
    if (request.method === "OPTIONS") {
      response.end();
      return;
    }
    let body = "";
    for await (const part of request) body += part;
    runs.push(JSON.parse(body));
    response.writeHead(200, {
      "Content-Type": "text/event-stream",
      run_id: "fixture-debug-run",
    });
    if (hold)
      response.write(
        `data: ${JSON.stringify({ type: "model_output", content: "Fixture response" })}\n\n`,
      );
    if (!hold)
      response.end(
        `data: ${JSON.stringify({ type: "final_answer", content: "Fixture response" })}\n\n`,
      );
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  await page.route("**/api/agent/run", (route) =>
    route.continue({ url: `http://127.0.0.1:${server.address().port}/run` }),
  );
  await page.route("**/api/agent/stop/**", async (route) => {
    stops.push(new URL(route.request().url()).pathname);
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ status: "success" }),
    });
  });
  const fixture = await installFixtures(page);
  try {
    await page.goto(`${baseUrl}/zh/agents/42`);
    const identity = page.getByTestId("agent-config-header");
    await expect(identity).toBeVisible();
    await identity
      .getByRole("button", {
        name: label("agent.highFidelity.debugMode"),
        exact: true,
      })
      .click();
    const panel = page.getByTestId("agent-debug-panel");
    await expect(panel).toBeVisible();
    await assertNoOverflow(page);
    const panelBox = await box(panel);
    const cardBox = await box(page.getByTestId("agent-config-card-info"));
    expect(panelBox.width).toBeCloseTo(488, 0);
    expect(panelBox.height).toBeCloseTo(930, 0);
    expect(panelBox.y).toBeCloseTo(cardBox.y, 0);
    expect(panelBox.x - cardBox.x - cardBox.width).toBeCloseTo(10, 0);
    await expect(panel).toHaveCSS("padding", "24px");
    await expect(panel).toHaveCSS("border-radius", "8px");
    await expect(panel.locator(".agent-debug-header-title")).toHaveCSS(
      "font-size",
      "20px",
    );
    await expect(panel.locator(".agent-debug-header-title")).toHaveCSS(
      "line-height",
      "28px",
    );
    await expect(
      panel.getByTestId("agent-debug-welcome").locator("h1"),
    ).toHaveCSS("font-size", "28px");
    await expect(
      panel.getByTestId("agent-debug-welcome").locator("h1"),
    ).toHaveCSS("font-weight", "700");
    await expect(
      panel.getByTestId("agent-debug-welcome").locator("h1"),
    ).toHaveCSS("line-height", "36px");
    await expect(
      panel.getByTestId("agent-debug-welcome").locator("p").first(),
    ).toHaveCSS("font-size", "16px");
    const suggestions = panel.getByTestId("agent-debug-suggestions");
    await expect(
      panel
        .getByTestId("agent-debug-welcome")
        .getByTestId("agent-debug-suggestions"),
    ).toBeVisible();
    await expect(panel.locator(".agent-debug-question-scroll")).toHaveCount(0);
    expect(
      (await box(suggestions.getByRole("button").first())).height,
    ).toBeCloseTo(46, 0);
    await expect(suggestions.getByRole("list")).toHaveCSS("gap", "12px");
    const composer = panel.locator("fieldset").first();
    expect((await box(composer)).height).toBeCloseTo(164, 0);
    expect((await box(composer)).width).toBeCloseTo(440, 0);
    await expect(composer).toHaveCSS("border-radius", "20px");
    await expect(composer).toHaveCSS("padding", "16px");
    await expect(composer).toHaveCSS(
      "box-shadow",
      /rgba\(0, 0, 0, 0\.16\) 0px 1px 6px 0px$/,
    );
    await expect(panel.locator(".agent-debug-disclaimer")).toHaveCSS(
      "font-size",
      "12px",
    );
    await expect(panel.locator(".agent-debug-disclaimer")).toHaveCSS(
      "line-height",
      "18px",
    );
    const input = panel.locator("textarea").first();
    await page.screenshot({
      path: "test/artifacts/agent-debug-layout/desktop.png",
    });
    await suggestions.getByRole("button", { name: "怎样改善睡眠？" }).click();
    await expect(input).toHaveValue("怎样改善睡眠？");
    expect(runs).toHaveLength(0);
    await expect(
      panel.getByRole("button", { name: "发送", exact: true }),
    ).toBeEnabled();
    await panel.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => runs.length).toBe(1);
    expect(runs[0]).toMatchObject({
      query: "怎样改善睡眠？",
      agent_id: 42,
      is_debug: true,
      enable_plan: false,
    });
    await expect(
      panel.getByText("Fixture response", { exact: true }),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: label("agent.debug.maximize"), exact: true })
      .click();
    expect((await box(panel)).width).toBeGreaterThan(488);
    await expect(
      panel.getByText("Fixture response", { exact: true }),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: label("agent.debug.restore"), exact: true })
      .click();
    expect((await box(panel)).width).toBeCloseTo(488, 0);
    expect((await box(panel)).x).toBeCloseTo(panelBox.x, 0);
    await panel
      .getByRole("button", { name: label("agent.debug.clear"), exact: true })
      .click();
    await expect(panel.getByTestId("agent-debug-welcome")).toBeVisible();
    await expect(
      panel.getByText("Fixture response", { exact: true }),
    ).toHaveCount(0);
    await panel
      .getByRole("button", { name: label("agent.debug.options"), exact: true })
      .click();
    await page
      .getByRole("menuitem", {
        name: label("chat.composer.planning"),
        exact: true,
      })
      .click();
    hold = true;
    await input.fill("Long fixture question");
    await panel.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => runs.length).toBe(2);
    expect(runs[1].enable_plan).toBe(true);
    const stop = panel.getByRole("button", {
      name: label("chat.composer.stopGenerating"),
      exact: true,
    });
    await expect(stop).toBeVisible();
    await expect(
      panel.getByText("Fixture response", { exact: true }),
    ).toBeVisible();
    await stop.click();
    await expect.poll(() => stops.length).toBe(1);
    await expect(stop).toHaveCount(0);
    await panel
      .getByRole("button", { name: label("agent.debug.options"), exact: true })
      .click();
    await page
      .getByRole("menuitem", {
        name: label("agent.debug.compareMode"),
        exact: true,
      })
      .click();
    await expect(panel.getByRole("combobox")).toHaveCount(2);
    await panel
      .getByRole("button", { name: label("agent.debug.options"), exact: true })
      .click();
    await page
      .getByRole("menuitem", {
        name: label("agent.debug.defaultMode"),
        exact: true,
      })
      .click();
    await expect(
      panel.getByText("Fixture response", { exact: true }),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: label("agent.debug.options"), exact: true })
      .click();
    await page
      .getByRole("menuitem", {
        name: label("agent.page.panel.debug.closeAria"),
        exact: true,
      })
      .click();
    await expect(panel).toBeHidden();
    await identity
      .getByRole("button", {
        name: label("agent.highFidelity.debugMode"),
        exact: true,
      })
      .click();
    await expect(
      panel.getByText("Fixture response", { exact: true }),
    ).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 800 });
    await assertNoOverflow(page);
    await expect(
      panel.getByRole("button", {
        name: label("agent.debug.clear"),
        exact: true,
      }),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: label("agent.debug.clear"), exact: true })
      .click();
    await expect(panel.getByTestId("agent-debug-suggestions")).toBeVisible();
    await expect(
      panel.getByRole("button", { name: "发送", exact: true }),
    ).toBeVisible();
    fixture.getDraft().example_questions = Array.from(
      { length: 6 },
      (_, index) =>
        `Legacy question ${index + 1}: a longer stored question that wraps in a constrained panel`,
    );
    await page.reload();
    await identity
      .getByRole("button", {
        name: label("agent.highFidelity.debugMode"),
        exact: true,
      })
      .click();
    const legacyQuestion = panel.getByRole("button", {
      name: fixture.getDraft().example_questions[5],
      exact: true,
    });
    await legacyQuestion.click();
    await expect(panel.locator("textarea").first()).toHaveValue(
      fixture.getDraft().example_questions[5],
    );
    const constrainedPanel = await box(panel);
    const sendBox = await box(
      panel.getByRole("button", { name: "发送", exact: true }),
    );
    expect(sendBox.y + sendBox.height).toBeLessThanOrEqual(
      constrainedPanel.y + constrainedPanel.height,
    );
    await assertNoOverflow(page);
    expect(fixture.updates).toHaveLength(0);
    expect(fixture.unexpectedWrites).toEqual([]);
    await page.goto(`${baseUrl}/zh/newchat?agent_id=42`);
    await expect(page.locator(".agent-debug-panel")).toHaveCount(0);
    await expect(page.locator(".agent-debug-disclaimer")).toHaveCount(0);
    await expect(page.locator("fieldset").first()).toBeVisible();
    await page.screenshot({
      path: "test/artifacts/agent-debug-layout/default-chat.png",
    });
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
