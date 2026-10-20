// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";
journey("WB-CONTROLS-D4-005", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1174, height: 1188 });
  const state = await prepareWorkbench(page, 11, { longDescriptions: true });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(page.locator("[data-workbench-composer]")).toBeVisible();
    },
  );
  const drawer = page.getByRole("dialog");
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const name of ["智能体", "知识库", "技能"]) {
      await expect(page.getByRole("button", { name, exact: true })).toHaveText(
        name,
      );
      await page.getByRole("button", { name, exact: true }).click();
      await expect(drawer).toBeVisible();
      for (const part of [
        "search",
        "selection",
        "list-heading",
        "list-content",
        "pagination",
      ]) {
        await expect(
          drawer.locator(`[data-picker-part="${part}"]`),
        ).toBeVisible();
      }
      await expect(
        drawer.getByRole("button", { name: "管理标签", exact: true }),
      ).toHaveCount(0);
      await expect(
        drawer.getByRole("button", { name: "本地智能体", exact: true }),
      ).toHaveCount(0);
      await expect(
        drawer.getByRole("button", { name: "官方", exact: true }),
      ).toHaveCount(0);
      await expect(
        drawer.getByRole("button", { name: "自定义", exact: true }),
      ).toHaveCount(0);
      await expect(
        drawer.getByRole("button", { name: "外部智能体", exact: true }),
      ).toHaveCount(0);
      if (name !== "知识库")
        await expect(drawer.getByRole("tab")).toHaveCount(2);

      await expect
        .poll(async () => {
          const bounds = await page
            .locator(".ant-drawer-content-wrapper:visible")
            .boundingBox();
          return Math.round(bounds!.x + bounds!.width);
        })
        .toBe(page.viewportSize()!.width);
      const searchRow = drawer.locator('[data-picker-part="search"]');
      const searchBox = await searchRow.getByRole("searchbox").boundingBox();
      const tagButton = await searchRow
        .getByRole("button", { name: "标签筛选", exact: true })
        .boundingBox();
      expect(
        Math.abs(
          searchBox!.y +
            searchBox!.height / 2 -
            tagButton!.y -
            tagButton!.height / 2,
        ),
      ).toBeLessThanOrEqual(1);
      expect(searchBox!.x + searchBox!.width).toBeLessThan(tagButton!.x);
      const list = drawer.locator("[data-resource-list]");
      const pager = drawer.locator("[data-resource-pagination]");
      const confirm = drawer.getByRole("button", {
        name: "确认",
        exact: true,
      });
      const footer = drawer.locator('[data-picker-part="footer"]');
      await expect(footer.getByRole("button")).toHaveText(["关闭", "确认"]);
      await expect(
        drawer.getByRole("button", { name: /检索设置|恢复默认/ }),
      ).toHaveCount(0);

      const verifyLayout = async () => {
        await expect(list).toHaveCSS("overflow-y", "auto");
        await expect
          .poll(async () => {
            const l = (await list.boundingBox())!,
              p = (await pager.boundingBox())!;
            return Math.round(p.y - l.y - l.height);
          })
          .toBe(16);
        await expect
          .poll(async () => {
            const p = (await pager.boundingBox())!,
              c = (await confirm.boundingBox())!;
            return Math.round(c.y - p.y - p.height);
          })
          .toBe(16);
        expect((await list.boundingBox())!.height).toBeGreaterThan(80);
      };
      await verifyLayout();
      await expect(
        list.getByRole("button", { name: "编辑", exact: true }),
      ).toHaveCount(0);
      if (name === "智能体") {
        await expect(list.locator("[data-resource-agent-card]")).toHaveCount(
          10,
        );
        await expect(list.locator(".ant-avatar")).toHaveCount(10);
        await expect(list.getByRole("option").first()).toContainText("版本");
      } else {
        await expect(
          list.locator(
            ".lucide-bot,.lucide-book-open,.lucide-layers,.lucide-zap",
          ),
        ).toHaveCount(0);
      }
      const header = drawer.locator('[data-picker-part="list-heading"]');
      const selectAll = header.getByRole("checkbox", {
        name: "全选",
        exact: true,
      });
      const refresh = header.getByRole("button", { name: "刷新", exact: true });
      await expect(selectAll).toBeEnabled();
      await list.getByRole("option").first().click();
      await expect(selectAll).toHaveAttribute("aria-checked", "mixed");
      await refresh.click();
      await expect(list.getByRole("option").first()).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await expect(selectAll).toBeEnabled();
      if (name === "智能体") {
        await selectAll.click();
        await expect(
          page.getByText("最多选择 8 个智能体", { exact: true }),
        ).toBeVisible();
        await expect(selectAll).toHaveAttribute("aria-checked", "mixed");
        await searchRow.getByRole("searchbox").fill("Internal Analyst 10");
        await selectAll.click();
        await expect(selectAll).toHaveAttribute("aria-checked", "true");
        await expect(list.getByRole("option")).toHaveCount(1);
        await selectAll.click();
        await expect(selectAll).toHaveAttribute("aria-checked", "false");
        await searchRow.getByRole("searchbox").fill("");
        await expect(list.getByRole("option").first()).toHaveAttribute(
          "aria-selected",
          "true",
        );
        await list.getByRole("option").first().click();
        await expect(selectAll).toHaveAttribute("aria-checked", "false");
      } else {
        await selectAll.click();
        await expect(selectAll).toHaveAttribute("aria-checked", "true");
        expect(
          await list
            .getByRole("option")
            .evaluateAll((items) =>
              items.every(
                (item) => item.getAttribute("aria-selected") === "true",
              ),
            ),
        ).toBe(true);
        await selectAll.click();
        await expect(selectAll).toHaveAttribute("aria-checked", "false");
        expect(
          await list
            .getByRole("option")
            .evaluateAll((items) =>
              items.every(
                (item) => item.getAttribute("aria-selected") === "false",
              ),
            ),
        ).toBe(true);
      }
      if (name === "知识库") {
        await expect(list.getByRole("option").first()).toContainText(
          "向量模型",
        );
        await expect(list.getByRole("option").first()).toContainText(/\d+文档/);
        await expect(list.getByRole("option").first()).toContainText("nexent");
      }
      const [rowA, rowB] = await list
        .getByRole("option")
        .evaluateAll((elements) =>
          elements.slice(0, 2).map((el) => {
            const r = el.getBoundingClientRect();
            return { x: r.x, y: r.y, height: r.height, width: r.width };
          }),
        );
      expect(Math.abs(rowA.width - rowB.width)).toBeLessThanOrEqual(1);
      if (name === "智能体") {
        expect(Math.abs(rowA.y - rowB.y)).toBeLessThanOrEqual(1);
        expect(rowB.x).toBeGreaterThanOrEqual(rowA.x + rowA.width);
        expect(rowA.height).toBeGreaterThanOrEqual(148);
      } else {
        expect(Math.abs(rowA.x - rowB.x)).toBeLessThanOrEqual(1);
        expect(rowA.height).toBeLessThan(120);
        expect(rowB.y).toBeGreaterThanOrEqual(rowA.y + rowA.height);
      }
      await pager.getByRole("button", { name: "2", exact: true }).click();
      await expect(list.getByRole("option")).toHaveCount(1);
      await verifyLayout();
      await pager.getByRole("button", { name: "1", exact: true }).click();
      await expect(list.getByRole("option")).toHaveCount(10);
      for (const [size, count] of [
        [20, 11],
        [50, 11],
        [10, 10],
      ]) {
        await pager.getByRole("combobox").click();
        await expect(
          page.locator(
            ".ant-select-dropdown:visible .ant-select-item-option-content",
          ),
        ).toHaveText(["10 条/页", "20 条/页", "50 条/页"]);
        await page
          .locator(
            ".ant-select-dropdown:visible .ant-select-item-option-content",
          )
          .filter({ hasText: new RegExp(`^${size} `) })
          .click();
        await expect(list.getByRole("option")).toHaveCount(count);
        await verifyLayout();
      }
      const pagerY = (await pager.boundingBox())!.y;
      await searchRow
        .getByRole("searchbox")
        .fill("no-such-resource-layout-check");
      await expect(list.getByRole("option")).toHaveCount(0);
      await verifyLayout();
      expect(
        Math.abs((await pager.boundingBox())!.y - pagerY),
      ).toBeLessThanOrEqual(1);
      await searchRow.getByRole("searchbox").fill("");
      if (name !== "知识库") {
        await drawer.getByRole("tab", { name: "仓库", exact: true }).click();
        await expect(list.getByRole("option")).toHaveCount(0);
        await verifyLayout();
        expect(
          Math.abs((await pager.boundingBox())!.y - pagerY),
        ).toBeLessThanOrEqual(1);
        await drawer.getByRole("tab", { name: "我的", exact: true }).click();
      }
      await page.setViewportSize({ width: 1174, height: 650 });
      await verifyLayout();
      const smallPagerY = (await pager.boundingBox())!.y;
      const searchY = (await searchRow.boundingBox())!.y;
      await expect(list.getByRole("option")).toHaveCount(10);
      await expect
        .poll(() => list.evaluate((el) => el.scrollHeight > el.clientHeight))
        .toBe(true);
      await list.evaluate((el) => {
        el.scrollTop = el.scrollHeight;
      });
      expect(await list.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
      expect(
        Math.abs((await pager.boundingBox())!.y - smallPagerY),
      ).toBeLessThanOrEqual(1);
      expect(
        Math.abs((await searchRow.boundingBox())!.y - searchY),
      ).toBeLessThanOrEqual(1);
      await page.setViewportSize({ width: 1174, height: 1188 });
      await verifyLayout();
      await drawer
        .getByRole("button", { name: "标签筛选", exact: true })
        .click();
      await expect(
        page
          .locator(".ant-popover:visible")
          .getByText("Business", { exact: true })
          .first(),
      ).toBeVisible();
      await drawer
        .getByRole("button", { name: "标签筛选", exact: true })
        .click();
      await drawer
        .locator('[data-picker-part="footer"]')
        .getByRole("button", { name: "关闭", exact: true })
        .click();
      await expect(drawer).toHaveCount(0);
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await contract.assertion(
      contract.expectedIds("assertions")[0],
      async () => {
        await page.getByRole("button", { name: "智能体", exact: true }).click();
        await drawer
          .getByRole("option", { name: "Internal Analyst", exact: true })
          .click();
        await drawer
          .locator('[data-picker-part="footer"]')
          .getByRole("button", { name: "关闭", exact: true })
          .click();
        await expect(
          page.getByRole("button", {
            name: "Agent · Internal Analyst",
            exact: true,
          }),
        ).toHaveCount(0);
        await page.getByRole("button", { name: "智能体", exact: true }).click();
        await expect(
          drawer.getByRole("button", { name: "编辑", exact: true }),
        ).toHaveCount(0);
        const [first, second] = await drawer
          .getByRole("option")
          .evaluateAll((elements) =>
            elements.slice(0, 2).map((el) => {
              const r = el.getBoundingClientRect();
              return { x: r.x, y: r.y, height: r.height, width: r.width };
            }),
          );
        expect(first.height).toBeGreaterThanOrEqual(148);
        expect(Math.abs(first.y - second.y)).toBeLessThanOrEqual(1);
        expect(second.x).toBeGreaterThanOrEqual(first.x + first.width);
        await expect(
          drawer.getByRole("option", { name: "Internal Analyst", exact: true }),
        ).toHaveAttribute("aria-selected", "false");
        await drawer
          .getByRole("option", { name: "Internal Analyst", exact: true })
          .click();
        await drawer
          .getByRole("button", { name: "标签筛选", exact: true })
          .click();
        await page
          .locator(".ant-popover:visible")
          .getByRole("combobox")
          .last()
          .click();
        await page
          .locator(".ant-select-dropdown:visible")
          .getByText("Finance", { exact: true })
          .click();
        await expect.poll(() => state.filters.length).toBeGreaterThan(0);
        await expect
          .poll(async () => {
            const values = await page
              .locator(".ant-popover:visible .ant-select")
              .last()
              .boundingBox();
            const options = await page
              .locator(".ant-select-dropdown:visible")
              .boundingBox();
            return options!.y - values!.y - values!.height;
          })
          .toBeGreaterThanOrEqual(-1);
        expect(state.filters[0].resource_ids).toEqual([
          "7",
          "8",
          "9",
          "10",
          "11",
          "12",
          "13",
          "14",
          "15",
          "16",
          "17",
        ]);
        await expect(
          drawer.getByRole("option", { name: "Internal Analyst", exact: true }),
        ).toHaveAttribute("aria-selected", "true");
        await drawer.getByRole("tab", { name: "仓库", exact: true }).click();
        await expect(
          drawer.getByRole("tab", { name: "我的", exact: true }),
        ).toBeVisible();
        await drawer.getByRole("tab", { name: "我的", exact: true }).click();
        await drawer.getByRole("button", { name: "确认", exact: true }).click();
        await expect(drawer).toHaveCount(0);
        await expect(
          page.getByRole("button", { name: "智能体", exact: true }),
        ).toHaveText("智能体");
        await expect(
          page.getByRole("button", {
            name: "Agent · Internal Analyst",
            exact: true,
          }),
        ).toBeVisible();
        await page.getByRole("button", { name: "技能", exact: true }).click();
        await expect(
          drawer.getByRole("option", { name: "Invoice Skill", exact: true }),
        ).toBeVisible();
        await drawer.getByRole("tab", { name: "仓库", exact: true }).click();
        await expect(
          drawer.getByRole("tab", { name: "我的", exact: true }),
        ).toBeVisible();
        await drawer
          .locator('[data-picker-part="footer"]')
          .getByRole("button", { name: "关闭", exact: true })
          .click();
        await expect(drawer).toHaveCount(0);
        await page.setViewportSize({ width: 760, height: 900 });
        await page.getByRole("button", { name: "知识库", exact: true }).click();
        await expect(
          drawer.getByRole("option", { name: "Company Docs", exact: true }),
        ).toBeVisible();
        const width = await drawer.evaluate(
          (el) => el.getBoundingClientRect().width,
        );
        expect(Math.round(width)).toBeLessThanOrEqual(760);
        await drawer
          .locator('[data-picker-part="footer"]')
          .getByRole("button", { name: "关闭", exact: true })
          .click();
      },
    );
    expect(state.writes).toEqual([]);
    await expect(page.getByText("A2A", { exact: true })).toHaveCount(0);
  });
});
