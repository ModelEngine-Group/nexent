import fs from "node:fs";
import path from "node:path";
import type { Page, Route } from "playwright/test";
import { makeDraft, fulfillEditorReadFixture } from "./agent-editor-reads.mjs";

export const baseUrl = process.env.NEXENT_BASE_URL || "http://localhost:3000";
const messages = JSON.parse(
  fs.readFileSync(
    path.join(
      process.env.NEXENT_REPO!,
      "frontend/public/locales/zh/common.json",
    ),
    "utf8",
  ),
);
export function label(key: string): string {
  const value = messages[key];
  if (typeof value !== "string") throw new Error(`Missing translation: ${key}`);
  return value;
}

export async function installEditor(page: Page, permission = "EDIT") {
  const state = {
    draft: makeDraft(permission),
    creationAttempts: [] as Record<string, any>[],
    updates: [] as Record<string, any>[],
    unexpectedWrites: [] as string[],
    conflicts: new Set<string>(),
    rejectNextCreation: false,
    successfulCreations: 0,
  };
  const json = (route: Route, data: unknown, status = 200) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.replace(/^.*\/api/, "");
    const payload = request
      .headers()
      ["content-type"]?.includes("application/json")
      ? request.postDataJSON()
      : undefined;
    if (await fulfillEditorReadFixture(route, endpoint)) return;
    if (endpoint === "/agent/search_info") return json(route, state.draft);
    if (endpoint === "/agent/check_name")
      return json(
        route,
        (payload?.items || []).map((item: any) => ({
          name_conflict: false,
          display_name_conflict: state.conflicts.has(item.display_name),
        })),
      );
    if (endpoint === "/agent/update") {
      if (permission === "READ_ONLY") {
        state.unexpectedWrites.push(endpoint);
        return json(route, { detail: "Read-only mutation rejected" }, 403);
      }
      if (!payload?.agent_id) {
        state.creationAttempts.push(payload);
        if (state.rejectNextCreation) {
          state.rejectNextCreation = false;
          return json(route, { detail: "Controlled creation rejection" }, 400);
        }
        state.successfulCreations++;
      } else state.updates.push(payload);
      state.draft = { ...state.draft, ...payload, agent_id: 42 };
      return json(route, { agent_id: 42, status: "success" });
    }
    if (endpoint === "/agent/published_list")
      return json(route, [{ ...state.draft, current_version_no: 1 }]);
    if (endpoint === "/agent/list/page")
      return json(route, {
        items: [],
        pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
      });
    if (endpoint === "/agent/list") return json(route, []);
    if (/^\/agent\/\d+\/versions$/.test(endpoint))
      return json(route, { items: [], total: 0 });
    if (endpoint.startsWith("/tag-assignments/"))
      return json(route, {
        resource_type: "agent",
        resource_id: "42",
        assignment_count: 0,
        assignment_capacity: 100,
        assignments: [],
      });
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method()))
      state.unexpectedWrites.push(endpoint);
    return json(route, { data: [], items: [], total: 0, status: "success" });
  });
  return state;
}
