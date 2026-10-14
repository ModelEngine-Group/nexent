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
const baseUrl = process.env.NEXENT_E2E_BASE_URL ?? "http://127.0.0.1:3000";
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

const populatedTools = [
  {
    tool_id: 9002,
    name: "weather_lookup",
    origin_name: "weather_lookup",
    description: "Fixture weather lookup",
    source: "local",
    category: "search",
    labels: ["天气", "检索"],
    is_available: true,
    is_user_selectable: true,
    inputs: JSON.stringify({ location: { type: "string" } }),
    params: [
      {
        name: "location",
        type: "string",
        optional: false,
        default: "Shenzhen",
        description: "Fixture location",
      },
    ],
  },
  {
    tool_id: 9003,
    name: "menu_lookup",
    origin_name: "menu_lookup",
    description: "Fixture menu lookup",
    source: "local",
    category: "search",
    labels: ["菜单"],
    is_available: true,
    is_user_selectable: true,
    inputs: "{}",
    params: [],
  },
  {
    tool_id: 9004,
    name: "feedback_lookup",
    origin_name: "feedback_lookup",
    description: "Fixture lookup without optional labels",
    source: "local",
    category: "search",
    is_available: true,
    is_user_selectable: true,
    inputs: "{}",
    params: [],
  },
];
const publishedChild = {
  agent_id: 61,
  name: "health_assistant",
  display_name: "健康管理助手",
  description: "Fixture published child Agent",
  author: "Fixture Author",
  is_available: true,
  is_main_agent: true,
  permission: "READ_ONLY",
  current_version_no: 3,
  version_name: "Current published version",
  tags: ["保健"],
};
const externalChild = {
  id: 81,
  name: "外部服务助手",
  agent_url: "https://fixture.nexent.test/agent",
  source_type: "url",
  is_available: true,
};

function makeDraft(permission = "EDIT", populated = false) {
  return {
    agent_id: 42,
    name: "fixture_agent",
    display_name: "配置测试智能体",
    description: "",
    author: "Fixture Author",
    permission,
    created_by: "fixture-user",
    model_ids: [],
    model_names: [],
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
      ...(populated ? structuredClone(populatedTools) : []),
    ],
    skills: [],
    sub_agent_id_list: populated ? [61] : [],
    sub_agent_relations: populated
      ? [
          {
            agent_id: 61,
            agent_name: publishedChild.display_name,
            version_no: 1,
            version_name: "Saved selected version",
          },
        ]
      : [],
    external_sub_agent_id_list: populated ? [81] : [],
    group_ids: [],
    ingroup_permission: "READ_ONLY",
    greeting_message: "",
    example_questions: [],
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
    duty_prompt: "",
    constraint_prompt: "",
    few_shots_prompt: "",
    current_version_no: null,
  };
}

async function installFixtures(page, permission = "EDIT", populated = false) {
  let draft = makeDraft(permission, populated);
  const updates = [];
  const iconUploads = [];
  const unexpectedWrites = [];
  const relationRemovals = [];
  const toolUpdates = [];
  const externalRelations = new Set(draft.external_sub_agent_id_list);
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
            accessibleRoutes: ["/agents", "/mcp-space", "/knowledges"],
          },
        },
      });
    if (endpoint === "/groups/list")
      return fulfill(route, { data: [], total: 0, message: "ok" });
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
      if (Array.isArray(payload.enabled_tool_ids)) {
        draft.tools = payload.enabled_tool_ids.map((id) => {
          const existing = draft.tools.find((tool) => tool.tool_id === id);
          const canonical = populatedTools.find((tool) => tool.tool_id === id);
          if (!existing && !canonical)
            throw new Error(`Fixture has no tool definition for ${id}`);
          return structuredClone(existing ?? canonical);
        });
      }
      if (Array.isArray(payload.related_agent_ids))
        draft.sub_agent_id_list = payload.related_agent_ids;
      if (Array.isArray(payload.related_agents)) {
        draft.sub_agent_relations = payload.related_agents.map((relation) => ({
          ...draft.sub_agent_relations.find(
            ({ agent_id }) => agent_id === relation.agent_id,
          ),
          ...relation,
        }));
      }
      if (Array.isArray(payload.related_external_agent_ids))
        draft.external_sub_agent_id_list = payload.related_external_agent_ids;
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
    if (endpoint === "/agent/list") return fulfill(route, []);
    if (endpoint === "/agent/published_list")
      return fulfill(route, populated ? [publishedChild] : []);
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
    if (endpoint === "/tool/list")
      return fulfill(route, populated ? populatedTools : []);
    if (endpoint === "/tool/search") {
      const tool = populatedTools.find(
        ({ tool_id }) => tool_id === payload.tool_id,
      );
      if (!tool)
        throw new Error(`Fixture has no tool instance for ${payload.tool_id}`);
      return fulfill(route, {
        enabled: true,
        params: Object.fromEntries(
          tool.params.map((param) => [param.name, param.default]),
        ),
      });
    }
    if (endpoint === "/tool/update") {
      if (permission === "READ_ONLY") unexpectedWrites.push(endpoint);
      toolUpdates.push(payload);
      return fulfill(route, { status: "success" });
    }
    if (endpoint === "/skills" || endpoint === "/tag-libraries")
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
    if (endpoint === "/a2a/client/agents")
      return fulfill(route, {
        status: "success",
        data: populated ? [externalChild] : [],
      });
    if (endpoint === "/a2a/client/sub-agents/42")
      return fulfill(route, {
        status: "success",
        data: externalRelations.has(81) ? [externalChild] : [],
      });
    if (endpoint === "/a2a/client/relations" && request.method() === "DELETE") {
      if (permission === "READ_ONLY") unexpectedWrites.push(endpoint);
      const params = new URL(request.url()).searchParams;
      const relation = {
        local_agent_id: Number(params.get("local_agent_id")),
        external_agent_id: Number(params.get("external_agent_id")),
      };
      relationRemovals.push(relation);
      externalRelations.delete(relation.external_agent_id);
      return fulfill(route, { status: "success" });
    }
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
    updates,
    iconUploads,
    unexpectedWrites,
    relationRemovals,
    toolUpdates,
    getDraft: () => draft,
  };
}

