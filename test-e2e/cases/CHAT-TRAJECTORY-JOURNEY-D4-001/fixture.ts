// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Page } from "playwright/test";

/** Owned HTTP boundary; the product page and its state/rendering remain real. */
export async function installTrajectoryFixture(
  page: Page,
  base = process.env.NEXENT_BASE_URL || "http://localhost:3000",
) {
  const state = {
    role: "ADMIN",
    records: [] as URL[],
    reads: [] as URL[],
    cleanups: [] as Record<string, unknown>[],
    writes: [] as string[],
    failure: "",
    cleanupPaused: false,
  };
  const body = (text: string, complete = true) => ({
    availability: "available",
    text,
    complete,
    content_id: "signed-content",
    byte_count: complete ? Buffer.byteLength(text) : 1048579,
    char_count: complete ? text.length : 1048577,
  });
  const makeNode = (
    id: string,
    parent_id: string | null,
    kind: string,
    name: string,
    offset = 0,
  ) => ({
    id,
    parent_id,
    display_trace_id: parent_id ? id : "9223372036854775806",
    kind,
    name,
    status: "completed",
    started_at: new Date(
      Date.parse("2026-11-10T01:00:00Z") + offset,
    ).toISOString(),
    finished_at: "2026-11-10T01:00:02Z",
    duration_ms: 2000 - offset,
    usage:
      kind === "tool"
        ? null
        : { input: 100, output: 20, total: 120, complete: true },
    ttft_ms: kind === "model" ? 0 : null,
    throughput: kind === "model" ? 10 : null,
    direct_child_count: parent_id ? 0 : 3,
    model_call_count: kind === "agent" ? 1 : null,
    tool_call_count: kind === "agent" ? 1 : null,
    model: kind === "model" ? "DeepSeek" : null,
    user: "Owner",
    user_id: "owner",
    attributes: {},
    source: { trace_id: "native", span_id: id, export_seq: "1" },
    input: body("private preview", false),
    output: body("retention_days: 30"),
    reasoning:
      kind === "model"
        ? body("Returned reasoning")
        : { ...body(""), availability: "not_returned", text: null },
  });
  const nodes = [
    makeNode("root", null, "agent", "Friday"),
    makeNode("storage", "root", "agent", "存储设计", 500),
    makeNode("model", "storage", "model", "DeepSeek", 700),
    makeNode("tool", "storage", "tool", "policy.check", 900),
    makeNode("security", "root", "agent", "安全审查", 500),
    makeNode("capacity", "root", "agent", "容量规划", 500),
  ];
  const row = {
    tenant_id: "tenant",
    tenant_name: "Fixture Tenant",
    user_id: "owner",
    user_name: "Owner",
    conversation_id: "9223372036854775806",
    conversation_title: "并行轨迹评估",
    trajectory_id: "execution",
    root_agent_id: "12",
    root_agent_name: "Friday",
    models: ["DeepSeek"],
    status: "success",
    business_status: "completed",
    availability: "available",
    started_at: "2026-11-10T01:00:00Z",
    finished_at: "2026-11-10T01:00:02Z",
    duration_ms: 2000,
    usage: { input: 100, output: 20, total: 120, complete: true },
    coverage: { complete: true },
  };
  const percentiles = {
    p50_ms: 2000,
    p90_ms: 2000,
    p99_ms: 2000,
    sample_count: 1,
  };
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
        id: "administrator",
        email: "fixture@example.test",
        role: "ADMIN",
        tenantId: "tenant",
      }),
    );
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname.replace(/^.*\/api\//, "/api/");
    let data: unknown = {};
    if (
      path.includes("/trajectory/") &&
      !["ADMIN", "SU"].includes(state.role)
    ) {
      await route.fulfill({
        status: 403,
        json: { detail: { code: "administrator_required" } },
      });
      return;
    }
    if (path.endsWith("/trajectory/records")) {
      state.records.push(url);
      const facet = url.searchParams.get("facet");
      data = facet
        ? {
            items: [
              {
                id:
                  facet === "tenants"
                    ? "tenant"
                    : facet === "users"
                      ? "owner"
                      : facet === "agents"
                        ? "12"
                        : row.conversation_id,
                name:
                  facet === "tenants"
                    ? "Fixture Tenant"
                    : facet === "users"
                      ? "Owner"
                      : facet === "agents"
                        ? "Friday"
                        : row.conversation_title,
                tenant_id: "tenant",
                tenant_name: "Fixture Tenant",
              },
            ],
            next_cursor: null,
          }
        : {
            query_id: "query-snapshot",
            as_of: "2026-11-10T01:00:00Z",
            items: [row],
            total: 25,
            page: Number(url.searchParams.get("page") || 1),
            page_size: Number(url.searchParams.get("page_size") || 10),
            summary: {
              conversation_count: 20,
              duration: { ...percentiles, mean_ms: 2000 },
              ttft: { ...percentiles, p50_ms: 0 },
              complete: true,
              coverage: { complete: true },
            },
          };
    } else if (path.endsWith("/snapshot")) {
      state.reads.push(url);
      if (state.failure) {
        await route.fulfill({
          status: state.failure === "content_expired" ? 410 : 409,
          json: { detail: { code: state.failure } },
        });
        return;
      }
      const later = url.searchParams.has("cursor");
      data = {
        snapshot_id: "snapshot",
        conversation_id: row.conversation_id,
        trajectory_id: row.trajectory_id,
        root_node_id: "root",
        nodes: later
          ? [makeNode("later", "root", "tool", "Later tool")]
          : nodes,
        context_nodes: later ? [nodes[0]] : [],
        next_cursor: later ? null : "next-segment",
        coverage: { complete: true },
        scope: {
          kind: "execution",
          complete: false,
          aggregates: "execution_subtree",
        },
      };
    } else if (path.includes("/contents/")) {
      state.reads.push(url);
      if (state.failure) {
        await route.fulfill({
          status: 409,
          json: { detail: { code: state.failure } },
        });
        return;
      }
      const offset = Number(url.searchParams.get("offset") || 0);
      data = {
        text: offset === 0 ? "a".repeat(1048576) : "终",
        offset,
        next_offset: offset === 0 ? 1048576 : 1048579,
        complete: offset > 0,
        byte_count: 1048579,
        char_count: 1048577,
        offset_unit: "utf8_bytes",
      };
    } else if (path.endsWith("/trajectory/cleanup")) {
      const payload = request.postDataJSON();
      state.cleanups.push(payload);
      if (state.cleanupPaused)
        await new Promise((resolve) => setTimeout(resolve, 300));
      data = {
        cutoff_at: "2026-11-03T01:00:00Z",
        scanned_runs: 2,
        deleted_runs: 1,
        deleted_bytes: 100,
        skipped_active: 0,
        pending_runs: payload.cursor ? 1 : 0,
        failed_runs: payload.cursor ? 1 : 0,
        next_cursor: payload.cursor ? null : "cleanup-next",
        done: !!payload.cursor,
      };
    } else if (path.endsWith("/user/current_user_info")) {
      await route.fulfill({
        json: {
          data: {
            user: {
              user_id: "administrator",
              user_email: "fixture@example.test",
              tenant_id: "tenant",
              user_role: state.role,
              groupIds: [],
              permissions: [],
              accessibleRoutes: [
                "/",
                ...(["ADMIN", "SU"].includes(state.role)
                  ? ["/observability"]
                  : []),
              ],
            },
          },
        },
      });
      return;
    } else if (path.endsWith("/tenant_config/deployment_version")) {
      await route.fulfill({
        json: {
          deployment_version: "full",
          app_version: "fixture",
          status: "success",
        },
      });
      return;
    } else if (path.endsWith("/user/session")) {
      data = {};
    } else if (path.includes("groups") || path.includes("notifications")) {
      data = [];
    } else if (request.method() !== "GET") state.writes.push(path);
    await route.fulfill({ json: { code: 0, message: "success", data } });
  });
  return state;
}
