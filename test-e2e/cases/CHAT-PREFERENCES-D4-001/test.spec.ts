// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import {
  prepareControls,
  trigger,
  openControls,
  settings,
} from "../../infra/automation/d4/fixtures/model-controls";

journey("CHAT-PREFERENCES-D4-001", async ({ page, contract }) => {
  const entries = [];
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
  await page
    .context()
    .addCookies([
      {
        name: "nexent_token_expires_at",
        value: String(Math.floor(Date.now() / 1000) + 3600),
        url: base,
      },
    ]);
  for (const locale of ["zh", "en"]) {
    const target = locale === "zh" ? page : await page.context().newPage();
    if (target !== page) contract.deferCleanup(() => target.close());
    const state = await prepareControls(target);
    Object.assign(state.draft, {
      model_params_override: {
        "1": {
          extra_params: { enable_thinking: true, reasoning_effort: "auto" },
        },
      },
    });
    const values: Record<string, unknown> = {};
    const writes: Array<Record<string, unknown>> = [];
    let reject = false;
    await target.route(
      /\/api\/conversation\/agent_groups(?:\/[^?]+)?(?:\?|$)/,
      (route) =>
        route.fulfill({
          json: {
            code: 0,
            data: {
              items: [],
              pinned_items: [],
              included_items: [],
              next_cursor: null,
            },
          },
        }),
    );
    await target.route(
      /\/api\/conversation\/93(?:\/model_preferences(?:\/1)?)?(?:\?|$)/,
      async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path === "/api/conversation/93")
          return route.fulfill({
            json: {
              code: 0,
              data: [
                {
                  conversation_id: 93,
                  agent_id: 42,
                  conversation_title: "Saved preferences",
                  message: [],
                },
              ],
            },
          });
        if (path.endsWith("/model_preferences"))
          return route.fulfill({
            json: {
              code: 0,
              data: {
                selected_model_id: 1,
                model_parameter_preferences: { "1": values },
              },
            },
          });
        if (route.request().method() === "PATCH") {
          const patch = route.request().postDataJSON();
          writes.push(patch);
          if (reject) {
            const field = Object.hasOwn(patch.parameter_values, "temperature")
              ? "temperature"
              : "reasoning_effort";
            return route.fulfill({
              status: 422,
              json: {
                detail: {
                  code:
                    field === "temperature"
                      ? "FIXED_PARAMETER"
                      : "PARAMETER_DEPENDENCY",
                  field: `/${field}`,
                },
              },
            });
          }
          Object.assign(values, patch.parameter_values);
          for (const key of patch.delete_parameters) delete values[key];
        }
        const rule = (key: string, schema: Record<string, unknown>) => ({
          key,
          schema,
          visible: true,
          editable: true,
          required: false,
          allowed_scopes: ["conversation"],
        });
        await route.fulfill({
          json: {
            code: 0,
            data: {
              config_revision: 10,
              parameter_values: values,
              defaults: { enable_thinking: false, temperature: 0.4 },
              issues: [],
              reasoning_status: "supported",
              field_specs: [
                rule("enable_thinking", { type: "boolean" }),
                rule("temperature", { type: "number", minimum: 0, maximum: 2 }),
                {
                  ...rule("reasoning_effort", {
                    type: "string",
                    enum: ["low", "medium", "high"],
                  }),
                  condition: { key: "enable_thinking", op: "eq", value: true },
                },
              ],
            },
          },
        });
      },
    );
    entries.push({
      target,
      locale,
      values,
      writes,
      reject: () => {
        reject = true;
      },
      state,
    });
  }
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      for (const { target, locale } of entries) {
        await target.goto(`${base}/${locale}/newchat?conversation_id=93`);
        await expect(trigger(target)).toBeVisible();
        await expect(trigger(target)).toContainText("Default A");
      }
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const { target, writes, values } of entries) {
      await openControls(target);
      const toggle = settings(target).getByRole("switch");
      await expect(toggle).not.toBeChecked();
      await expect(settings(target).getByRole("combobox")).toHaveCount(0);
      expect(writes).toEqual([]);
      await toggle.click();
      await expect
        .poll(() => values)
        .toEqual({ enable_thinking: true, reasoning_effort: "low" });
      expect(writes).toEqual([
        {
          parameter_values: { enable_thinking: true, reasoning_effort: "low" },
          delete_parameters: [],
        },
      ]);
      await target.keyboard.press("Escape");
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    for (const { target, locale, values, reject } of entries) {
      reject();
      await openControls(target);
      await settings(target).getByRole("combobox").click();
      await target
        .getByText(locale === "zh" ? "高" : "High", { exact: true })
        .last()
        .click();
      await expect(
        target
          .getByText(
            locale === "zh" ? /依赖其他参数/ : /depends on other parameters/,
          )
          .first(),
      ).toBeVisible();
      await settings(target)
        .getByRole("button", {
          name: locale === "zh" ? "高级设置" : "Advanced settings",
          exact: true,
        })
        .click();
      const temperature = target.getByRole("spinbutton", {
        name: locale === "zh" ? "温度" : "Temperature",
        exact: true,
      });
      await expect(temperature).toHaveValue("0.4");
      await temperature.fill("0.7");
      await temperature.press("Tab");
      await expect(
        target
          .getByText(locale === "zh" ? /固定/ : /cannot be overridden/)
          .first(),
      ).toBeVisible();
      expect(values).toEqual({
        enable_thinking: true,
        reasoning_effort: "low",
      });
      await target.screenshot({
        path: `${contract.caseDir}/${locale}-validation.png`,
      });
      await target.keyboard.press("Escape");
    }
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const { target, locale, values } of entries) {
      await target.reload();
      await expect(trigger(target)).toContainText(
        locale === "zh" ? "低" : "Low",
      );
      await openControls(target);
      await expect(settings(target).getByRole("switch")).toBeChecked();
      expect(values).toEqual({
        enable_thinking: true,
        reasoning_effort: "low",
      });
    }
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      for (const { state, writes, values } of entries) {
        expect(state.requests).toEqual([]);
        expect(writes).toHaveLength(3);
        expect(values).toEqual({
          enable_thinking: true,
          reasoning_effort: "low",
        });
        expect(
          writes.every((write) => !JSON.stringify(write).includes("auto")),
        ).toBe(true);
      }
    });
});
