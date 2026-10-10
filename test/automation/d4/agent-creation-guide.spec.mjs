import fs from "node:fs";
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
const baseUrl = process.env.NEXENT_E2E_BASE_URL ?? "http://localhost:4010";
const messages = JSON.parse(
  fs.readFileSync(
    path.join(repositoryRoot, "frontend/public/locales/zh/common.json"),
    "utf8",
  ),
);
const label = (key) => {
  if (typeof messages[key] !== "string")
    throw new Error(`Missing localized test label: ${key}`);
  return messages[key];
};

function makeDraft(permission = "EDIT") {
  return {
    agent_id: 42,
    name: "fixture_agent",
    display_name: "健康小助手",
    description: "A deterministic health question assistant.",
    author: "Fixture Author",
    permission,
    created_by: "fixture-user",
    model_ids: [7],
    model_names: ["Fixture Model"],
    tools: [
      {
        tool_id: 9001,
        name: "knowledge_base_search",
        origin_name: "knowledge_base_search",
        description: "Fixture knowledge-base retrieval",
        params: [
          {
            name: "index_names",
            type: "array",
            optional: true,
            default: ["fixture-kb"],
          },
        ],
      },
    ],
    skills: [],
    sub_agent_id_list: [],
    sub_agent_relations: [],
    external_sub_agent_id_list: [],
    group_ids: [],
    ingroup_permission: "READ_ONLY",
    greeting_message: "你好，我可以帮助你解答健康问题。",
    example_questions: [
      "如何保持健康？",
      "每天应该运动多久？",
      "怎样改善睡眠？",
    ],
    max_steps: 10,
    requested_output_tokens: 4096,
    is_main_agent: true,
    is_a2a: false,
    provide_run_summary: false,
    allow_chat_metadata: false,
    enable_protocol_repair_retry: false,
    is_available: true,
    unavailable_reasons: [],
    verification_config: {
      enabled: false,
      guardrail_config: { enabled: false, rules: [], default_action: "pass" },
    },
    duty_prompt: "Answer the question using the draft Agent configuration.",
    constraint_prompt: "",
    few_shots_prompt: "",
    current_version_no: null,
  };
}