async function box(locator) {
  const bounds = await locator.boundingBox();
  expect(bounds).not.toBeNull();
  return bounds;
}
async function assertNoOverflow(page) {
  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.client + 1);
}

test("AGENT-CONFIG-D4-001 measured empty editor, saved guidance and guarded workflow journey", async ({
  page,
}) => {
  const fixture = await installFixtures(page);
  await page.goto(`${baseUrl}/zh/agents/42`);
  const scroll = page.getByTestId("agent-config-scroll-region");
  await expect(scroll).toBeVisible();
  await expect(page.getByTestId("agent-config-header")).toBeVisible();
  const workspace = await box(page.getByTestId("agent-config-workspace"));
  const conversation = await box(
    page.getByTestId("agent-config-conversation-panel"),
  );
  const identity = await box(page.getByTestId("agent-config-header"));
  expect(workspace.x).toBeCloseTo(64, 0);
  expect(conversation.width).toBeCloseTo(561, 0);
  expect(identity.width).toBeCloseTo(1295, 0);
  expect(identity.height).toBeCloseTo(74, 0);
  const modes = page
    .getByTestId("agent-config-header")
    .getByRole("group", { name: label("agent.highFidelity.workflowModes") });
  expect((await box(modes)).height).toBeCloseTo(32, 0);
  expect((await box(modes)).width).toBeCloseTo(318, 0);
  const greeting = await box(page.getByTestId("agent-configuration-greeting"));
  const composer = await box(
    page.getByTestId("agent-configuration-welcome").locator("fieldset"),
  );
  console.log("Conversation geometry:", { greeting, composer });
  expect(greeting.y).toBeCloseTo(348, 0);
  expect(greeting.height).toBeCloseTo(100, 0);
  expect(composer.width).toBeCloseTo(512, 0);
  expect(composer.height).toBeCloseTo(164, 0);
  expect(composer.y).toBeCloseTo(448, 0);
  await assertNoOverflow(page);
  const cards = ["info", "model", "resources", "advanced"].map((name) =>
    page.getByTestId(`agent-config-card-${name}`),
  );
  for (const card of cards) {
    await expect(card).toHaveCSS("border-radius", "8px");
    await expect(card).toHaveCSS("background-color", "rgb(255, 255, 255)");
    await expect(card).toHaveCSS("box-shadow", "none");
    await expect(card).toHaveCSS("border-top-width", "0px");
  }
  const info = await box(cards[0]);
  const model = await box(cards[1]);
  expect(info.width).toBeCloseTo(1261, 0);
  expect(info.height).toBeGreaterThanOrEqual(224);
  expect(model.height).toBeCloseTo(268, 0);
  expect(model.y - info.y - info.height).toBeCloseTo(12, 0);
  await expect(
    cards[0].getByPlaceholder(label("agent.displayNamePlaceholder")),
  ).toBeVisible();
  await expect(
    cards[0].getByPlaceholder(label("agent.namePlaceholder")),
  ).toBeVisible();
  await expect(
    cards[0].getByPlaceholder(label("agent.authorPlaceholder")),
  ).toBeVisible();
  const descriptionInput = cards[0].getByPlaceholder(
    label("agent.highFidelity.descriptionPlaceholder"),
  );
  expect((await box(descriptionInput.locator(".."))).height).toBeCloseTo(
    100,
    0,
  );
  await expect(descriptionInput).toHaveAttribute("maxlength", "200");
  const columns = cards[0].locator(".grid > div");
  const descriptionColumn = await box(columns.nth(0));
  const avatarColumn = await box(columns.nth(1));
  expect(descriptionColumn.width).toBeCloseTo(avatarColumn.width, 0);
  expect(
    avatarColumn.x - descriptionColumn.x - descriptionColumn.width,
  ).toBeCloseTo(16, 0);
  expect((await box(cards[0].locator(".ant-avatar"))).height).toBeCloseTo(
    100,
    0,
  );
  await expect(page.locator("#agent-primary-prompt")).toHaveAttribute(
    "maxlength",
    "1000",
  );
  await expect(cards[0].locator(".ant-avatar")).toHaveCSS(
    "border-top-color",
    "rgb(201, 201, 201)",
  );
  await expect(cards[0].locator(".ant-avatar")).toHaveCSS(
    "border-top-width",
    "1px",
  );
  await expect(
    page.getByPlaceholder(label("agent.highFidelity.greetingPlaceholder")),
  ).toHaveAttribute("maxlength", "200");
  await page.screenshot({
    path: path.join(
      repositoryRoot,
      "test/artifacts/agent-config-empty-1920.png",
    ),
  });
  expect((await box(cards[2])).height).toBeCloseTo(740, 0);
  expect((await box(cards[3])).height).toBeCloseTo(520, 0);
  const resourceCard = cards[2];
  const questionPlaceholder = label("agent.guide.example.placeholder");
  await expect(resourceCard.getByPlaceholder(questionPlaceholder)).toHaveCount(
    0,
  );
  const selectedKnowledgeBase = page.getByTestId(
    "agent-selected-knowledge-base-fixture-kb",
  );
  const selectedKnowledgeBaseBounds = await box(selectedKnowledgeBase);
  expect(selectedKnowledgeBaseBounds.width).toBeCloseTo(602.5, 0);
  expect(selectedKnowledgeBaseBounds.height).toBeCloseTo(48, 0);
  await expect(selectedKnowledgeBase).toHaveCSS(
    "border-top-color",
    "rgb(223, 223, 223)",
  );
  await expect(selectedKnowledgeBase).toHaveCSS("border-top-width", "1px");
  await expect(selectedKnowledgeBase).toHaveCSS("border-radius", "4px");
  await expect(selectedKnowledgeBase).toHaveCSS(
    "background-color",
    "rgb(255, 255, 255)",
  );
  await expect(selectedKnowledgeBase).not.toHaveCSS("box-shadow", "none");
  await expect(selectedKnowledgeBase).toHaveCSS("padding-left", "12px");
  await expect(selectedKnowledgeBase).toHaveCSS("padding-top", "8px");
  await expect(selectedKnowledgeBase).toContainText("Fixture Knowledge Base");
  await expect(selectedKnowledgeBase).toContainText("2026-09-14");
  await expect(selectedKnowledgeBase).toContainText("使用过");
  await expect(selectedKnowledgeBase).toContainText("1文档");
  await expect(selectedKnowledgeBase).toContainText("2分块");
  const knowledgeBaseName = selectedKnowledgeBase.getByTestId(
    "agent-selected-knowledge-base-name",
  );
  const knowledgeBaseMetadata = selectedKnowledgeBase.getByTestId(
    "agent-selected-knowledge-base-metadata",
  );
  const nameBounds = await box(knowledgeBaseName);
  const metadataBounds = await box(knowledgeBaseMetadata);
  expect(metadataBounds.x - (nameBounds.x + nameBounds.width)).toBeCloseTo(
    8,
    0,
  );
  const configureButton = selectedKnowledgeBase.getByRole("button", {
    name: new RegExp(label("agent.knowledge.button.configure")),
  });
  const removeButton = selectedKnowledgeBase.getByRole("button", {
    name: new RegExp(label("skillPool.remove")),
  });
  const configureButtonBounds = await box(configureButton);
  const removeButtonBounds = await box(removeButton);
  expect(
    removeButtonBounds.x -
      (configureButtonBounds.x + configureButtonBounds.width),
  ).toBeCloseTo(0, 0);
  await expect(
    selectedKnowledgeBase.getByTestId("agent-knowledge-base-icon"),
  ).toHaveCSS("width", "24px");
  await expect(
    selectedKnowledgeBase.getByTestId(
      "agent-knowledge-base-metadata-separator",
    ),
  ).toHaveCount(2);
  await expect(configureButton).toBeVisible();
  await expect(removeButton).toBeVisible();
  const resourceKeys = ["knowledge", "guide", "skill", "tool", "child"];
  const headings = await resourceCard
    .locator("[data-slot='collapsible-trigger']")
    .allTextContents();
  resourceKeys.forEach((key, index) =>
    expect(headings[index]).toContain(label(`agent.highFidelity.${key}Title`)),
  );
  const title = resourceCard.getByText(
    label("agent.highFidelity.knowledgeTitle"),
    { exact: true },
  );
  await expect(title).toHaveCSS("font-size", "16px");
  await expect(title).toHaveCSS("line-height", "24px");
  await expect(title).toHaveCSS("font-weight", "500");
  await expect(title).toHaveCSS("color", "rgb(25, 25, 25)");
  const description = resourceCard.getByText(
    label("agent.highFidelity.knowledgeDescription"),
    { exact: true },
  );
  await expect(description).toHaveCSS("font-size", "12px");
  await expect(description).toHaveCSS("line-height", "22px");
  await expect(description).toHaveCSS("font-weight", "400");
  await expect(description).toHaveCSS("color", "rgb(128, 128, 128)");
  const knowledgeHeader = resourceCard
    .locator("[data-slot='collapsible-trigger']")
    .first();
  await knowledgeHeader.click();
  await expect(
    resourceCard.getByRole("button", {
      name: label("agentConfig.layout.addKnowledgeBase"),
      exact: true,
    }),
  ).toBeHidden();
  await knowledgeHeader.click();
  await expect(
    resourceCard.getByRole("button", {
      name: label("agentConfig.layout.addKnowledgeBase"),
      exact: true,
    }),
  ).toBeVisible();
  const addTool = resourceCard.getByRole("button", {
    name: label("agentConfig.layout.addTool"),
    exact: true,
  });
  await addTool.scrollIntoViewIfNeeded();
  const addBounds = await box(addTool);
  const rowBounds = await box(addTool.locator(".."));
  expect(addBounds.height).toBeCloseTo(48, 0);
  expect(addBounds.width * 2 + 8).toBeCloseTo(rowBounds.width, 0);
  await expect(addTool).toHaveCSS("background-color", "rgba(25, 25, 25, 0.03)");
  expect(fixture.updates).toHaveLength(0);
  await cards[0]
    .getByRole("button", {
      name: `${label("agent.highFidelity.defaultAvatars")} 2`,
      exact: true,
    })
    .click();
  await expect.poll(() => fixture.iconUploads.length).toBe(1);
  expect(fixture.iconUploads[0]).toContain("multipart/form-data");
  await expect
    .poll(() =>
      fixture.updates.some((update) =>
        update.icon_url?.includes("fixture-revision"),
      ),
    )
    .toBe(true);
  await expect(page.getByTestId("agent-config-header")).toContainText(
    /自动保存于.*\d{2}:\d{2}/,
  );
  const updatesBeforeResourceSelection = fixture.updates.length;
  const associationsBefore = structuredClone(fixture.getDraft());
  for (const key of [
    "agent.highFidelity.addModel",
    "agentConfig.layout.addKnowledgeBase",
    "agentConfig.layout.addSkill",
    "agentConfig.layout.addTool",
    "agentConfig.layout.addAgent",
  ]) {
    const entry = page
      .getByRole("button", { name: label(key), exact: true })
      .first();
    await entry.scrollIntoViewIfNeeded();
    await entry.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    const drawer = page.locator(".ant-drawer-content-wrapper:visible");
    await expect
      .poll(async () => {
        const position = await box(drawer);
        return Math.round(position.x + position.width);
      })
      .toBe(1920);
    const bounds = await box(drawer);
    expect(bounds.width).toBeCloseTo(760, 0);
    expect(bounds.x + bounds.width).toBeCloseTo(1920, 0);
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /关闭|Close/ })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  expect(fixture.updates).toHaveLength(updatesBeforeResourceSelection);
  expect(fixture.getDraft()).toEqual(associationsBefore);
  const guide = resourceCard.getByPlaceholder(
    label("agent.highFidelity.greetingPlaceholder"),
  );
  await guide.fill("Welcome from the fixture journey");
  await descriptionInput.fill("A deterministic browser fixture draft");
  await expect
    .poll(() => fixture.getDraft().description)
    .toBe("A deterministic browser fixture draft");
  await expect
    .poll(() => fixture.getDraft().greeting_message)
    .toBe("Welcome from the fixture journey");
  for (let index = 0; index < 5; index++) {
    const addQuestion = resourceCard.getByRole("button", {
      name: label("agent.highFidelity.addPresetQuestion"),
      exact: true,
    });
    await addQuestion.click();
    const question = resourceCard
      .getByPlaceholder(questionPlaceholder)
      .nth(index);
    if (index === 0) {
      const questionBounds = await box(question);
      expect(questionBounds.width).toBeCloseTo(564, 0);
      expect(questionBounds.height).toBeCloseTo(32, 0);
    }
    await question.fill(`Question ${index + 1}`);
  }
  await expect(
    resourceCard.getByRole("button", {
      name: label("agent.highFidelity.addPresetQuestion"),
      exact: true,
    }),
  ).toBeDisabled();
  await expect.poll(() => fixture.getDraft().example_questions.length).toBe(5);
  await resourceCard
    .getByPlaceholder(label("agent.guide.example.placeholder"))
    .first()
    .fill("Edited fixture question");
  await expect
    .poll(() => fixture.getDraft().example_questions[0])
    .toBe("Edited fixture question");
  await resourceCard
    .getByRole("button", { name: label("agent.guide.example.removeAria") })
    .first()
    .click();
  await expect(
    resourceCard.getByRole("button", {
      name: label("agent.highFidelity.addPresetQuestion"),
      exact: true,
    }),
  ).toBeEnabled();
  const publish = page.getByTestId("agent-config-header").getByRole("button", {
    name: label("agent.config.button.publish"),
    exact: true,
  });
  await publish.click();
  await expect(
    page
      .getByText(label("agent.validation.modelRequired"), { exact: true })
      .first(),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", {
      name: label("agent.highFidelity.addModel"),
      exact: true,
    })
    .click();
  const modelDialog = page.getByRole("dialog");
  await modelDialog
    .getByRole("button", { name: "Fixture Model", exact: true })
    .click();
  await modelDialog
    .getByRole("button", { name: /关闭|Close/ })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect.poll(() => fixture.getDraft().model_ids).toEqual([7]);
  await publish.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /关闭|Close/ })
    .first()
    .click();
  await page
    .getByTestId("agent-config-header")
    .getByRole("button", {
      name: label("agent.highFidelity.debugMode"),
      exact: true,
    })
    .click();
  await expect(page.getByTestId("agent-debug-pane")).toBeVisible();
  await page
    .getByTestId("agent-config-header")
    .getByRole("button", {
      name: label("agent.highFidelity.configureMode"),
      exact: true,
    })
    .click();
  await cards[3]
    .getByRole("button", {
      name: label("agent.highFidelity.moreSettings"),
      exact: true,
    })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByText(label("agent.guardrail.disabledHint"), { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /关闭|Close/ })
    .first()
    .click();
  await expect(page.getByTestId("agent-config-header")).toBeInViewport();
  await expect(page.locator(".ant-modal-mask:visible")).toHaveCount(0);
  await page.screenshot({
    path: path.join(
      repositoryRoot,
      "test/artifacts/agent-config-advanced-1920.png",
    ),
  });
  expect(await scroll.evaluate((element) => element.scrollTop)).toBeGreaterThan(
    0,
  );
  await page.reload();
  await expect(
    page.getByPlaceholder(label("agent.highFidelity.greetingPlaceholder")),
  ).toHaveValue("Welcome from the fixture journey");
  await page.setViewportSize({ width: 1280, height: 800 });
  await assertNoOverflow(page);
  await expect(page.getByTestId("agent-config-header")).toBeVisible();
  expect(fixture.unexpectedWrites).toEqual([]);
});

