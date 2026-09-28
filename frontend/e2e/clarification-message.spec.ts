import { expect, test, type Page, type Route } from "@playwright/test";

test.use({
  channel: "chrome",
  actionTimeout: 10000,
  viewport: { width: 1440, height: 1100 },
});
test.setTimeout(45000);

const form = {
  schema_version: 1,
  questions: [
    {
      id: "scope",
      type: "text",
      title: "Which region?",
      required: true,
      placeholder: "Region",
    },
    {
      id: "period",
      type: "single_choice",
      title: "Which period?",
      required: true,
      options: [
        { id: "month", label: "This month" },
        { id: "year", label: "This year" },
      ],
    },
    {
      id: "metrics",
      type: "multiple_choice",
      title: "Which metrics?",
      required: true,
      allow_other: true,
      options: [
        { id: "sales", label: "Sales" },
        { id: "profit", label: "Profit" },
      ],
    },
  ],
};
const fallback =
  "1. Which region?\n   Region\n2. Which period?\n   - This month\n   - This year\n3. Which metrics?\n   - Sales\n   - Profit\n   - 其他 / Other";
const messages: object[] = [
  {
    message_id: 1,
    role: "user",
    message: "Analyze sales",
    status: "completed",
  },
  {
    message_id: 2,
    role: "assistant",
    status: "completed",
    message: [
      { type: "human_interaction", unit_index: 0, content: JSON.stringify(form) },
      { type: "final_answer", unit_index: 1, content: fallback },
    ],
  },
];
const json = (route: Route, body: unknown) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
async function setup(page: Page, history = messages) {
  page.on("console", (msg) => {
    if (msg.type() === "error")
      console.error("BROWSER", msg.text().slice(0, 1200));
  });
  page.on("pageerror", (error) => {
    throw error;
  });
  await page.route("**/api/**", (route) => json(route, {}));
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
          permissions: [],
          accessibleRoutes: ["/newchat"],
        },
      },
    })
  );
  await page.route("**/api/memory/config/load", (route) =>
    json(route, { MEMORY_SWITCH: "N" })
  );
  await page.route("**/api/groups/list", (route) =>
    json(route, { data: [], total: 0 })
  );
  await page.route("**/api/agent/published_list", (route) =>
    json(route, [
      {
        agent_id: 10,
        name: "Analyst",
        description: "Test agent",
        model_id: 1,
        model_name: "test",
        is_available: true,
        is_main_agent: true,
      },
    ])
  );
  await page.route("**/api/conversation/list?*", (route) =>
    json(route, {
      code: 0,
      data: {
        items: [
          {
            conversation_id: 123,
            conversation_title: "Clarification check",
            agent_id: 10,
            create_time: Date.now(),
            update_time: Date.now(),
          },
        ],
        metadata: { total: 1, today: 1, last_7_days: 0, older: 0 },
      },
    })
  );
  await page.route("**/api/conversation/123", (route) =>
    json(route, {
      code: 0,
      data: [
        {
          conversation_id: 123,
          conversation_title: "Clarification check",
          agent_id: 10,
          create_time: Date.now(),
          message: history,
        },
      ],
    })
  );
  await page.route("**/api/agent/10/knowledge-capabilities*", (route) =>
    json(route, {
      code: 0,
      data: {
        agent_id: 10,
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
            default_range_values: [],
          },
        },
      },
    })
  );
}