async function installFixtures(page, permission = "EDIT") {
  let draft = makeDraft(permission);
  const updates = [];
  const creations = [];
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
    if (endpoint === "/tenant_config/deployment_version")
      return fulfill(route, {
        deployment_version: "speed",
        app_version: "fixture",
        status: "success",
      });
    if (endpoint === "/user/current_user_info")
      return fulfill(route, {
        data: {
          user: {
            user_id: "fixture-user",
            tenant_id: "fixture-tenant",
            user_email: "fixture@nexent.test",
            user_role: "SPEED",
            auth_provider: "local",
            group_ids: [],
            permissions: [],
            accessibleRoutes: [
              "/agents",
              "/mcp-space",
              "/knowledges",
              "/newchat",
            ],
          },
        },
      });
    if (endpoint === "/groups/list")
      return fulfill(route, { data: [], total: 0, message: "ok" });
    if (endpoint === "/conversation/list")
      return fulfill(route, {
        code: 0,
        data: {
          items: [],
          metadata: { total: 0, today: 0, last_7_days: 0, older: 0 },
        },
      });
    if (endpoint === "/agent/42/knowledge-capabilities")
      return fulfill(route, {
        code: 0,
        data: {
          agent_id: 42,
          version_no: 1,
          sources: {
            local: {
              enabled: false,
              max_select: 0,
              requires_same_embedding_model: false,
              default_summary: "",
              default_knowledge_ids: [],
              default_range_values: [],
            },
            aidp: {
              enabled: false,
              max_select: 0,
              default_summary: "",
              default_knowledge_ids: [],
            },
          },
        },
      });
    if (endpoint === "/agent/run" || endpoint.startsWith("/agent/stop/")) {
      unexpectedWrites.push(endpoint);
      return fulfill(route, { detail: "Guide must not run Agents" }, 400);
    }
    if (endpoint === "/agent/search_info") return fulfill(route, draft);
    if (endpoint === "/agent/update") {
      if (!payload?.agent_id && permission !== "READ_ONLY") {
        creations.push(payload);
        draft = { ...draft, ...payload };
        return fulfill(route, { agent_id: 42, status: "success" });
      }
      unexpectedWrites.push(endpoint);
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
    if (endpoint === "/agent/list/page")
      return fulfill(route, {
        items: [],
        creator_counts: {},
        pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
      });
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
    if (endpoint === "/model/list" || endpoint === "/model/llm_list")
      return fulfill(route, {
        data: [
          {
            model_id: 8,
            model_name: "fixture_second",
            display_name: "Second Model",
            model_type: "llm",
            model_factory: "custom",
            connect_status: "available",
          },
          {
            model_id: 7,
            model_name: "fixture_model",
            display_name: "Fixture Model",
            model_type: "llm",
            model_factory: "custom",
            connect_status: "available",
            max_tokens: 8192,
            context_window_tokens: 8192,
            max_output_tokens: 4096,
          },
        ],
      });
    if (endpoint === "/model/catalog/inference_field_specs")
      return fulfill(route, { data: {} });
    if (
      endpoint === "/tool/list" ||
      endpoint === "/skills" ||
      endpoint === "/tag-libraries"
    )
      return fulfill(route, []);
    if (
      /^\/skills\/instances/.test(endpoint) ||
      endpoint === "/skills/instance/list"
    )
      return fulfill(route, []);
    if (endpoint === "/indices/health")
      return fulfill(route, { status: "healthy", elasticsearch: "connected" });
    if (endpoint === "/indices")
      return fulfill(route, {
        indices: ["fixture-kb"],
        count: 1,
        indices_info: [
          {
            name: "fixture-kb",
            display_name: "Fixture Knowledge Base",
            stats: {
              base_info: {
                doc_count: 1,
                chunk_count: 2,
                creation_date: "2026-09-14T00:00:00Z",
              },
            },
          },
        ],
      });
    if (endpoint.startsWith("/a2a/client/"))
      return fulfill(route, { status: "success", data: [] });
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
  return {
    creations,
    updates,
    iconUploads,
    unexpectedWrites,
    getDraft: () => draft,
  };
}

const tour = (page) => page.locator(".agent-creation-guide.ant-tour");
const targets = ["assistant", "core", "resources", "workflow"];
async function checkStep(page, index, screenshot) {
  const popup = tour(page);
  await expect(popup.locator(".ant-tour-title")).toHaveText(
    label(`agent.creationGuide.${targets[index]}.title`),
  );
  await expect(popup.locator(".ant-tour-description")).toHaveText(
    label(`agent.creationGuide.${targets[index]}.description`),
  );
  await expect(popup).toBeVisible();
  await expect(
    popup.getByRole("button", {
      name: label(
        index === 3 ? "agent.creationGuide.finish" : "agent.creationGuide.next",
      ),
      exact: true,
    }),
  ).toBeFocused();
  await expect
    .poll(() =>
      page
        .locator('.agent-creation-guide.ant-tour-mask mask rect[fill="black"]')
        .evaluate((rect) => {
          const bounds = rect.getBBox();
          return Math.max(
            ...["x", "y", "width", "height"].map((key) =>
              Math.abs(bounds[key] - Number(rect.getAttribute(key))),
            ),
          );
        }),
    )
    .toBeLessThanOrEqual(1);
  const measured = await popup.evaluate((element, index) => {
    const section = element.querySelector(".ant-tour-section");
    const rect = section.getBoundingClientRect();
    const title = element.querySelector(".ant-tour-title");
    const description = element.querySelector(".ant-tour-description");
    const buttons = [...element.querySelectorAll(".ant-tour-actions .ant-btn")];
    const hole = document.querySelector(
      '.agent-creation-guide.ant-tour-mask mask rect[fill="black"]',
    );
    const anchorElement = document.querySelector(
      `[data-agent-guide="${["assistant", "core", "resources", "workflow"][index]}"]`,
    );
    const arrowElement = element.querySelector(".ant-tour-arrow");
    if (!anchorElement || !arrowElement || !hole)
      throw new Error(
        `Missing geometry: index=${index}, anchor=${Boolean(anchorElement)}, arrow=${Boolean(arrowElement)}, hole=${Boolean(hole)}; anchors=${JSON.stringify([...document.querySelectorAll("[data-agent-guide]")].map((node) => node.getAttribute("data-agent-guide")))}`,
      );
    const anchor = anchorElement.getBoundingClientRect();
    const arrow = arrowElement.getBoundingClientRect();
    const style = getComputedStyle(section);
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      rootClass: element.className,
      rootStyle: element.getAttribute("style"),
      rootMargin: getComputedStyle(element).margin,
      anchor: {
        x: anchor.x,
        y: anchor.y,
        width: anchor.width,
        height: anchor.height,
      },
      hole: Object.fromEntries(
        ["x", "y", "width", "height", "rx"].map((key) => [
          key,
          Number(hole.getAttribute(key)),
        ]),
      ),
      arrow: {
        x: arrow.x,
        y: arrow.y,
        width: arrow.width,
        height: arrow.height,
      },
      padding: style.padding,
      radius: style.borderRadius,
      shadow: style.boxShadow,
      title: [
        getComputedStyle(title).fontSize,
        getComputedStyle(title).lineHeight,
        getComputedStyle(title).fontWeight,
        getComputedStyle(title).color,
      ],
      description: [
        getComputedStyle(description).fontSize,
        getComputedStyle(description).lineHeight,
        getComputedStyle(description).fontWeight,
        getComputedStyle(description).color,
      ],
      contentGap:
        description.getBoundingClientRect().top -
        element.querySelector(".ant-tour-header").getBoundingClientRect()
          .bottom,
      footerGap:
        element.querySelector(".ant-tour-footer").getBoundingClientRect().top -
        description.getBoundingClientRect().bottom,
      buttonGap:
        buttons[1].getBoundingClientRect().left -
        buttons[0].getBoundingClientRect().right,
      buttons: buttons.map((button) => ({
        height: button.getBoundingClientRect().height,
        width: button.getBoundingClientRect().width,
        font: getComputedStyle(button).fontSize,
        radius: getComputedStyle(button).borderRadius,
      })),
    };
  }, index);
  expect(measured.width).toBeCloseTo(index === 0 ? 292 : 300, 0);
  expect(measured.height).toBe(174);
  expect(measured.hole.rx).toBe(8);
  expect(measured.hole.width).toBeCloseTo(
    measured.anchor.width + (index === 0 ? 2 : index === 3 ? 0 : 34),
    0,
  );
  expect(measured.hole.height).toBeCloseTo(
    measured.anchor.height +
      (index === 0 ? -18 : index === 3 ? 0 : index === 2 ? 13 : 16),
    0,
  );
  expect(measured.padding).toBe("16px");
  expect(measured.radius).toBe("6px");
  expect(measured.shadow).toBe("rgba(0, 0, 0, 0.16) 0px 8px 24px 0px");
  expect(measured.title).toEqual(["16px", "24px", "500", "rgb(25, 25, 25)"]);
  expect(measured.description).toEqual([
    "14px",
    "22px",
    "400",
    "rgb(119, 119, 119)",
  ]);
  expect(measured.contentGap).toBe(8);
  expect(measured.footerGap).toBe(16);
  expect(measured.buttonGap).toBe(8);
  if (page.viewportSize().width === 1920) {
    const sourceHoles = [
      { x: 63, y: 10, width: 563, height: 1062 },
      { x: 625, y: 130, width: 1295, height: 524 },
      { x: 625, y: 647, width: 1295, height: 359 },
      { x: 1029, y: 63, width: 891, height: 73 },
    ];
    const sourceBodies = [
      { x: 651, y: 453 },
      { x: 625, y: 673 },
      { x: 625, y: 455 },
      { x: 1598, y: 154 },
    ];
    for (const key of ["x", "y", "width", "height"]) {
      expect(
        Math.abs(measured.hole[key] - sourceHoles[index][key]),
      ).toBeLessThanOrEqual(1);
    }
    for (const key of ["x", "y"])
      expect(
        Math.abs(measured[key] - sourceBodies[index][key]),
      ).toBeLessThanOrEqual(1);
  }
  for (const button of measured.buttons) {
    expect(button.height).toBe(28);
    expect(button.width).toBeGreaterThanOrEqual(72);
    expect(button.width).toBeLessThanOrEqual(160);
    expect(button.font).toBe("12px");
    expect(button.radius).toBe("4px");
  }
  if (screenshot) {
    const size = page.viewportSize().width;
    await page.screenshot({
      path: test.info().outputPath(`${size}-step-${index + 1}.png`),
    });
    await fs.promises.writeFile(
      test.info().outputPath(`${size}-step-${index + 1}.json`),
      JSON.stringify(measured, null, 2),
    );
  }
  return measured;
}
async function clearPreference(page) {
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage))
      if (key.startsWith("nexent.agent.creation-guide."))
        localStorage.removeItem(key);
  });
}
async function noTour(page) {
  await expect(page.locator('[data-agent-guide="core"]')).toBeVisible();
  await page.waitForTimeout(250);
  await expect(tour(page)).toHaveCount(0);
}

