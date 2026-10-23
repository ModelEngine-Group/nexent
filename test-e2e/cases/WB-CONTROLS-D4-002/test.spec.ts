// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-CONTROLS-D4-002", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1174, height: 1188 });
  const history = {conversation_id:91,conversation_title:"Saved parameter reset",agent_id:null,create_time:Date.now(),update_time:Date.now()};
  const state = await prepareWorkbench(page, 1, {histories:[history],samplingDefaults:{temperature:0.6,top_p:0.85},agentSamplingDefaults:{temperature:0.45}});
  const input = page.locator("[data-workbench-composer]");
  const expectAligned = async (panel: ReturnType<typeof page.getByRole>) => {
    for (const label of ["温度", "Top P"]) {
      const numeric = panel.getByRole("spinbutton", {name:label,exact:true});
      const rail = numeric.locator("..").locator(".ant-slider-rail");
      await expect.poll(async () => {
        const a = await numeric.boundingBox(), b = await rail.boundingBox();
        if (!a || !b) return Number.POSITIVE_INFINITY;
        return Math.abs(a.y + a.height / 2 - b.y - b.height / 2);
      }).toBeLessThanOrEqual(1);
    }
  };

  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await expect(input).toBeVisible();
    await expect(page.getByText("Fixture Model", { exact: true })).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await input.fill("Ordinary conversation draft");
    const initialInputY = (await input.boundingBox())!.y;
    const composer = page.locator("fieldset").filter({ has: input });
    const initialComposerY = (await composer.boundingBox())!.y;
    const expectPosition = async () => {
      await expect.poll(async () => Math.abs((await input.boundingBox())!.y - initialInputY)).toBeLessThanOrEqual(1);
      await expect.poll(async () => Math.abs((await composer.boundingBox())!.y - initialComposerY)).toBeLessThanOrEqual(1);
    };
    for (const [mode, example] of [["智能体创建", "文档资料整理助手"], ["技能创建", "发票信息提取"]]) {
      const button = page.getByRole("button", { name: mode, exact: true });
      const a = await button.boundingBox(), b = await input.boundingBox();
      expect(a!.y).toBeLessThan(b!.y);
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
      await expect(input).toHaveValue("");
      await expect(page.getByRole("button", { name: "返回普通对话", exact: true })).toHaveCount(0);
      await expectPosition();
      await page.getByRole("button", { name: new RegExp(example) }).click();
      await expect(input).not.toHaveValue("");
      await expectPosition();
      await expect(page.locator("[data-workbench-composer]")).toBeVisible();
      await button.click();
      await expect(input).toHaveValue("Ordinary conversation draft");
      await expectPosition();
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await contract.assertion(contract.expectedIds("assertions")[0], async () => {
      await page.getByText("Fixture Model", { exact: true }).click();
      const advanced = page.getByRole("button", { name: "高级设置", exact: true });
      await expect(advanced).toBeVisible();
      const panel = page.getByRole("region", { name: "高级设置", exact: true });
      await expect(page.getByRole("switch", { name: "深度思考" })).toBeDisabled();
      await expect(advanced).toBeFocused();
      await expect(advanced).toHaveAttribute("aria-expanded", "false");
      await expect(panel).not.toBeVisible();
      await advanced.focus();
      await expect(panel).not.toBeVisible();
      await expect(advanced.locator(".lucide-settings")).toHaveCount(0);
      await expect.poll(async () => {
        const advancedLabel = await advanced.getByText("高级设置", { exact: true }).boundingBox();
        const thinkingLabel = await page.getByText("深度思考", { exact: true }).boundingBox();
        return Math.abs(advancedLabel!.x - thinkingLabel!.x);
      }).toBeLessThanOrEqual(1);
      const effort = page.getByText("思考强度", { exact: true });
      await expect(effort).toHaveCount(0);
      expect((await advanced.boundingBox())!.y).toBeGreaterThan((await page.getByText("深度思考", {exact:true}).boundingBox())!.y);
      await advanced.hover();
      const temperature = panel.getByRole("spinbutton", { name: "温度", exact: true });
      await expect(temperature).toHaveValue("0.6");
      await expectAligned(panel);
      const slider = panel.getByRole("slider", { name: "温度 滑块", exact: true });
      await slider.focus();
      await slider.hover();
      const handle = await slider.boundingBox();
      await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2);
      await page.mouse.down(); await page.mouse.move(handle!.x + 24, handle!.y + handle!.height / 2, { steps: 6 }); await page.mouse.up();
      await expect(temperature).not.toHaveValue("");
      await temperature.fill("2"); await temperature.press("Enter");
      await expect(slider).toHaveAttribute("aria-valuenow", "2");
      const topP = panel.getByRole("spinbutton", { name: "Top P", exact: true });
      await topP.fill("1"); await topP.press("Enter");
      for (const invalid of ["-0.1", "2.1", ""]) {
        await temperature.fill(invalid); await temperature.press("Enter");
        await expect(temperature).toHaveAttribute("aria-invalid", "true");
        await expect(panel.getByRole("alert")).toHaveText("请输入 0–2 的数字");
      }
      await panel.getByRole("button", { name: "恢复默认", exact: true }).click();
      await expect(temperature).toHaveValue("0.6"); await expect(topP).toHaveValue("0.85");
      await expectAligned(panel);
      await expect(input).toHaveValue("Ordinary conversation draft");
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/newchat`);
      await expect(page).toHaveURL(/\/zh\/newchat/);
      await page.getByRole("button", { name: /Internal Analyst/ }).first().click();
      await expect(page.getByText("Fixture Model", { exact: true })).toBeVisible();
      const writesBeforeParameters = [...state.writes];
      await page.getByText("Fixture Model", { exact: true }).click();
      const sharedAdvanced = page.getByRole("button", { name: "高级设置", exact: true });
      await expect(sharedAdvanced).toBeVisible();
      const sharedPanel = page.getByRole("region", { name: "高级设置", exact: true });
      await expect(sharedAdvanced).toBeFocused();
      await expect(sharedAdvanced).toHaveAttribute("aria-expanded", "false");
      await expect(sharedPanel).not.toBeVisible();
      await sharedAdvanced.focus();
      await expect(sharedPanel).not.toBeVisible();
      await expect(page.getByText("深度思考", { exact: true })).toBeVisible();
      await expect(page.getByText("思考强度", { exact: true })).toHaveCount(0);
      await sharedAdvanced.press("ArrowRight");
      await expect(sharedPanel).toBeVisible();
      const sharedTemperature = sharedPanel.getByRole("spinbutton", { name: "温度", exact: true });
      await expect(sharedTemperature).toHaveValue("0.45");
      await expectAligned(sharedPanel);
      await expect(sharedPanel.getByRole("slider",{name:"温度 滑块"})).toHaveAttribute("aria-valuenow","0.45");
      await sharedTemperature.fill("0.7"); await sharedTemperature.press("Enter");
      await expect(sharedPanel.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute("aria-valuenow", "0.7");
      const sharedTopP = sharedPanel.getByRole("spinbutton", { name: "Top P", exact: true });
      await sharedTopP.fill("0.4"); await sharedTopP.press("Enter");
      await expect(sharedPanel.getByRole("slider", { name: "Top P 滑块" })).toHaveAttribute("aria-valuenow", "0.4");
      await sharedPanel.getByRole("button", { name: "恢复默认", exact: true }).click();
      await expect(sharedTemperature).toHaveValue("0.45"); await expect(sharedTopP).toHaveValue("0.85");
      await expectAligned(sharedPanel);
      expect(state.writes).toEqual(writesBeforeParameters);
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/workbench`);
      await expect(input).toBeVisible();
    });
    expect(state.writes).toEqual([]);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const permissions of [[], ["agent:create"], ["skill:create"], ["agent:create", "skill:create"]]) {
      state.authorization.permissions = permissions;
      await page.reload();
      await expect(input).toBeVisible();
      await expect(page.getByText("Fixture Model", { exact: true })).toBeVisible();
      for (const [permission, label] of [["agent:create", "智能体创建"], ["skill:create", "技能创建"]]) {
        const button = page.getByRole("button", { name: label, exact: true });
        if (permissions.includes(permission)) {
          await expect(button).toBeVisible();
          await button.click();
          await expect(button).toHaveAttribute("aria-pressed", "true");
          await button.click();
          await expect(button).toHaveAttribute("aria-pressed", "false");
        } else {
          await expect(button).toHaveCount(0);
        }
      }
    }
    expect(state.writes).toEqual([]);
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    let config = {schema_version:3,mode:"generic_chat",model_id:1,generation_config:{deep_thinking:false,thinking_effort:"auto",requested_output_tokens:2048,temperature:0.7,top_p:0.4},agent_mounts:[],skill_mounts:[]};
    let version = 1;
    let reads = 0;
    const patches: Array<{config:typeof config;expected_version:number}> = [];
    await page.route("**/api/conversation/91", async route => {
      reads++;
      await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({code:0,data:[{...history,message:[
        {role:"user",message:"Saved fixture question",message_id:101,message_index:0,status:"completed"},
        {role:"assistant",message:[{type:"final_answer",content:"Saved reply remains mounted"}],message_id:102,message_index:1,status:"completed"},
      ],workbench_config:config,workbench_config_version:version}]})});
    });
    await page.route("**/api/conversation/91/workbench-config", async route => {
      patches.push(route.request().postDataJSON());
      await new Promise(resolve=>setTimeout(resolve,500));
      config=patches.at(-1)!.config;
      version++;
      await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify({code:0,data:{workbench_config:config,workbench_config_version:version}})});
    });
    await page.getByRole("button").filter({has:page.getByText("Saved parameter reset",{exact:true})}).click();
    await expect(page.getByText("Saved reply remains mounted",{exact:true})).toBeVisible();
    await expect(page.locator('[data-slot="model-selector-trigger"]')).toBeEnabled();
    await input.fill("Unsent reset regression draft");
    const assistant = await page.locator('[data-slot="aui_assistant-message-root"]').elementHandle();
    const composer = await input.elementHandle();
    const url = page.url();
    const navigations: string[]=[];
    const navigation = (frame: import("playwright/test").Frame) => { if(frame===page.mainFrame()) navigations.push(frame.url()); };
    page.on("framenavigated",navigation);
    await page.locator('[data-slot="model-selector-trigger"]').click();
    await page.getByRole("button",{name:"高级设置",exact:true}).hover();
    const panel = page.getByRole("region",{name:"高级设置",exact:true});
    const readsBeforeReset=reads;
    await panel.getByRole("button",{name:"恢复默认",exact:true}).click();
    await expect.poll(()=>patches.length).toBe(1);
    await expect(panel.getByRole("spinbutton",{name:"温度",exact:true})).toBeDisabled();
    expect(await assistant!.evaluate(node=>node.isConnected)).toBe(true);
    expect(await composer!.evaluate(node=>node.isConnected)).toBe(true);
    // Saving temporarily disables/closes the model menu. Deliberately reopen
    // the nested panel rather than depending on the removed autofocus action.
    await expect(page.locator('[data-slot="model-selector-trigger"]')).toBeEnabled();
    await expect(panel).not.toBeVisible();
    const advancedAfterSave = page.getByRole("button",{name:"高级设置",exact:true});
    if (!(await advancedAfterSave.isVisible())) {
      await page.locator('[data-slot="model-selector-trigger"]').click();
    }
    await advancedAfterSave.hover();
    await expect(panel.getByRole("spinbutton",{name:"温度",exact:true})).toHaveValue("0.6");
    await expect(panel.getByRole("spinbutton",{name:"Top P",exact:true})).toHaveValue("0.85");
    await expect(panel.getByRole("spinbutton",{name:"温度",exact:true})).toBeEnabled();
    expect(await assistant!.evaluate(node=>node.isConnected)).toBe(true);
    expect(await composer!.evaluate(node=>node.isConnected)).toBe(true);
    await expect(input).toHaveValue("Unsent reset regression draft");
    expect(page.url()).toBe(url); expect(navigations).toEqual([]); expect(reads).toBe(readsBeforeReset);
    expect(patches[0].expected_version).toBe(1);
    expect(patches[0].config).toMatchObject({model_id:1,mode:"generic_chat",generation_config:{deep_thinking:false,thinking_effort:"auto",requested_output_tokens:2048},agent_mounts:[],skill_mounts:[]});
    expect(patches[0].config.generation_config.temperature ?? null).toBeNull();
    expect(patches[0].config.generation_config.top_p ?? null).toBeNull();
    expect(state.writes).toEqual([]);
    page.off("framenavigated",navigation);
    await assistant!.dispose(); await composer!.dispose();
    await page.screenshot({path:join(process.env.NEXENT_TEST_HOME!,"artifacts","sampling-reset-after.png")});
  });
});
