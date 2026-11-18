// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  advance,
  base,
  file,
  folderTreeResponse,
  kb,
  matching,
  mount,
  reply,
  server,
  settle,
  t,
  UploadTransport,
} from "../../infra/automation/d1/frontend/aidp-fixtures";
import AidpKnowledgeFilesPage from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeFilesPage";

const path = base + "/kb-a/folders/tree";
const detailPath = base + "/kb-a";
const removePath = base + "/kb-a/documents/remove";
const movePath = base + "/kb-a/files/move";
const page = () => (
  <AidpKnowledgeFilesPage
    knowledgeBase={kb}
    onBack={() => {}}
    onDelete={() => {}}
    onUpdated={() => {}}
  />
);
const headerCount = () =>
  screen
    .getAllByText(t("aidpKnowledge.detailTabFiles"))
    .find((element) => element.tagName === "DT")!.parentElement!;
const deleteDialogButton = () =>
  within(screen.getByRole("dialog")).getByRole("button", {
    name: /删\s*除/,
  });
const confirmDelete = () => fireEvent.click(deleteDialogButton());
// The page also renders the KB-level delete and the batch delete; scope the
// query to the file's own row so only its action button is clicked.
const rowDelete = () =>
  within(screen.getByText(file.file_name).closest("tr")!).getByRole("button", {
    name: t("common.delete"),
  });