test("AGENT-GUIDE-D4-001 create, measured four-step navigation, remembered finish/skip and permission/responsive boundaries", async ({
  page,
}) => {
  const fixture = await installFixtures(page);
  await page.goto(`${baseUrl}/zh/agents`);
  await page
    .getByRole("button", { name: label("agent.action.create"), exact: true })
    .click();
  await page
    .getByPlaceholder(label("agentConfig.createModal.namePlaceholder"))
    .fill("首次引导测试");
  await page
    .getByRole("button", {
      name: label("agentConfig.createModal.submit"),
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(/\/zh\/agents\/42\?onboarding=1$/);
  const first = await checkStep(page, 0, true);
  expect(first.height).toBe(174);
  expect(first.x).toBeCloseTo(651, 0);
  expect(first.y).toBeCloseTo(453, 0);
  await tour(page)
    .getByRole("button", {
      name: label("agent.creationGuide.next"),
      exact: true,
    })
    .click();
  await checkStep(page, 1, true);
  await tour(page)
    .getByRole("button", {
      name: label("agent.creationGuide.previous"),
      exact: true,
    })
    .click();
  await checkStep(page, 0);
  for (const index of [1, 2, 3]) {
    await tour(page)
      .getByRole("button", {
        name: label("agent.creationGuide.next"),
        exact: true,
      })
      .click();
    await checkStep(page, index, index !== 1);
  }
  await tour(page)
    .getByRole("button", {
      name: label("agent.creationGuide.finish"),
      exact: true,
    })
    .click();
  await noTour(page);
  await expect(page.getByTestId("agent-variable-name-input")).toBeVisible();
  await expect(
    page.locator('[data-agent-guide="assistant"] textarea'),
  ).toBeFocused();
  await page.reload();
  await noTour(page);
  await clearPreference(page);
  await page.goto(`${baseUrl}/zh/agents/42`);
  await noTour(page);
  await page.goto(`${baseUrl}/zh/agents/42?onboarding=1`);
  await checkStep(page, 0);
  await tour(page)
    .getByRole("button", {
      name: label("agent.creationGuide.skip"),
      exact: true,
    })
    .click();
  await noTour(page);
  await page.reload();
  await noTour(page);
  expect(fixture.creations).toHaveLength(1);
  expect(fixture.updates).toEqual([]);
  expect(fixture.unexpectedWrites).toEqual([]);

  const readOnly = await page.context().newPage();
  const readOnlyFixture = await installFixtures(readOnly, "READ_ONLY");
  await clearPreference(page);
  await readOnly.goto(`${baseUrl}/zh/agents/42?onboarding=1`);
  await noTour(readOnly);
  expect(readOnlyFixture.unexpectedWrites).toEqual([]);
  await readOnly.close();

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${baseUrl}/zh/agents/42?onboarding=1`);
  for (let index = 0; index < 4; index++) {
    const measured = await checkStep(page, index, true);
    expect(measured.x).toBeGreaterThanOrEqual(0);
    expect(measured.y).toBeGreaterThanOrEqual(0);
    expect(measured.x + measured.width).toBeLessThanOrEqual(1281);
    expect(measured.y + measured.height).toBeLessThanOrEqual(801);
    await tour(page)
      .getByRole("button", {
        name: label(
          index === 3
            ? "agent.creationGuide.finish"
            : "agent.creationGuide.next",
        ),
        exact: true,
      })
      .click();
  }
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    ),
  ).toBeLessThanOrEqual(1);
  expect(fixture.updates).toEqual([]);
  expect(fixture.unexpectedWrites).toEqual([]);
});