test("ordinary clarification submit recovers from conflict and sends readable query", async ({
  page,
}) => {
  await setup(page);
  const requests: Record<string, unknown>[] = [];
  await page.route("**/api/agent/run", (route) => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1)
      return route.fulfill({
        status: 200,
        headers: { "X-Stream-Status": "conflict" },
        contentType: "text/event-stream",
        body: "",
      });
    return route.fulfill({
      status: 200,
      headers: { conversation_id: "123" },
      contentType: "text/event-stream",
      body: 'data: {"type":"final_answer","content":"Analysis complete","unit_index":0}\n\ndata: {"type":"complete","content":""}\n\n',
    });
  });
  await page.goto("http://127.0.0.1:3100/en/newchat?conversation_id=123");
  const card = page.locator('[data-slot="clarification-message"]');
  await expect(card).toBeVisible({ timeout: 15000 });
  await expect(
    card.getByRole("button", { name: "Submit and continue" })
  ).toBeDisabled();
  await card.locator("textarea").first().fill("Asia Pacific");
  await card.locator('input[type="text"]').fill("Compare with last quarter");
  await card.getByText("This month", { exact: true }).click();
  await card.getByText("Sales", { exact: true }).click();
  await card.getByText("Profit", { exact: true }).click();
  await card.getByRole("button", { name: "Submit and continue" }).click();
  await expect(card.getByText(/previous run is finishing/)).toBeVisible();
  await expect(card.locator("textarea").first()).toHaveValue("Asia Pacific");
  await expect(
    card.getByRole("button", { name: "Submit and continue" })
  ).toBeEnabled();
  await expect(page.getByText("Analyze sales", { exact: true })).toHaveCount(1);
  await card.getByRole("button", { name: "Submit and continue" }).click();
  await expect(
    page.getByText("Analysis complete", { exact: true })
  ).toBeVisible();
  expect(requests).toHaveLength(2);
  expect(requests[1].query).toContain("Asia Pacific");
  expect(requests[1].query).toContain("This month");
  expect(requests[1].query).toContain("Sales");
  expect(requests[1].query).toContain("Profit");
  expect(requests[1].query).toContain("Compare with last quarter");
  await expect(page.getByText(fallback, { exact: true })).toHaveCount(0);
  for (const key of [
    "enable_hitl",
    "hitl_run_id",
    "hitl_after_event",
    "decision",
  ])
    expect(requests[1]).not.toHaveProperty(key);
  await expect(card.getByRole("button", { name: "Submitted" })).toBeDisabled();
  await card.screenshot({ path: "/tmp/nexent-clarification-en.png" });
});

test("older historical cards are read-only on a narrow Chinese page", async ({
  page,
}) => {
  await setup(page, [
    ...messages,
    {
      message_id: 3,
      role: "user",
      message: "Continue with Asia Pacific",
      status: "completed",
    },
    {
      message_id: 4,
      role: "assistant",
      message: [{ type: "final_answer", content: "Done" }],
      status: "completed",
    },
  ]);
  await page.setViewportSize({ width: 390, height: 1300 });
  await page.goto("http://127.0.0.1:3100/zh/newchat?conversation_id=123");
  const card = page.locator('[data-slot="clarification-message"]');
  await expect(card).toBeVisible({ timeout: 15000 });
  await expect(card.locator("textarea").first()).toBeDisabled();
  await expect(card.getByRole("button", { name: "提交并继续" })).toBeDisabled();
  expect(await card.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(
    true
  );
  await card.screenshot({ path: "/tmp/nexent-clarification-zh-mobile.png" });
});

for (const method of ["button", "enter"] as const) {
  test(`ordinary composer ${method} preserves draft when the previous worker is finishing`, async ({
    page,
  }) => {
    await setup(page);
    let calls = 0;
    await page.route("**/api/agent/run", (route) => {
      calls++;
      return route.fulfill({
        status: 200,
        headers: { "X-Stream-Status": "conflict" },
        contentType: "text/event-stream",
        body: "",
      });
    });
    await page.goto("http://127.0.0.1:3100/en/newchat?conversation_id=123");
    const composer = page.getByPlaceholder("Send a message...");
    await expect(composer).toBeVisible();
    await composer.fill("Only East China");
    if (method === "enter") await composer.press("Enter");
    else await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: "previous run is finishing" })
    ).toBeVisible();
    await expect(composer).toHaveValue("Only East China");
    expect(calls).toBe(1);
    await expect(
      page
        .locator('[data-role="user"]')
        .getByText("Only East China", { exact: true })
    ).toHaveCount(0);
  });
}