describe("AIDP-FE-FILES-01", () => {
  it("global counts survive search, empty results and pagination", async () => {
    vi.useFakeTimers();
    const original = server.handler;
    server.handler = (request) => {
      if (request.url.pathname === detailPath && request.method === "GET")
        return reply({ ...kb, document_count: 21 });
      if (request.url.pathname === path) {
        const keyword = request.url.searchParams.get("keyword");
        return reply(
          keyword
            ? folderTreeResponse(
                [],
                keyword === "guide" ? [file] : [],
                keyword === "guide" ? 1 : 0,
              )
            : folderTreeResponse([], [file], 21),
        );
      }
      return original(request);
    };
    mount(page());
    await advance(5);
    expect(headerCount()).toHaveTextContent("21");
    expect(
      screen.getByText(t("aidpKnowledge.showTotal", { count: 21 }), {
        exact: false,
      }),
    ).toBeInTheDocument();
    fireEvent.click(document.querySelector(".ant-pagination-item-2")!);
    await advance(5);
    expect(matching(path).at(-1)!.url.searchParams.get("page")).toBe("2");
    const search = screen.getByPlaceholderText(
      t("aidpKnowledge.detailFileSearch"),
    );
    fireEvent.change(search, { target: { value: "guide" } });
    await advance(260);
    expect(screen.getByText(file.file_name)).toBeInTheDocument();
    expect(headerCount()).toHaveTextContent("21");
    fireEvent.change(search, { target: { value: "missing" } });
    await advance(260);
    expect(matching(path).at(-1)!.url.searchParams.get("page")).toBe("1");
    expect(
      screen.getByText(t("aidpKnowledge.filesSearchEmpty")),
    ).toBeInTheDocument();
    expect(headerCount()).toHaveTextContent("21");
    fireEvent.change(search, { target: { value: "" } });
    await advance(260);
    expect(screen.getByText(file.file_name)).toBeInTheDocument();
    expect(headerCount()).toHaveTextContent("21");
  });

  it.each([
    [
      "business-code",
      { code: "130503", message: "upstream down" },
      "errorCode.130503",
    ],
    [
      "upstream-message",
      { message: "Count request failed" },
      "Count request failed",
    ],
  ])(
    "query %s failure is visible instead of an empty file list",
    async (_kind, body, expected) => {
      const original = server.handler;
      server.handler = (request) =>
        request.url.pathname === path ? reply(body, 500) : original(request);
      mount(page());
      expect((await screen.findAllByText(t(expected))).length).toBeGreaterThan(
        0,
      );
      expect(
        screen.queryByText(t("aidpKnowledge.filesSearchEmpty")),
      ).toBeNull();
      expect(matching(path).length).toBeGreaterThanOrEqual(1);
    },
  );

  it("polling pauses while importing and refreshes after upload center completion", async () => {
    vi.useFakeTimers();
    let count = 21;
    let added = false;
    const original = server.handler;
    server.handler = (request) => {
      if (request.url.pathname === detailPath && request.method === "GET")
        return reply({ ...kb, document_count: count });
      if (request.url.pathname === path)
        return reply(
          folderTreeResponse(
            [],
            added ? [{ ...file, file_name: "added.txt" }] : [file],
            count,
          ),
        );
      return original(request);
    };
    mount(page());
    await advance(5);
    expect(headerCount()).toHaveTextContent("21");
    count = 22;
    const before = matching(path).length;
    await advance(30000);
    expect(matching(path).length).toBeGreaterThan(before);
    // The KB-level count comes from the detail endpoint, not the folder page.
    expect(headerCount()).toHaveTextContent("21");
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(t("aidpKnowledge.importFile")),
      }),
    );
    await advance(5);
    const opened = matching(path).length;
    await advance(30000);
    expect(matching(path)).toHaveLength(opened);
    fireEvent.change(document.querySelector("input[type=file]")!, {
      target: { files: [new File(["x"], "added.txt")] },
    });
    await advance(5);
    fireEvent.click(
      screen.getByRole("button", {
        name: t("aidpKnowledge.importAction"),
      }),
    );
    await advance(5);
    // The upload contract carries the target folder and one relative path per
    // file, even for a root upload.
    const uploadForm = UploadTransport.sent[0].body;
    expect(uploadForm.getAll("target_folder")).toEqual(["/"]);
    expect(uploadForm.getAll("relative_paths")).toEqual(["added.txt"]);
    added = true;
    count = 23;
    await act(async () =>
      UploadTransport.sent[0].complete({
        summary: { total: 1, success: 1, failed: 0 },
        success_list: [{ file_name: "added.txt" }],
        failed_list: [],
      }),
    );
    await advance(5);
    expect(matching(path).length).toBeGreaterThanOrEqual(opened + 1);
    expect(screen.getAllByText("added.txt").length).toBeGreaterThan(0);
    await waitFor(() => expect(headerCount()).toHaveTextContent("23"));
  });

  it("file deletion success respects cancellation and refreshes the count", async () => {
    let removed = false;
    const original = server.handler;
    server.handler = (request) => {
      if (request.url.pathname === detailPath && request.method === "GET")
        return reply({ ...kb, document_count: removed ? 0 : 1 });
      if (request.url.pathname === removePath) {
        removed = true;
        return reply({
          summary: { total: 1, success: 1, failed: 0 },
          success_list: [{ file_uuid: file.file_uuid }],
          failed_list: [],
        });
      }
      if (request.url.pathname === path)
        return reply(
          folderTreeResponse([], removed ? [] : [file], removed ? 0 : 1),
        );
      return original(request);
    };
    mount(page());
    await screen.findByText(file.file_name);
    fireEvent.click(rowDelete());
    fireEvent.click(await screen.findByRole("button", { name: /取\s*消/ }));
    await settle();
    expect(matching(removePath, "POST")).toHaveLength(0);
    fireEvent.click(rowDelete());
    await screen.findByRole("dialog");
    const before = matching(path).length;
    confirmDelete();
    await screen.findByText(t("aidpKnowledge.filesEmptyRoot"));
    await waitFor(() => expect(headerCount()).toHaveTextContent("0"));
    expect(matching(path).length).toBeGreaterThan(before);
    expect(matching(removePath, "POST")).toHaveLength(1);
    expect(matching(removePath, "POST")[0].body).toEqual({
      file_uuids: [file.file_uuid],
    });
  });
  it.each(["retry", "cancel"])(
    "file deletion failure keeps the dialog for %s without an unhandled rejection",
    async (action) => {
      const original = server.handler;
      let attempts = 0;
      let deleted = false;
      server.handler = (request) => {
        if (request.url.pathname === detailPath && request.method === "GET")
          return reply({ ...kb, document_count: 1 });
        if (request.url.pathname === removePath) {
          if (++attempts > 1) {
            deleted = true;
            return reply({
              summary: { total: 1, success: 1, failed: 0 },
              success_list: [{ file_uuid: file.file_uuid }],
              failed_list: [],
            });
          }
          return reply({
            summary: { total: 1, success: 0, failed: 1 },
            success_list: [],
            failed_list: [
              {
                file_uuid: file.file_uuid,
                reason_zh: "File deletion rejected",
              },
            ],
          });
        }
        if (request.url.pathname === path && deleted)
          return reply(folderTreeResponse([], [], 0));
        return original(request);
      };
      mount(page());
      await screen.findByText(file.file_name);
      fireEvent.click(rowDelete());
      await screen.findByRole("dialog");
      const before = matching(path).length;
      confirmDelete();
      await screen.findByText("File deletion rejected");
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(
        within(screen.getByRole("dialog")).getByText(
          new RegExp(file.file_name),
        ),
      ).toBeInTheDocument();
      expect(matching(path)).toHaveLength(before);
      expect(
        screen.queryByText(t("aidpKnowledge.deleteDocSuccess")),
      ).toBeNull();
      expect(matching(removePath, "POST")[0].body).toEqual({
        file_uuids: [file.file_uuid],
      });
      await waitFor(() => expect(deleteDialogButton()).toBeEnabled());
      if (action === "retry") {
        confirmDelete();
        await screen.findByText(t("aidpKnowledge.filesEmptyRoot"));
        expect(matching(removePath, "POST")).toHaveLength(2);
        expect(matching(path).length).toBeGreaterThan(before);
      } else {
        fireEvent.click(screen.getByRole("button", { name: /取\s*消/ }));
        expect(matching(removePath, "POST")).toHaveLength(1);
        expect(matching(path)).toHaveLength(before);
      }
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    },
  );

  it("batch move keeps failed files selected and shows reasons inline", async () => {
    const secondFile = {
      ...file,
      file_uuid: "8e2b9c37-8d83-4e3d-8472-457a74aa4e53",
      file_name: "report.pdf",
      file_type: "pdf",
    };
    let moved = false;
    const original = server.handler;
    server.handler = (request) => {
      if (request.url.pathname === movePath && request.method === "POST") {
        moved = true;
        return reply({
          summary: { total: 2, success: 1, failed: 1 },
          success_list: [{ file_uuid: file.file_uuid }],
          failed_list: [
            {
              file_uuid: secondFile.file_uuid,
              reason_zh: "目标目录无写权限",
            },
          ],
        });
      }
      if (request.url.pathname === path) {
        return reply(
          folderTreeResponse(
            [{ folder_name: "目标目录", is_empty: true }],
            moved ? [secondFile] : [file, secondFile],
            moved ? 1 : 2,
          ),
        );
      }
      return original(request);
    };

    mount(page());
    await screen.findByText(file.file_name);
    await screen.findByText(secondFile.file_name);
    fireEvent.click(
      within(screen.getByText(file.file_name).closest("tr")!).getByRole(
        "checkbox",
      ),
    );
    fireEvent.click(
      within(screen.getByText(secondFile.file_name).closest("tr")!).getByRole(
        "checkbox",
      ),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: t("aidpKnowledge.fileMoveAction"),
      }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByText("目标目录"));
    fireEvent.click(within(dialog).getByRole("button", { name: /确\s*定/ }));

    await screen.findByText(
      t("aidpKnowledge.fileMoveResultTitle", {
        success: 1,
        failed: 1,
      }),
    );
    expect(screen.getByText(/目标目录无写权限/)).toBeInTheDocument();
    expect(
      screen.getByText(
        t("aidpKnowledge.fileMoveFailureTarget", {
          folder: "/目标目录",
        }),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(file.file_name)).toBeNull();
    const remainingRow = screen
      .getAllByText(secondFile.file_name)
      .map((element) => element.closest("tr"))
      .find((row): row is HTMLTableRowElement => Boolean(row))!;
    expect(within(remainingRow).getByRole("checkbox")).toBeChecked();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(matching(movePath, "POST")[0].body).toEqual({
      file_uuids: [file.file_uuid, secondFile.file_uuid],
      target_folder: "/目标目录",
    });
  });
});
