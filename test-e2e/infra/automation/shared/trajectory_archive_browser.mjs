// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";

/** Generate browser inputs through real product HTTP exchange, then release source resources. */
export function archivePayload() {
  const repo = process.env.NEXENT_REPO || process.cwd();
  const source = `
import sys, tempfile, json, base64
from pathlib import Path
root = Path(sys.argv[1])
for path in (root / 'backend', root / 'sdk'):
    sys.path.insert(0, str(path))
sys.path.append(str(root / 'test-e2e/infra/automation/shared'))
from pytest import MonkeyPatch
from trajectory_exchange import seed, http_app, exported, imported
with tempfile.TemporaryDirectory() as directory:
    patch = MonkeyPatch()
    state = seed(Path(directory).resolve() / 'source')
    with http_app(patch, state) as http:
        raw = exported(http).content
    with http_app(patch) as http:
        result = imported(http, raw)
        assert result.status_code == 200, result.text
        data = result.json()['data']
    other = seed(Path(directory).resolve() / 'other', name_prefix='Replacement')
    with http_app(patch, other) as http:
        other_raw = exported(http).content
    with http_app(patch) as http:
        other_data = imported(http, other_raw).json()['data']
    patch.undo()
    print(json.dumps({'zip': base64.b64encode(raw).decode(), 'data': data,
                      'other_zip': base64.b64encode(other_raw).decode(), 'other_data': other_data}))
`;
  const child = spawnSync(
    process.env.FIXED_TEST_PYTHON || resolve(repo, "backend/.venv/bin/python"),
    ["-c", source, repo],
    { encoding: "utf8", maxBuffer: 16 * 1024 * 1024, timeout: 30000 },
  );
  if (child.status !== 0)
    throw new Error(`Archive fixture failed: ${child.stderr}`);
  return JSON.parse(child.stdout);
}

