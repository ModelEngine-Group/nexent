// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { readFile } from "node:fs/promises";
import { expect, test } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

test.use({ viewport: { width: 1440, height: 1100 } });

const file_ref = { knowledge_id: 7, file_id: "a".repeat(32), file_version: 2 };
const image_ref = {
  space: "files",
  key: "kb/image.png",
  version: "v1",
  sha256: "b".repeat(64),
};
const source = {
  file_ref,
  url: "",
  title: "report.txt",
  filename: "report.txt",
  source_type: "file",
  cite_index: 1,
  tool_sign: "a",
  text: "Knowledge reference browser proof",
  location: { page: 2 },
};
const image = {
  ...source,
  image_ref,
  cite_index: 2,
  score_details: { chunk_type: "image" },
};
const rejected = {
  ...image,
  cite_index: 3,
  image_ref: { ...image_ref, key: "kb/rejected.png" },
};
const pictures = {
  images_url: [],
  images_ref: [{ file_ref, image_ref, cite_index: 2, tool_sign: "a" }],
};
const bytes = "Knowledge reference browser proof\n";
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4xkAAAAASUVORK5CYII=",
  "base64",
);

journey("DPR-SOURCE-CONSUMER-D4-001", async ({ page, contract }) => {
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: process.env.NEXENT_BASE_URL!,
    },
  ]);
  const row = {
    conversation_id: 123,
    conversation_title: "Knowledge source check",
    agent_id: 7,
    create_time: Date.now(),
    update_time: Date.now(),
  };
  const state = await prepareWorkbench(page, 1, { histories: [row] });
  let saved: object[] = [];
  let runs = 0;
  let denied = false;
  const contentReads: Record<string, unknown>[] = [];
  const forbiddenReads: string[] = [];
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !/403 \(Forbidden\)|Failed to download citation file/.test(message.text())
    )
      browserErrors.push(message.text());
  });
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (/\/api\/(?:file\/download|tasks|image)(?:\/|$)/.test(path))
      forbiddenReads.push(path);
  });
  await page.route("**/api/conversation/agent_groups**", (route) =>
    route.fulfill({
      json: {
        code: 0,
        data: {
          items: new URL(route.request().url()).pathname.endsWith(
            "/conversations",
          )
            ? [row]
            : [],
          pinned_items: [],
          included_items: [],
          next_cursor: null,
        },
      },
    }),
  );
  await page.route("**/api/conversation/123", (route) =>
    route.fulfill({ json: { code: 0, data: [{ ...row, message: saved }] } }),
  );
  await page.route("**/api/file/knowledge/content", (route) => {
    const body = route.request().postDataJSON();
    contentReads.push(body);
    expect(route.request().method()).toBe("POST");
    const { image_ref: requestedImage, ...file } = body;
    expect(file).toEqual(file_ref);
    if (requestedImage) {
      expect(requestedImage).toEqual(image_ref);
      return route.fulfill({ contentType: "image/png", body: png });
    }
    return denied
      ? route.fulfill({ status: 403, json: { detail: { code: "forbidden" } } })
      : route.fulfill({ contentType: "text/plain", body: bytes });
  });
  await page.route("**/api/agent/run", (route) => {
    runs++;
    saved = [
      {
        role: "user",
        message_id: 1,
        message: "Find the report",
        status: "completed",
      },
      {
        role: "assistant",
        message_id: 2,
        status: "completed",
        search: [source, image, rejected],
        message: [
          {
            type: "picture_web",
            content: JSON.stringify(pictures),
            unit_index: 0,
          },
          {
            type: "final_answer",
            content: "Knowledge answer [a1]",
            unit_index: 1,
          },
        ],
      },
    ];
    const events = [
      {
        type: "search_content",
        content: JSON.stringify([source, image, rejected]),
      },
      { type: "picture_web", content: JSON.stringify(pictures) },
      { type: "final_answer", content: "Knowledge answer [a1]" },
      { type: "complete", content: "" },
    ];
    return route.fulfill({
      contentType: "text/event-stream",
      headers: { conversation_id: "123" },
      body: events
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join(""),
    });
  });
  const panel = page.locator('[data-slot="sources-panel"]');
  const picture = page.getByRole("img", { name: "a2", exact: true });
  const assertImage = async () => {
    await expect(picture).toBeVisible();
    await expect
      .poll(() =>
        picture.evaluate(
          (element) => (element as HTMLImageElement).naturalWidth,
        ),
      )
      .toBe(1);
  };
  const openSources = async () => {
    await page.locator(".aui-source-group-button").last().click();
    await expect(panel).toBeVisible();
    await expect(page.locator(".aui-source-group-button")).toHaveCount(1);
  };
  const results = [false, false, false, false];
  contract.deferCleanup(async () => {
    await page.goto("about:blank");
    await page.unrouteAll({ behavior: "wait" });
    await page.context().clearCookies();
  });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto(
        `${process.env.NEXENT_BASE_URL}/en/newchat?conversation_id=123`,
      );
      await expect(
        page.getByRole("textbox", { name: "Message input", exact: true }),
      ).toBeEnabled();
      expect(runs).toBe(0);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await page
      .getByRole("textbox", { name: "Message input", exact: true })
      .fill("Find the report");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(
      page.getByText("Knowledge answer", { exact: false }).first(),
    ).toBeVisible();
    await assertImage();
    expect(runs).toBe(1);
    results[0] = true;
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await openSources();
    await expect(page.locator(".aui-source-group-button")).toHaveCount(1);
    const downloadPromise = page.waitForEvent("download");
    await panel
      .getByRole("button", { name: "Download report.txt", exact: true })
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("report.txt");
    expect(await readFile((await download.path())!, "utf8")).toBe(bytes);
    await panel
      .getByRole("button", { name: "Preview report.txt", exact: true })
      .click();
    const preview = page.getByRole("dialog");
    await expect(
      preview.getByText(bytes.trim(), { exact: true }),
    ).toBeVisible();
    await preview.getByRole("button", { name: "Close", exact: true }).click();
    await expect(preview).not.toBeVisible();
    results[1] = true;
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await page.reload();
    await assertImage();
    await openSources();
    await expect(
      panel.getByRole("button", { name: "Download report.txt", exact: true }),
    ).toBeEnabled();
    expect(runs).toBe(1);
    results[2] = true;
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    denied = true;
    const before = contentReads.length;
    await panel
      .getByRole("button", { name: "Download report.txt", exact: true })
      .click();
    await expect(
      panel.getByText("Download failed. Please try again.", { exact: true }),
    ).toBeVisible();
    expect(contentReads.length - before).toBe(1);
    results[3] = true;
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      expect(results).toEqual([true, true, true, true]);
      expect(forbiddenReads).toEqual([]);
      expect(state.writes).toEqual([]);
      expect(browserErrors).toEqual([]);
      expect(runs).toBe(1);
      expect(
        contentReads.every(
          (body) =>
            !body.image_ref ||
            (body.image_ref as typeof image_ref).key === image_ref.key,
        ),
      ).toBe(true);
    });
});
