// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  advance,
  base,
  deferred,
  identity,
  kb,
  listResponse,
  matching,
  mount,
  reply,
  requests,
  server,
  settle,
  t,
  UploadTransport,
} from "../../infra/automation/d1/frontend/aidp-fixtures";
import AidpKnowledgeConfiguration from "@/ext_components/aidp/AidpKnowledgeConfiguration";
import { useAidpKnowledgeList } from "@/ext_components/aidp/pages/knowledge-list/hooks/useAidpKnowledgeList";

async function ready() {
  const view = mount(<AidpKnowledgeConfiguration />);
  await screen.findByText(kb.kds_name);
  return view;
}
async function menu(action: string) {
  fireEvent.click(
    screen.getByRole("button", { name: t("aidpKnowledge.moreOperations") }),
  );
  fireEvent.click(await screen.findByText(t(action)));
}
const confirm = () =>
  fireEvent.click(screen.getByRole("button", { name: /确\s*定/ }));

describe("AIDP-FE-LIST-01", () => {
  it("card/table, guide and columns persist while only the name enters files", async () => {
    const view = await ready();
    expect(document.querySelector("article")).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: new RegExp(t("aidpKnowledge.guideCollapse")),
      }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("--")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(t("aidpKnowledge.guideCollapse")),
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(t("aidpKnowledge.guideExpand")),
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(t("aidpKnowledge.guideCollapse")),
      }),
    );
    fireEvent.click(
      document.querySelector(`[title="${t("aidpKnowledge.viewTable")}"]`)!,
    );
    fireEvent.click(
      screen.getByRole("button", { name: t("aidpKnowledge.columnSettings") }),
    );
    expect(
      screen.getByRole("checkbox", { name: t("aidpKnowledge.columnName") }),
    ).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: t("aidpKnowledge.columnActions") }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: t("aidpKnowledge.columnCreatedAt"),
      }),
    );
    await waitFor(() =>
      expect(
        JSON.parse(sessionStorage.getItem("aidpKnowledge.visibleColumns")!),
      ).not.toContain("created_at"),
    );
    view.unmount();
    mount(<AidpKnowledgeConfiguration />, view.client);
    await waitFor(() => expect(document.querySelector("table")).toBeTruthy());
    expect(document.querySelector("article")).toBeNull();
    expect(
      screen.getByRole("button", {
        name: new RegExp(t("aidpKnowledge.guideExpand")),
      }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("columnheader", {
        name: t("aidpKnowledge.columnCreatedAt"),
      }),
    ).toBeNull();
    fireEvent.click(screen.getByText(kb.description));
    expect(identity.push).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(kb.kds_name));
    await waitFor(() =>
      expect(identity.push).toHaveBeenCalledWith(
        "/zh/knowledges/detail?kb=kb-a",
      ),
    );
  });

  it("pagination and debounced search use the right parameters and reset page", async () => {
    vi.useFakeTimers();
    server.handler = (request) =>
      reply(
        listResponse(
          request.url.searchParams.get("keyword") ? [] : [kb],
          request.url.searchParams.get("keyword") ? 0 : 21,
        ),
      );
    mount(<AidpKnowledgeConfiguration />);
    await advance(5);
    fireEvent.click(document.querySelector(".ant-pagination-item-2")!);
    await advance(5);
    expect(matching(base).at(-1)!.url.searchParams.get("page")).toBe("2");
    const search = screen.getByPlaceholderText(
      t("aidpKnowledge.searchPlaceholder"),
    );
    fireEvent.change(search, { target: { value: "  missing  " } });
    const before = matching(base).length;
    await advance(200);
    expect(matching(base)).toHaveLength(before);
    await advance(110);
    expect(matching(base).at(-1)!.url.searchParams.get("keyword")).toBe(
      "missing",
    );
    expect(matching(base).at(-1)!.url.searchParams.get("page")).toBe("1");
    expect(
      screen.getByText(t("aidpKnowledge.searchEmpty")),
    ).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "" } });
    await advance(310);
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: t("aidpKnowledge.pageSize") }),
    );
    fireEvent.click(
      screen.getByText(t("aidpKnowledge.pageSizeOption", { size: 20 })),
    );
    await advance(5);
    expect(matching(base).at(-1)!.url.searchParams.get("page_size")).toBe("20");
    expect(matching(base).at(-1)!.url.searchParams.get("page")).toBe("1");
  });

  it.each(["confirm", "close"])(
    "import %s pauses polling and refreshes exactly on close",
    async (closeMode) => {
      vi.useFakeTimers();
      mount(<AidpKnowledgeConfiguration />);
      await advance(5);
      const first = matching(base).length;
      await advance(30000);
      expect(matching(base)).toHaveLength(first + 1);
      fireEvent.click(
        screen.getByRole("button", { name: t("aidpKnowledge.moreOperations") }),
      );
      await advance(5);
      fireEvent.click(screen.getByText(t("aidpKnowledge.importFile")));
      await advance(5);
      const opened = matching(base).length;
      await advance(30000);
      expect(matching(base)).toHaveLength(opened);
      fireEvent.change(document.querySelector("input[type=file]")!, {
        target: { files: [new File(["x"], "added.txt")] },
      });
      await advance(25);
      expect(UploadTransport.sent).toHaveLength(1);
      await act(async () =>
        UploadTransport.sent[0].complete({
          summary: { total: 1, success: 1, failed: 0 },
          success_list: [{ file_name: "added.txt" }],
          failed_list: [],
        }),
      );
      await advance(5);
      expect(matching(base)).toHaveLength(opened);
      if (closeMode === "confirm") confirm();
      else fireEvent.click(screen.getByRole("button", { name: "Close" }));
      await advance(5);
      expect(matching(base)).toHaveLength(opened + 1);
      await advance(30000);
      expect(matching(base)).toHaveLength(opened + 2);
    },
  );

  it("cancelled deletion does nothing and confirmed deletion refreshes the list", async () => {
    let deleted = false;
    const original = server.handler;
    server.handler = (request) => {
      if (request.method === "DELETE") {
        deleted = true;
        return reply({});
      }
      if (request.url.pathname === base)
        return reply(listResponse(deleted ? [] : [kb]));
      return original(request);
    };
    await ready();
    await menu("common.delete");
    fireEvent.click(await screen.findByRole("button", { name: /取\s*消/ }));
    await settle();
    expect(matching(base + "/kb-a", "DELETE")).toHaveLength(0);
    await menu("common.delete");
    await screen.findByRole("button", { name: /确\s*定/ });
    const before = matching(base).length;
    confirm();
    await screen.findByText(t("aidpKnowledge.listEmpty"));
    expect(matching(base + "/kb-a", "DELETE")).toHaveLength(1);
    expect(matching(base)).toHaveLength(before + 1);
  });

  it.each(["user", "tenant"])(
    "late responses remain isolated after switching %s",
    async (dimension) => {
      const old = deferred<Response>();
      let calls = 0;
      server.handler = () =>
        ++calls === 1
          ? old.promise
          : reply(listResponse([{ ...kb, kds_name: "NewIdentityKnowledge" }]));
      function Probe() {
        const query = useAidpKnowledgeList(1, 10, "");
        return (
          <div>
            {query.data?.value.map((item) => item.kds_name).join(",") ||
              "waiting"}
          </div>
        );
      }
      const view = mount(<Probe />);
      await waitFor(() => expect(calls).toBe(1));
      identity.user = {
        ...identity.user!,
        ...(dimension === "user"
          ? { id: "owner-b" }
          : { tenantId: "tenant-b" }),
      };
      view.rerender(<Probe />);
      await screen.findByText("NewIdentityKnowledge");
      await act(async () => old.resolve(reply(listResponse())));
      await settle();
      expect(screen.queryByText(kb.kds_name)).toBeNull();
      expect(screen.getByText("NewIdentityKnowledge")).toBeInTheDocument();
      expect(view.client.getQueryCache().getAll()).toHaveLength(2);
      const before = requests.length;
      identity.enabled = false;
      identity.user!.id = "disabled-user";
      view.rerender(<Probe />);
      await settle();
      identity.enabled = true;
      identity.user = null;
      view.rerender(<Probe />);
      await settle();
      expect(requests).toHaveLength(before);
    },
  );
});
