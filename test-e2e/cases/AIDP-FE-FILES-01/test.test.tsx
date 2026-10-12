import React from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "antd";
import {
  advance,
  base,
  file,
  filesResponse,
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

const path = base + "/kb-a/documents";
const removePath = path + "/remove";
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
const confirm = () =>
  fireEvent.click(screen.getByRole("button", { name: /确\s*定/ }));

describe("AIDP-FE-FILES-01", () => {
  it("global counts survive search, empty results and pagination", async () => {
    vi.useFakeTimers();
    const original = server.handler;
    server.handler = (request) =>
      request.url.pathname === path
        ? reply(
            request.url.searchParams.get("keyword")
              ? {
                  ...filesResponse(
                    request.url.searchParams.get("keyword") === "guide"
                      ? [file]
                      : [],
                  ),
                  total_reliable: false,
                }
              : filesResponse([file], 21),
          )
        : original(request);
    mount(page());
    await advance(5);
    expect(headerCount()).toHaveTextContent("21");
    expect(
      screen.getByText(t("aidpKnowledge.showTotal", { count: 21 })),
    ).toBeInTheDocument();
    expect(
      screen.getByText(t("aidpKnowledge.detailLocalImport")),
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
    expect(
      screen.queryByText(t("aidpKnowledge.showTotal", { count: 1 })),
    ).toBeNull();
    fireEvent.change(search, { target: { value: "missing" } });
    await advance(260);
    expect(matching(path).at(-1)!.url.searchParams.get("page")).toBe("1");
    expect(
      screen.getByText(t("aidpKnowledge.detailFilesEmpty")),
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
      await screen.findByText(t(expected));
      expect(
        screen.queryByText(t("aidpKnowledge.detailFilesEmpty")),
      ).toBeNull();
      expect(
        screen.queryByRole("button", { name: t("aidpKnowledge.retry") }),
      ).toBeNull();
      expect(matching(path)).toHaveLength(1);
    },
  );

  it("polling updates counts and import refresh waits for drawer close", async () => {
    vi.useFakeTimers();
    let count = 21;
    let added = false;
    const original = server.handler;
    server.handler = (request) =>
      request.url.pathname === path
        ? reply(
            filesResponse(
              added ? [{ ...file, file_name: "added.txt" }] : [file],
              count,
            ),
          )
        : original(request);
    mount(page());
    await advance(5);
    expect(headerCount()).toHaveTextContent("21");
    count = 22;
    const before = matching(path).length;
    await advance(30000);
    expect(matching(path)).toHaveLength(before + 1);
    expect(headerCount()).toHaveTextContent("22");
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
    expect(matching(path)).toHaveLength(opened);
    confirm();
    await advance(5);
    expect(matching(path)).toHaveLength(opened + 1);
    expect(screen.getByText("added.txt")).toBeInTheDocument();
    expect(headerCount()).toHaveTextContent("23");
  });

  it("file deletion success respects cancellation and refreshes the count", async () => {
    let removed = false;
    const original = server.handler;
    server.handler = (request) => {
      if (request.url.pathname === removePath) {
        removed = true;
        return reply({
          summary: { total: 1, success: 1, failed: 0 },
          success_list: [{ file_uuid: file.file_uuid }],
          failed_list: [],
        });
      }
      if (request.url.pathname === path)
        return reply(filesResponse(removed ? [] : [file], removed ? 0 : 1));
      return original(request);
    };
    mount(page());
    await screen.findByText(file.file_name);
    fireEvent.click(screen.getByRole("button", { name: t("common.delete") }));
    fireEvent.click(await screen.findByRole("button", { name: /取\s*消/ }));
    await settle();
    expect(matching(removePath, "POST")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: t("common.delete") }));
    await screen.findByRole("button", { name: /确\s*定/ });
    const before = matching(path).length;
    confirm();
    await screen.findByText(t("aidpKnowledge.detailFilesEmpty"));
    expect(headerCount()).toHaveTextContent("0");
    expect(matching(path)).toHaveLength(before + 1);
    expect(matching(removePath, "POST")).toHaveLength(1);
    expect(matching(removePath, "POST")[0].body).toEqual({
      file_uuids: [file.file_uuid],
    });
  });
  it("file deletion failure keeps the file and rejects confirmation", async () => {
    const original = server.handler;
    server.handler = (request) =>
      request.url.pathname === removePath
        ? reply({
            summary: { total: 1, success: 0, failed: 1 },
            success_list: [],
            failed_list: [
              {
                file_uuid: file.file_uuid,
                reason_zh: "File deletion rejected",
              },
            ],
          })
        : original(request);
    mount(page());
    await screen.findByText(file.file_name);
    let confirmation!: Parameters<typeof Modal.confirm>[0];
    // Own the rejected confirmation promise; AntD's static button rethrows it.
    const prompt = vi.spyOn(Modal, "confirm").mockImplementation((options) => {
      confirmation = options;
      return { destroy: vi.fn(), update: vi.fn() };
    });
    try {
      fireEvent.click(screen.getByRole("button", { name: t("common.delete") }));
      const before = matching(path).length;
      await act(async () => {
        await expect(confirmation.onOk!()).rejects.toThrow(
          "File deletion rejected",
        );
      });
      await screen.findByText("File deletion rejected");
      expect(screen.getByText(file.file_name)).toBeInTheDocument();
      expect(matching(path)).toHaveLength(before);
      expect(
        screen.queryByText(t("aidpKnowledge.deleteDocSuccess")),
      ).toBeNull();
      expect(matching(removePath, "POST")[0].body).toEqual({
        file_uuids: [file.file_uuid],
      });
    } finally {
      prompt.mockRestore();
    }
  });
});