test("AGENT-CONFIG-D4-001 read-only draft keeps configuration reachable and rejects mutations", async ({
  page,
}) => {
  const fixture = await installFixtures(page, "READ_ONLY", true);
  await page.goto(`${baseUrl}/zh/agents/42`);
  await expect(page.getByTestId("agent-config-header")).toBeVisible();
  await expect(
    page.getByTestId("agent-config-header").getByRole("button", {
      name: label("agent.config.button.publish"),
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    page.getByPlaceholder(label("agent.highFidelity.greetingPlaceholder")),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", {
      name: label("agentConfig.layout.addTool"),
      exact: true,
    }),
  ).toBeDisabled();
  for (const rowId of [
    "agent-selected-tool-9002",
    "agent-selected-tool-9003",
    "agent-selected-tool-9004",
    "agent-selected-child-internal-61",
    "agent-selected-child-external-81",
  ]) {
    const row = page.getByTestId(rowId);
    await expect(row).toBeVisible();
    const controls = row.getByRole("button");
    for (let index = 0; index < (await controls.count()); index++)
      await expect(controls.nth(index)).toBeDisabled();
  }
  await expect(page.getByTestId("agent-selected-tool-9001")).toHaveCount(0);
  expect(fixture.updates).toEqual([]);
  expect(fixture.unexpectedWrites).toEqual([]);
  expect(fixture.relationRemovals).toEqual([]);
  expect(fixture.toolUpdates).toEqual([]);
});

