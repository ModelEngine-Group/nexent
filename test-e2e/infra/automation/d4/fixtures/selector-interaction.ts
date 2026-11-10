// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Locator, type Page } from "playwright/test";

/** Check the rendered control instead of relying on its declared CSS width. */
export async function expectReadableLabel(control: Locator, text: string) {
  const label = control.getByText(text, { exact: true });
  await expect(label).toBeVisible();
  await expect.poll(() => label.evaluate(element => {
    const range = document.createRange();
    range.selectNodeContents(element);
    const textBox = range.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    return textBox.width <= box.width + 1 && element.scrollWidth <= element.clientWidth + 1;
  })).toBe(true);
}

export async function expectWithinViewport(page: Page, region: Locator) {
  await expect(region).toBeVisible();
  await expect.poll(async () => {
    const box = await region.boundingBox();
    const viewport = page.viewportSize();
    return !!box && !!viewport && box.x >= 0 && box.y >= 0 &&
      box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1;
  }).toBe(true);
}

/** Reserve space for the native number spinner as well as input padding. */
export async function expectReadablePlaceholder(input: Locator, text: string) {
  await expect(input).toHaveAttribute("placeholder", text);
  expect(await input.evaluate((element: HTMLInputElement) => {
    const style = getComputedStyle(element);
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d")!;
    context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const available = element.clientWidth - parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight) - 20;
    return context.measureText(element.placeholder).width <= available;
  })).toBe(true);
}