for (const outcome of ["complete", "stop"] as const) {
  test(`a streaming card stays editable but cannot submit before ${outcome}`, async ({
    page,
  }) => {
    await setup(page, []);
    let stops = 0;
    await page.route("**/api/agent/stop/123", (route) => {
      stops++;
      return json(route, { status: "success" });
    });
    await page.addInitScript(() => {
      const originalFetch = window.fetch;
      let controller: ReadableStreamDefaultController<Uint8Array>;
      let closed = false;
      const close = () => {
        if (!closed) {
          closed = true;
          controller.close();
        }
      };
      (
        window as typeof window & { finishClarificationTest: () => void }
      ).finishClarificationTest = close;
      window.fetch = async (input, init) => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (!url.endsWith("/api/agent/run")) return originalFetch(input, init);
        const stream = new ReadableStream<Uint8Array>({
          start(value) {
            controller = value;
            const content = {
              schema_version: 1,
              questions: [
                { id: "scope", type: "text", title: "Which region?" },
              ],
            };
            controller.enqueue(
              new TextEncoder().encode(
                `data: ${JSON.stringify({ type: "human_interaction", content, unit_index: 0 })}\n\ndata: ${JSON.stringify({ type: "final_answer", content: "1. Which region?", unit_index: 1 })}\n\n`
              )
            );
          },
        });
        init?.signal?.addEventListener("abort", close, { once: true });
        return new Response(stream, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            conversation_id: "123",
          },
        });
      };
    });
    await page.goto("http://127.0.0.1:3100/en/newchat?conversation_id=123");
    const composer = page.getByPlaceholder("Send a message...");
    await expect(composer).toBeVisible();
    await composer.fill("Analyze sales");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const card = page.locator('[data-slot="clarification-message"]');
    await expect(card).toBeVisible();
    await expect(card.locator("textarea")).toBeEnabled();
    await card.locator("textarea").fill("Asia Pacific");
    await expect(
      card.getByRole("button", { name: "Submit and continue" })
    ).toBeDisabled();
    await composer.fill("Only East China");
    await composer.press("Enter");
    await expect(composer).toHaveValue("Only East China");
    if (outcome === "complete") {
      await page.evaluate(() =>
        (
          window as typeof window & { finishClarificationTest: () => void }
        ).finishClarificationTest()
      );
      await expect(
        card.getByRole("button", { name: "Submit and continue" })
      ).toBeEnabled();
      expect(stops).toBe(0);
    } else {
      await page
        .getByRole("button", { name: "Stop generating", exact: true })
        .click();
      await expect.poll(() => stops).toBe(1);
      await expect(card.locator("textarea")).toBeDisabled();
      await expect(
        card.getByRole("button", { name: "Submit and continue" })
      ).toBeDisabled();
    }
  });
}

test("the last clarification in a shared conversation remains read-only", async ({
  page,
}) => {
  await setup(page);
  let runs = 0;
  await page.route("**/api/agent/run", (route) => {
    runs++;
    return json(route, {});
  });
  await page.route("**/api/share/test-share", (route) =>
    json(route, {
      code: 0,
      data: {
        share_id: "test-share",
        title: "Shared clarification",
        render_version: "newchat",
        snapshot: {
          conversation_id: 123,
          conversation_title: "Shared clarification",
          create_time: Date.now(),
          message: messages,
        },
      },
    })
  );
  await page.goto("http://127.0.0.1:3100/en/share/test-share");
  const card = page.locator('[data-slot="clarification-message"]');
  await expect(card).toBeVisible();
  await expect(card.locator("textarea")).toBeDisabled();
  await expect(
    card.getByRole("button", { name: "Submit and continue" })
  ).toBeDisabled();
  expect(runs).toBe(0);
});