/** Keep the product page real, with controlled auth/catalog and actual exchange DTOs. */
export async function installArchiveBrowser(page, payload) {
  const base = process.env.NEXENT_BASE_URL || "http://localhost:3000";
  const raw = Buffer.from(payload.zip, "base64");
  const otherRaw = Buffer.from(payload.other_zip, "base64");
  const row = {
    ...payload.data.row,
    root_agent_name: "Source Agent",
    conversation_title: "Archive source",
  };
  const state = {
    imports: 0,
    exports: 0,
    reads: 0,
    writes: [],
    role: "OPS",
    exportFailure: false,
    importFailure: false,
    delayImport: false,
    release: null,
    external: [],
    saved: [],
    deleteFailures: [],
    deleteRequests: [],
  };
  const user = () => ({
    user_id: "archive-admin",
    user_email: "archive@example.test",
    tenant_id: "source",
    user_role: state.role,
    groupIds: [],
    permissions: [],
    accessibleRoutes: state.role === "OPS" ? ["/", "/observability"] : ["/"],
  });
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: new URL(base).origin,
    },
  ]);
  await page.addInitScript(() => {
    localStorage.setItem(
      "user_info",
      JSON.stringify({
        id: "archive-admin",
        email: "archive@example.test",
        tenantId: "source",
        role: "OPS",
      }),
    );
    window.archiveExecuted = false;
  });
  page.on("request", (request) => {
    if (request.url().includes("invalid.example"))
      state.external.push(request.url());
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let data = {};
    if (path.endsWith("/user/current_user_info")) data = { user: user() };
    else if (path.endsWith("/tenant_config/deployment_version")) {
      await route.fulfill({
        json: {
          deployment_version: "full",
          app_version: "fixture",
          status: "success",
        },
      });
      return;
    } else if (path.endsWith("/trajectory/records")) {
      data = {
        items: [row],
        total: 1,
        page: 1,
        page_size: 10,
        query_id: "source-query",
        as_of: "2026-11-18T00:00:00Z",
        summary: {
          conversation_count: 1,
          duration: {
            p50_ms: null,
            p90_ms: null,
            p99_ms: null,
            mean_ms: null,
            sample_count: 0,
          },
          ttft: { p50_ms: null, p90_ms: null, p99_ms: null, sample_count: 0 },
          complete: true,
          coverage: { complete: true },
        },
      };
    } else if (path.endsWith("/export")) {
      state.exports++;
      if (state.exportFailure) {
        await route.fulfill({
          status: 422,
          json: { detail: { code: "invalid_parameters" } },
        });
        return;
      }
      await route.fulfill({
        contentType: "application/zip",
        body: raw,
        headers: { "cache-control": "private,no-store" },
      });
      return;
    } else if (
      path.endsWith("/trajectory/imports") &&
      request.method() === "GET"
    ) {
      const query = new URL(request.url()).searchParams;
      const current = Number(query.get("page") || 1);
      const size = Number(query.get("page_size") || 20);
      const field = query.get("sort_by") || "imported_at";
      const sign = query.get("sort_order") === "asc" ? 1 : -1;
      const entries = [...state.saved].sort((left, right) => {
        const a =
          field === "filename"
            ? left.item.filename.toLowerCase()
            : left.item.imported_at;
        const b =
          field === "filename"
            ? right.item.filename.toLowerCase()
            : right.item.imported_at;
        const comparison =
          a < b
            ? -1
            : a > b
              ? 1
              : left.item.import_id < right.item.import_id
                ? -1
                : left.item.import_id > right.item.import_id
                  ? 1
                  : 0;
        return sign * comparison;
      });
      data = {
        items: entries
          .slice((current - 1) * size, current * size)
          .map((entry) => entry.item),
        total: state.saved.length,
        page: current,
        page_size: size,
      };
    } else if (/\/trajectory\/imports\/[^/]+$/.test(path)) {
      const id = path.split("/").at(-1);
      const entry = state.saved.find((entry) => entry.item.import_id === id);
      if (request.method() === "DELETE") {
        state.deleteRequests.push(id);
        if (state.deleteFailures.includes(id)) {
          // Simulate a failed connection without generating a product 5xx.
          await route.abort("connectionfailed");
          return;
        }
        state.saved = state.saved.filter(
          (entry) => entry.item.import_id !== id,
        );
        data = { deleted: true };
      } else if (entry) data = entry;
      else {
        await route.fulfill({
          status: 404,
          json: { detail: { code: "import_not_found" } },
        });
        return;
      }
    } else if (
      path.endsWith("/trajectory/import") ||
      path.endsWith("/trajectory/imports")
    ) {
      state.imports++;
      const body = request.postDataBuffer();
      const replacement = body?.includes(otherRaw);
      if (!replacement && !body?.includes(raw))
        throw new Error("Browser did not upload the original ZIP");
      if (state.delayImport)
        await new Promise((resolve) => {
          state.release = resolve;
        });
      if (state.importFailure) {
        await route.fulfill({
          status: 422,
          json: { detail: { code: "invalid_archive" } },
        });
        return;
      }
      data = replacement ? payload.other_data : payload.data;
      if (path.endsWith("/trajectory/imports")) {
        data = {
          item: {
            import_id: randomUUID(),
            filename: replacement ? "replacement.zip" : "trajectory.zip",
            imported_at: new Date().toISOString(),
            size_bytes: replacement ? otherRaw.length : raw.length,
            row: data.row,
          },
          trajectory: data,
        };
        state.saved.unshift(data);
      }
    } else if (path.endsWith("/snapshot")) {
      state.reads++;
      data = payload.data.pages[0].snapshot;
    } else if (/\/trajectory\/conversations\/[^/]+$/.test(path)) {
      state.reads++;
      data = {
        snapshot_id: "source",
        conversation_id: row.conversation_id,
        executions: [payload.data.pages[0].run],
        next_cursor: null,
        coverage: { complete: true },
        availability: "available",
        active_execution_count: 0,
      };
    } else if (path.includes("/contents/"))
      throw new Error("Imported content must not fetch source bodies");
    else if (path.includes("groups") || path.includes("notifications"))
      data = [];
    else if (request.method() !== "GET") state.writes.push(path);
    await route.fulfill({ json: { code: 0, message: "success", data } });
  });
  const upload = async (replacement = false) => {
    if (!new URL(page.url()).pathname.endsWith("/observability/imports"))
      await page.getByRole("link", { name: "导入列表", exact: true }).click();
    await page.locator('input[type="file"]').setInputFiles({
      name: replacement ? "replacement.zip" : "trajectory.zip",
      mimeType: "application/zip",
      buffer: replacement ? otherRaw : raw,
    });
    await page
      .getByRole("treeitem", {
        name: replacement ? /Replacement 0/ : /Archive 0/,
      })
      .waitFor();
  };
  const close = async () => {
    await page
      .locator(".ant-drawer-header")
      .getByRole("button", { name: "关闭", exact: true })
      .click();
    await page.getByRole("dialog").waitFor({ state: "detached" });
  };
  return { state, raw, row, base, upload, close };
}

export async function persistentArchiveData(page) {
  return page.evaluate(async () => ({
    local: JSON.stringify(Object.entries(localStorage)),
    session: JSON.stringify(Object.entries(sessionStorage)),
    databases: (await indexedDB.databases()).map((value) => value.name),
    cacheNames: await caches.keys(),
    executed: window.archiveExecuted,
  }));
}