test("AGENT-CONFIG-D4-001 selected tool and child-Agent rows retain geometry, versions and persisted removals", async ({
  page,
}) => {
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  const fixture = await installFixtures(page, "EDIT", true);
  await page.goto(`${baseUrl}/zh/agents/42`);
  const resourceCard = page.getByTestId("agent-config-card-resources");
  const toolGrid = page.getByTestId("agent-selected-tool-grid");
  const childGrid = page.getByTestId("agent-selected-child-grid");
  const toolRows = populatedTools.map(({ tool_id }) =>
    page.getByTestId(`agent-selected-tool-${tool_id}`),
  );
  const internalRow = page.getByTestId("agent-selected-child-internal-61");
  const externalRow = page.getByTestId("agent-selected-child-external-81");
  const selectedKnowledgeBase = page.getByTestId(
    "agent-selected-knowledge-base-fixture-kb",
  );
  await expect(internalRow).toContainText(publishedChild.display_name);
  await expect(externalRow).toContainText(externalChild.name);
  await expect(toolRows[0]).toContainText("weather_lookup");
  await expect(page.getByTestId("agent-selected-tool-9001")).toHaveCount(0);

  async function assertGrid(grid, expectedIds, columnCount = 2) {
    await expect(grid).toHaveCSS("display", "grid");
    await expect(grid).toHaveCSS("gap", "8px");
    const columns = await grid.evaluate((element) =>
      getComputedStyle(element).gridTemplateColumns.split(" ").map(parseFloat),
    );
    expect(columns).toHaveLength(columnCount);
    if (columnCount === 2) expect(columns[0]).toBeCloseTo(columns[1], 0);
    const children = grid.locator(":scope > *");
    await expect(children).toHaveCount(expectedIds.length + 1);
    expect(
      await children.evaluateAll((elements) =>
        elements
          .slice(0, -1)
          .map((element) => element.getAttribute("data-testid")),
      ),
    ).toEqual(expectedIds);
    const addEntry = children.last();
    await expect(addEntry).toHaveRole("button");
    await expect(addEntry).toHaveAccessibleName(
      label(
        expectedIds[0].startsWith("agent-selected-tool")
          ? "agentConfig.layout.addTool"
          : "agentConfig.layout.addAgent",
      ),
    );
    await expect(addEntry).toHaveCSS("height", "48px");
    await expect(addEntry).toHaveCSS(
      "background-color",
      "rgba(25, 25, 25, 0.03)",
    );
    await expect(addEntry).toHaveCSS("border-radius", "8px");
    const first = await box(children.first());
    expect(first.width).toBeCloseTo(columns[0], 0);
    if (columnCount === 2) {
      const second = await box(children.nth(1));
      expect(second.x - first.x - first.width).toBeCloseTo(8, 0);
      expect(second.y).toBeCloseTo(first.y, 0);
    }
    if ((await children.count()) > columnCount) {
      const nextRow = await box(children.nth(columnCount));
      expect(nextRow.y - first.y - first.height).toBeCloseTo(8, 0);
    }
  }

  async function assertSelectedRow(row, expectedName, iconSize, expectedTags) {
    const bounds = await box(row);
    expect(bounds.width).toBeCloseTo(602.5, 0);
    expect(bounds.height).toBeCloseTo(48, 0);
    await expect(row).toHaveCSS("border-radius", "4px");
    await expect(row).toHaveCSS("border-top-width", "1px");
    await expect(row).toHaveCSS("border-top-color", "rgb(223, 223, 223)");
    await expect(row).toHaveCSS("padding-left", "12px");
    await expect(row).toHaveCSS("padding-right", "12px");
    await expect(row).toHaveCSS("padding-top", "8px");
    await expect(row).toHaveCSS("padding-bottom", "8px");
    await expect(row).toHaveCSS("background-color", "rgb(255, 255, 255)");
    expect(
      await row.evaluate((element) => getComputedStyle(element).boxShadow),
    ).toBe(
      await selectedKnowledgeBase.evaluate(
        (element) => getComputedStyle(element).boxShadow,
      ),
    );
    const name = row.locator('[data-slot="selected-resource-name"]');
    await expect(name).toHaveText(expectedName);
    await expect(name).toHaveCSS("font-size", "14px");
    await expect(name).toHaveCSS("line-height", "22px");
    await expect(name).toHaveCSS("font-weight", "400");
    await expect(name).toHaveCSS("--tw-tracking", "0px");
    // Chromium serializes explicit zero letter spacing as "normal" in CSSOM.
    expect(
      await name.evaluate((element) => {
        const value = getComputedStyle(element).letterSpacing;
        return value === "normal" ? 0 : parseFloat(value);
      }),
    ).toBe(0);
    await expect(name).toHaveCSS("color", "rgb(25, 25, 25)");
    await expect(name).toHaveCSS("text-overflow", "ellipsis");
    const icon = row.locator(":scope > div:first-child > span:first-child");
    expect((await box(icon)).width).toBeCloseTo(iconSize, 0);
    expect((await box(icon)).height).toBeCloseTo(iconSize, 0);
    const tags = row.locator('[data-slot="selected-resource-tag"]');
    await expect(tags).toHaveText(expectedTags);
    for (let index = 0; index < expectedTags.length; index++) {
      await expect(tags.nth(index)).toHaveCSS("font-size", "12px");
      await expect(tags.nth(index)).toHaveCSS("line-height", "18px");
      await expect(tags.nth(index)).toHaveCSS("font-weight", "400");
      await expect(tags.nth(index)).toHaveCSS("color", "rgb(119, 119, 119)");
      await expect(tags.nth(index)).toHaveCSS("border-radius", "4px");
      await expect(tags.nth(index)).toHaveCSS(
        "background-color",
        "rgb(243, 243, 243)",
      );
    }
    if (expectedTags.length) {
      const nameBounds = await box(name);
      const tagBounds = await box(tags.first());
      expect(tagBounds.x - nameBounds.x - nameBounds.width).toBeCloseTo(8, 0);
    }
    const buttons = row.getByRole("button");
    for (let index = 0; index < (await buttons.count()); index++) {
      const button = buttons.nth(index);
      await expect(button).toBeVisible();
      await expect(button).toBeEnabled();
      expect((await box(button)).width).toBeCloseTo(24, 0);
      expect((await box(button)).height).toBeCloseTo(24, 0);
      await expect(button).toHaveCSS("color", "rgb(119, 119, 119)");
      await expect(button.locator("svg")).toHaveAttribute("width", "14");
      await expect(button.locator("svg")).toHaveAttribute("height", "14");
      const buttonBounds = await box(button);
      expect(buttonBounds.y + buttonBounds.height / 2).toBeCloseTo(
        bounds.y + bounds.height / 2,
        0,
      );
    }
  }

  await assertGrid(
    toolGrid,
    populatedTools.map(({ tool_id }) => `agent-selected-tool-${tool_id}`),
  );
  await assertGrid(childGrid, [
    "agent-selected-child-internal-61",
    "agent-selected-child-external-81",
  ]);
  for (let index = 0; index < populatedTools.length; index++)
    await assertSelectedRow(
      toolRows[index],
      populatedTools[index].name,
      24,
      populatedTools[index].labels ?? [],
    );
  await assertSelectedRow(internalRow, publishedChild.display_name, 32, [
    "保健",
  ]);
  await assertSelectedRow(externalRow, externalChild.name, 32, []);
  expect((await box(selectedKnowledgeBase)).width).toBeCloseTo(602.5, 0);
  expect((await box(selectedKnowledgeBase)).height).toBeCloseTo(48, 0);
  await expect(selectedKnowledgeBase).toHaveCSS("padding-left", "12px");
  await expect(selectedKnowledgeBase).toHaveCSS("padding-top", "8px");
  await expect(selectedKnowledgeBase).toHaveCSS("border-radius", "4px");
  await expect(selectedKnowledgeBase).toHaveCSS(
    "border-top-color",
    "rgb(223, 223, 223)",
  );
  await expect(selectedKnowledgeBase).toContainText("1文档");
  await expect(selectedKnowledgeBase).toContainText("2分块");
  await internalRow.locator('[data-slot="selected-resource-name"]').hover();
  const tooltip = page.getByRole("tooltip");
  await expect(tooltip).toContainText(publishedChild.display_name);
  await expect(tooltip).toContainText("V1");
  await expect(tooltip).toContainText("Saved selected version");
  await expect(tooltip).not.toContainText("V3");
  await page.getByTestId("agent-config-header").hover();
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  expect(fixture.updates).toEqual([]);
  expect(fixture.relationRemovals).toEqual([]);
  expect(fixture.toolUpdates).toEqual([]);
  await assertNoOverflow(page);
  await resourceCard.screenshot({
    path: path.join(
      repositoryRoot,
      "test/artifacts/agent-config-selected-resources-1920.png",
    ),
  });

  await page.setViewportSize({ width: 1280, height: 800 });
  await assertNoOverflow(page);
  await assertGrid(
    toolGrid,
    populatedTools.map(({ tool_id }) => `agent-selected-tool-${tool_id}`),
  );
  await assertGrid(childGrid, [
    "agent-selected-child-internal-61",
    "agent-selected-child-external-81",
  ]);
  await page.setViewportSize({ width: 620, height: 800 });
  await assertGrid(
    toolGrid,
    populatedTools.map(({ tool_id }) => `agent-selected-tool-${tool_id}`),
    1,
  );
  await assertGrid(
    childGrid,
    ["agent-selected-child-internal-61", "agent-selected-child-external-81"],
    1,
  );
  await assertNoOverflow(page);
  await page.setViewportSize({ width: 1920, height: 1080 });

  await toolRows[0]
    .getByRole("button", {
      name: `${label("toolPool.configure")} weather_lookup`,
      exact: true,
    })
    .click();
  const configDialog = page.getByRole("dialog");
  await expect(configDialog).toContainText("weather_lookup");
  await expect(configDialog.getByRole("textbox").first()).toHaveValue(
    "Shenzhen",
  );
  await configDialog
    .getByRole("button", { name: /关闭|Close/ })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(fixture.updates).toEqual([]);
  await toolRows[1]
    .getByRole("button", {
      name: `${label("toolPool.remove")} menu_lookup`,
      exact: true,
    })
    .click();
  await expect(toolRows[1]).toHaveCount(0);
  await expect
    .poll(() => fixture.getDraft().tools.map(({ tool_id }) => tool_id))
    .toEqual([9001, 9002, 9004]);
  await expect
    .poll(() => fixture.toolUpdates)
    .toEqual([{ tool_id: 9003, agent_id: 42, params: {}, enabled: false }]);
  expect(fixture.getDraft().sub_agent_relations[0].version_no).toBe(1);
  await internalRow.getByRole("button").click();
  await expect(internalRow).toHaveCount(0);
  await expect.poll(() => fixture.getDraft().sub_agent_id_list).toEqual([]);
  await expect.poll(() => fixture.getDraft().sub_agent_relations).toEqual([]);
  await externalRow.getByRole("button").click();
  await expect(externalRow).toHaveCount(0);
  await expect
    .poll(() => fixture.relationRemovals)
    .toEqual([{ local_agent_id: 42, external_agent_id: 81 }]);
  await expect
    .poll(() => fixture.getDraft().external_sub_agent_id_list)
    .toEqual([]);
  expect(
    fixture.updates.some((update) => update.enabled_tool_ids?.includes(9001)),
  ).toBe(true);
  await page.reload();
  await expect(page.getByTestId("agent-selected-tool-9002")).toBeVisible();
  await expect(page.getByTestId("agent-selected-tool-9004")).toBeVisible();
  await expect(page.getByTestId("agent-selected-tool-9003")).toHaveCount(0);
  await expect(
    page.getByTestId("agent-selected-child-internal-61"),
  ).toHaveCount(0);
  await expect(
    page.getByTestId("agent-selected-child-external-81"),
  ).toHaveCount(0);
  await expect(
    page.getByTestId("agent-selected-knowledge-base-fixture-kb"),
  ).toContainText("Fixture Knowledge Base");
  expect(fixture.getDraft().tools.map(({ tool_id }) => tool_id)).toEqual([
    9001, 9002, 9004,
  ]);
  expect(fixture.unexpectedWrites).toEqual([]);
  expect(runtimeErrors).toEqual([]);
});
