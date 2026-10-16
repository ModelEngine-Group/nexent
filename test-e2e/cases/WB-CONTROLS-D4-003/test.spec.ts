import { expect, type Locator } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-CONTROLS-D4-003", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1441, height: 1244 });
  await prepareWorkbench(page, 1, { reasoning: true, modelEffort: "medium", agentEffort: "high" });
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
    expect(body.generation_config ?? {}).not.toHaveProperty("temperature");
    expect(body.generation_config ?? {}).not.toHaveProperty("top_p");
    expect(body.workbench?.generation_config ?? {}).not.toHaveProperty(
      "temperature",
    );
    expect(body.workbench?.generation_config ?? {}).not.toHaveProperty("top_p");
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
    await temperature.fill("73");
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
});
