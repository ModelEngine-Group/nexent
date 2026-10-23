// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Locator } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-CONTROLS-D4-003", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1441, height: 1244 });
  const { writes } = await prepareWorkbench(page, 1, { reasoning: true, modelEffort: "medium", agentEffort: "high" });
  const requests: Array<Record<string, any>> = [];
  await page.route("**/api/agent/run", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: 0, data: {} }),
    });
  });
  const options = [
    ["none", "无"],
    ["minimal", "最低"],
    ["low", "低"],
    ["medium", "中"],
    ["high", "高"],
    ["xhigh", "极高"],
    ["max", "最高"],
  ];
  const trigger = page.locator('[data-slot="model-selector-trigger"]');
  const settings = page.locator('[data-slot="model-selector-content"]');
  const open = async () => {
    if (
      !(await page
        .locator('[data-slot="model-selector-content"][data-state="open"]')
        .isVisible())
    )
      await trigger.click();
    await expect(settings).toBeVisible();
    await expect(settings).toHaveAttribute("data-state", "open");
  };
  const setThinking = async (enabled: boolean) => {
    await open();
    const toggle = settings.getByRole("switch");
    if ((await toggle.getAttribute("aria-checked")) !== String(enabled))
      await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", String(enabled));
  };
  const choose = async (label: string) => {
    await open();
    await expect
      .poll(() =>
        settings.evaluate(
          (element) =>
            element
              .getAnimations()
              .filter((animation) => animation.playState === "running").length,
        ),
      )
      .toBe(0);
    const panelBefore = (await settings.boundingBox())!;
    await settings.getByRole("combobox").click();
    const popup = page.locator("[data-model-effort-popup]");
    await expect
      .poll(() =>
        popup.evaluate(
          (element) =>
            element
              .getAnimations()
              .filter((animation) => animation.playState === "running").length,
        ),
      )
      .toBe(0);
    const popupBefore = (await popup.boundingBox())!;
    await popup.getByRole("option", { name: label, exact: true }).click();
    await open();
    await expect(settings.getByRole("combobox")).toHaveText(label);
    const surplusWidth = await settings
      .getByRole("combobox")
      .evaluate((element) => {
        const range = document.createRange();
        range.selectNodeContents(element.querySelector("span")!);
        const style = getComputedStyle(element);
        const spacing = [
          style.paddingLeft,
          style.paddingRight,
          style.borderLeftWidth,
          style.borderRightWidth,
          style.columnGap,
        ].reduce((sum, value) => sum + (Number.parseFloat(value) || 0), 0);
        return (
          element.getBoundingClientRect().width -
          range.getBoundingClientRect().width -
          element.querySelector("svg")!.getBoundingClientRect().width -
          spacing
        );
      });
    expect(
      Math.abs(surplusWidth),
      label + ": effort trigger fits text and chevron",
    ).toBeLessThanOrEqual(2);
    await settings.getByRole("combobox").click();
    await expect
      .poll(() =>
        popup.evaluate(
          (element) =>
            element
              .getAnimations()
              .filter((animation) => animation.playState === "running").length,
        ),
      )
      .toBe(0);
    const selected = popup.locator('[role="option"][data-state="checked"]');
    await expect(selected).toHaveText(label);
    const separation = await selected.evaluate((element) => {
      const text = element.querySelector("span")!;
      const icon = element.querySelector("svg")!;
      const range = document.createRange();
      range.selectNodeContents(text);
      return (
        icon.getBoundingClientRect().left - range.getBoundingClientRect().right
      );
    });
    expect(
      separation,
      label + ": text must leave space before the checkmark",
    ).toBeGreaterThanOrEqual(4);
    await expect
      .poll(() =>
        settings.evaluate(
          (element) =>
            element
              .getAnimations()
              .filter((animation) => animation.playState === "running").length,
        ),
      )
      .toBe(0);
    const panelAfter = (await settings.boundingBox())!;
    const popupAfter = (await popup.boundingBox())!;
    for (const dimension of ["x", "y", "width"] as const) {
      expect(
        Math.abs(panelAfter[dimension] - panelBefore[dimension]),
        label + ": model panel " + dimension + " stays anchored",
      ).toBeLessThanOrEqual(1);
      expect(
        Math.abs(popupAfter[dimension] - popupBefore[dimension]),
        label + ": effort popup " + dimension + " stays anchored",
      ).toBeLessThanOrEqual(1);
    }
    await popup.getByRole("option", { name: label, exact: true }).click();
  };
  const send = async (input: Locator, modelId = 1) => {
    if (await settings.isVisible()) await trigger.click();
    await expect(settings).not.toBeVisible();
    const index = requests.length;
    await input.fill(`Reasoning fixture ${index}`);
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => requests.length).toBe(index + 1);
    await expect(
      page.getByRole("button", { name: "发送", exact: true }),
    ).toBeVisible();
    const body = requests[index];
    expect(body.model_id).toBe(modelId);
    expect(body.query).toContain("Reasoning fixture");
    expect(body.minio_files).toBeNull();
    expect(body.is_debug).toBe(false);
    expect(body).not.toHaveProperty("temperature");
    expect(body).not.toHaveProperty("top_p");
    const generation = (body.workbench ?? body).generation_config ?? {};
    if (modelId === 1) {
      if (body.workbench && requests.length <= options.length) expect(generation.temperature).toBe(0.7);
      else if (!body.workbench) expect(generation).toMatchObject({temperature:0,top_p:0.8});
    } else {
      expect(generation.temperature ?? null).toBeNull();
      expect(generation.top_p ?? null).toBeNull();
    }
    return body;
  };
  let workbenchLabels: string[] = [];
  const assertOptions = async () => {
    await open();
    await settings.getByRole("combobox").click();
    const labels = await page
      .locator("[data-model-effort-popup]")
      .getByRole("option")
      .allTextContents();
    expect(labels).toEqual(["自动", ...options.map(([, label]) => label)]);
    await page
      .locator("[data-model-effort-popup]")
      .getByRole("option", { name: "低", exact: true })
      .click();
    await open();
    await choose("自动");
    await choose("低");
    return labels;
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(trigger).toContainText("Fixture Model");
      await open();
      await expect(settings.getByRole("switch")).toHaveAttribute(
        "aria-checked",
        "false",
      );
      await expect(settings.getByRole("combobox")).toHaveCount(0);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await setThinking(true);
    await expect(settings.getByRole("combobox")).toHaveText("中");
    await expect.poll(async () => {
      const effort = await settings.getByText("思考强度",{exact:true}).boundingBox();
      const advanced = await settings.getByRole("button",{name:"高级设置",exact:true}).getByText("高级设置",{exact:true}).boundingBox();
      return advanced!.y-effort!.y-effort!.height;
    }).toBeLessThanOrEqual(16);
    workbenchLabels = await assertOptions();
    await settings
      .getByRole("button", { name: "高级设置", exact: true })
      .hover();
    const temperature = page
      .getByRole("region", { name: "高级设置" })
      .getByRole("spinbutton", { name: "温度", exact: true });
    await temperature.fill("0.7");
    await temperature.press("Enter");
    for (const [value, label] of options) {
      await choose(label);
      const body = await send(page.locator("[data-workbench-composer]"));
      expect(body.workbench.generation_config).toMatchObject({
        deep_thinking: true,
        thinking_effort: value,
      });
      expect(body).not.toHaveProperty("reasoning_effort");
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.goto(`${process.env.NEXENT_BASE_URL}/zh/newchat`);
    await page
      .getByRole("button", { name: /Internal Analyst/ })
      .first()
      .click();
    await open();
    await expect(settings.getByRole("combobox")).toHaveCount(0);
    await setThinking(true);
    await expect(settings.getByRole("combobox")).toHaveText("高");
    expect(await assertOptions()).toEqual(workbenchLabels);
    await settings.getByRole("button",{name:"高级设置",exact:true}).hover();
    const panel = page.getByRole("region",{name:"高级设置",exact:true});
    await panel.getByRole("spinbutton",{name:"温度",exact:true}).fill("0");
    await panel.getByRole("spinbutton",{name:"温度",exact:true}).press("Enter");
    await panel.getByRole("spinbutton",{name:"Top P",exact:true}).fill("0.8");
    await panel.getByRole("spinbutton",{name:"Top P",exact:true}).press("Enter");
    await page.keyboard.press("Escape");

    for (const [value, label] of options) {
      await choose(label);
      const body = await send(page.getByRole("textbox").last());
      expect(body.reasoning_effort).toBe(value);
      expect(body.generation_config).toMatchObject({
        deep_thinking: true,
        thinking_effort: value,
      });
    }
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await contract.assertion(
      contract.expectedIds("assertions")[0],
      async () => {
        for (const route of ["newchat", "workbench"] as const) {
          if (route === "workbench")
            await page.goto(`${process.env.NEXENT_BASE_URL}/zh/workbench`);
          await setThinking(true);
          await choose("自动");
          const input =
            route === "workbench"
              ? page.locator("[data-workbench-composer]")
              : page.getByRole("textbox").last();
          const auto = await send(input);
          expect(auto).not.toHaveProperty("reasoning_effort");
          expect((auto.workbench ?? auto).generation_config).toMatchObject({
            deep_thinking: true,
            thinking_effort: "auto",
          });
          await setThinking(false);
          const off = await send(input);
          expect(off).not.toHaveProperty("reasoning_effort");
          expect((off.workbench ?? off).generation_config.deep_thinking).toBe(
            false,
          );
          if (route === "newchat")
            expect(off.generation_config).not.toHaveProperty("thinking_effort");
          await open();
          await expect(settings.getByRole("combobox")).toHaveCount(0);
          await setThinking(true);
          await expect(settings.getByRole("combobox")).toHaveText(route === "newchat" ? "高" : "中");
          await choose("极高");
          await setThinking(false);
          await setThinking(true);
          await expect(settings.getByRole("combobox")).toHaveText(route === "newchat" ? "高" : "中");
          await settings.getByText("Plain Model", { exact: true }).click();
          await open();
          await expect(settings.getByRole("combobox")).toHaveCount(0);
          await settings.getByText("Automatic Model", {exact:true}).click();
          await expect(trigger).toContainText("Automatic Model");
          await setThinking(true);
          await expect(settings.getByRole("combobox")).toHaveText("自动");
          await choose("高");
          await setThinking(false);
          await setThinking(true);
          await expect(settings.getByRole("combobox")).toHaveText("自动");
          const unconfigured = await send(input, 3);
          expect((unconfigured.workbench ?? unconfigured).generation_config).toMatchObject({deep_thinking:true,thinking_effort:"auto"});
          expect(unconfigured).not.toHaveProperty("reasoning_effort");
        }
      },
    );
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    await contract.assertion(contract.expectedIds("assertions")[1], async () => {
      const common = { model_type: "llm", model_factory: "openai", connect_status: "available" };
      const models = [
        { ...common, model_id: 1, model_name: "fixture-model", display_name: "Fixture Model" },
        { ...common, model_id: 4, model_name: "missing-capability", display_name: "Missing Capability" },
        ...(["unknown", "unsupported", "supported"] as const).map((status, index) => ({
          ...common, model_id: 5 + index, model_name: `${status}-toggle`,
          display_name: status === "supported" ? "Toggle Only Model" : `${status} Capability`,
          extra_params: { enable_thinking: false },
          reasoning_capability: { status, control: "toggle", levels: [], source: "catalog", controls: status === "supported" ? [{ type: "toggle" }] : [] },
        })),
      ];
      await page.route("**/api/model/list", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: models }) }));
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/workbench`);
      const beforeRequests = requests.length;
      const beforeWrites = writes.length;
      const reason = "当前模型不支持开启思考模式";
      for (const name of [
        "Missing Capability", "unknown Capability", "unsupported Capability",
      ]) {
        await open();
        await settings.getByText(name, { exact: true }).click();
      await page.mouse.move(0, 0);
        await open();
        const toggle = settings.getByRole("switch");
        await expect(toggle).toHaveAttribute("aria-disabled", "true");
      await expect(toggle).toHaveAccessibleDescription(reason);
      await expect(settings.locator('[data-slot="model-selector-effort"] > p')).toHaveCount(0);
      await toggle.focus();
      await expect(page.getByRole("tooltip")).toHaveCount(0);
      await toggle.hover();
      await expect(page.getByRole("tooltip")).toHaveText(reason);
      await page.mouse.move(0, 0);
      await expect(page.getByRole("tooltip")).toHaveCount(0);
        await toggle.click({ force: true });
        await expect(page.getByRole("tooltip")).toHaveText(reason);
        await expect(toggle).toHaveAttribute("aria-checked", "false");
        await expect(settings.getByRole("combobox")).toHaveCount(0);
        await expect(trigger).toContainText(name);
      await trigger.click();
      await expect(settings).toBeHidden();
      await page.mouse.move(0, 0);
      await open();
      await expect(page.getByRole("tooltip")).toHaveCount(0);
      await settings.getByRole("switch").press("Enter");
      await expect(page.getByRole("tooltip")).toHaveText(reason);
      await expect(settings.getByRole("switch")).toHaveAttribute("aria-checked", "false");
      await trigger.click();
      await expect(settings).toBeHidden();
      }
      await open();
      await settings.getByText("Toggle Only Model", { exact: true }).click();
      await setThinking(true);
      await expect(settings.getByRole("switch")).toHaveAttribute("aria-disabled", "false");
      await expect(settings.getByText("思考强度", { exact: true })).toHaveCount(0);
      await expect(settings.getByRole("combobox")).toHaveCount(0);
      await expect(settings.getByRole("slider")).toHaveCount(0);
      await trigger.click();
      const input = page.getByRole("textbox", { name: "对话输入", exact: true });
      await input.fill("Unsent narrow-layout verification draft");
      for (const width of [679, 390]) {
        await page.setViewportSize({ width, height: 1244 });
        await expect.poll(async () => (await trigger.getByTitle("Toggle Only Model").boundingBox())?.width ?? 0).toBeGreaterThan(16);
        const model = (await trigger.boundingBox())!;
        const sendButton = page.getByRole("button", { name: "发送", exact: true });
        const sendBox = (await sendButton.boundingBox())!;
        const form = (await page.locator("form").filter({ has: trigger }).boundingBox())!;
        expect(model.x).toBeGreaterThanOrEqual(form.x);
        expect(model.x + model.width).toBeLessThanOrEqual(sendBox.x);
        expect(sendBox.x + sendBox.width).toBeLessThanOrEqual(form.x + form.width + 1);
        expect(sendBox.x + sendBox.width).toBeLessThanOrEqual(width);
        await trigger.click();
        await expect(settings).toBeVisible();
        await expect(settings.getByRole("switch")).toHaveAttribute("aria-checked", "true");
        await trigger.click();
        await expect(input).toHaveValue("Unsent narrow-layout verification draft");
      }
      await input.fill("");
      expect(requests).toHaveLength(beforeRequests);
      expect(writes).toHaveLength(beforeWrites);
    });
  });
});
