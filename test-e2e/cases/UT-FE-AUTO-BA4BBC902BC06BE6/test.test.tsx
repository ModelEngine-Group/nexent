// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  base,
  chooseFiles,
  deferred,
  expandSection,
  fillBasic,
  identity,
  kb,
  matching,
  models,
  mount,
  prompt,
  reply,
  select,
  server,
  settle,
  t,
  UploadTransport,
} from "../../infra/automation/d1/frontend/aidp-fixtures";
import AidpCreateKbPage from "@/ext_components/aidp/pages/knowledge-create/AidpCreateKbPage";
import AidpUpdateKbModal from "@/ext_components/aidp/pages/knowledge-files/AidpUpdateKbModal";
import AidpImportDrawer from "@/ext_components/aidp/features/file-import/AidpImportDrawer";

const permissionPath = "/api/aidp-mgmt/aidp-permissions/kb-a";
const submit = () =>
  fireEvent.click(document.querySelector("footer button.ant-btn-primary")!);
async function createReady() {
  const view = mount(<AidpCreateKbPage />);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: t("aidpKnowledge.createSubmit") }),
    ).toBeEnabled(),
  );
  return view;
}
const enableGraph = () =>
  fireEvent.click(document.getElementById("is_exist_graph")!);
const enableVlm = async () => {
  fireEvent.click(
    screen.getByRole("switch", {
      name: t("aidpKnowledge.createCaptionEnable"),
    }),
  );
  await settle();
};
const importFiles = () =>
  mount(
    <AidpImportDrawer
      open
      title="Import"
      knowledgeBase={kb}
      onClose={() => {}}
    />,
  );

describe("UT-FE-AUTO-BA4BBC902BC06BE6", () => {
  it("required fields block requests and USER submits private defaults once", async () => {
    const pending = deferred<Response>();
    const original = server.handler;
    server.handler = (request) =>
      request.method === "POST" ? pending.promise : original(request);
    await createReady();
    submit();
    await screen.findByText(t("aidpKnowledge.createKbNameRequired"));
    expect(matching(base, "POST")).toHaveLength(0);
    expect(
      screen.queryByText(t("aidpKnowledge.createIngroupPermission")),
    ).toBeNull();
    fillBasic();
    enableGraph();
    await waitFor(() =>
      expect(document.getElementById("graph_prompt_text")).toHaveValue(
        prompt("chinese", "常规"),
      ),
    );
    enableGraph();
    expandSection("vector");
    await enableVlm();
    await enableVlm();
    expandSection("retrieval");
    const topk = screen.getByRole("spinbutton", {
      name: t("aidpKnowledge.createTopk"),
    });
    fireEvent.change(topk, { target: { value: "1.5" } });
    fireEvent.blur(topk);
    expect(topk).toHaveValue("2");
    submit();
    submit();
    await waitFor(() => expect(matching(base, "POST")).toHaveLength(1));
    expect(matching(base, "POST")[0].body).toMatchObject({
      name: "CreatedKnowledge",
      description: "Description",
      embedding_model: "embed-a",
      chunk_token_num: 1024,
      chunk_overlap_num: 128,
      topk: 2,
      similarity: 0.6,
      is_personal: 0,
      caption_enable: 0,
      vlm_model: "",
      is_exist_graph: false,
      ingroup_permission: "PRIVATE",
      group_ids: [],
    });
    expect(matching(base, "POST")[0].body.graph_config).toBeUndefined();
    await act(async () =>
      pending.resolve(reply({ ...kb, kds_id: "created-kb" })),
    );
    await waitFor(() =>
      expect(identity.push).toHaveBeenCalledWith(
        "/zh/knowledges/detail?kb=created-kb",
      ),
    );
  });
  it.each(["READ_ONLY", "EDIT"])(
    "shared %s creation requires groups and submits the selected group",
    async (permission) => {
      identity.user!.role = "SU";
      const original = server.handler;
      server.handler = (request) =>
        request.method === "POST" ? reply(kb) : original(request);
      await createReady();
      fillBasic();
      if (permission === "EDIT")
        await select(
          "ingroup_permission",
          t("aidpKnowledge.createIngroupPermissionEdit"),
        );
      submit();
      await screen.findByText(t("aidpKnowledge.createAccessGroupsRequired"));
      expect(matching(base, "POST")).toHaveLength(0);
      await select("group_ids", "Group A");
      submit();
      await waitFor(() => expect(matching(base, "POST")).toHaveLength(1));
      expect(matching(base, "POST")[0].body).toMatchObject({
        ingroup_permission: permission,
        group_ids: [1],
      });
    },
  );
  it("typed models and language/domain templates reach the create payload", async () => {
    const original = server.handler;
    server.handler = (request) =>
      request.method === "POST" ? reply(kb) : original(request);
    await createReady();
    fillBasic();
    enableGraph();
    expandSection("graph");
    await waitFor(() =>
      expect(document.getElementById("graph_prompt_text")).toHaveValue(
        prompt("chinese", "常规"),
      ),
    );
    const request = matching("/api/aidp-mgmt/models")[0];
    expect(request.url.searchParams.get("service")).toBe("");
    expect(request.url.searchParams.get("app")).toBe("KnowledgeBase");
    await select("graph_domain", t("aidpKnowledge.createGraphDomainMedical"));
    await waitFor(() =>
      expect(document.getElementById("graph_prompt_text")).toHaveValue(
        prompt("chinese", "医疗"),
      ),
    );
    await select(
      "graph_prompt_language",
      t("aidpKnowledge.createGraphPromptEn"),
    );
    await waitFor(() =>
      expect(document.getElementById("graph_prompt_text")).toHaveValue(
        prompt("english", "医疗"),
      ),
    );
    fireEvent.change(document.getElementById("graph_prompt_text")!, {
      target: { value: "Custom prompt" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: t("aidpKnowledge.createGraphUseDefaultPrompt"),
      }),
    );
    expect(document.getElementById("graph_prompt_text")).toHaveValue(
      prompt("english", "医疗"),
    );
    expandSection("vector");
    await enableVlm();
    expect(document.getElementById("aidp-create-vlm-model")).toBeEnabled();
    expect(
      document.querySelector("#embedding_model")!.closest(".ant-select"),
    ).toHaveTextContent("Vector A");
    expect(
      document.querySelector("#llm_model_name")!.closest(".ant-select"),
    ).toHaveTextContent("Language A");
    expect(
      document.querySelector("#aidp-create-vlm-model")!.closest(".ant-select"),
    ).toHaveTextContent("Vision A");
    for (const id of [
      "graph_thinking",
      "graph_synonym_merge",
      "graph_disambiguation",
    ])
      await select(id, t("aidpKnowledge.createYes"));
    submit();
    await waitFor(() => expect(matching(base, "POST")).toHaveLength(1));
    expect(matching(base, "POST")[0].body).toMatchObject({
      embedding_model: "embed-a",
      caption_enable: 1,
      vlm_model: "vlm-a",
      is_exist_graph: true,
      graph_config: {
        domain: "医疗",
        prompt_language: "英文",
        prompt_text: prompt("english", "医疗"),
        llm_model_name: "llm-a",
        no_think_mode: "否",
        retrieve_subgraph_hop: "2",
        synonym_merge_enable: "是",
        disambiguation_enable: "是",
      },
    });
  });
  it("missing VLM cannot submit a fabricated model", async () => {
    const original = server.handler;
    server.handler = (request) =>
      request.url.pathname === "/api/aidp-mgmt/models"
        ? reply({
            models: models.models.filter((model) => model.model_type !== "vlm"),
          })
        : original(request);
    await createReady();
    fillBasic();
    expandSection("vector");
    await enableVlm();
    submit();
    await waitFor(() =>
      expect(document.getElementById("aidp-create-vlm-model")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(matching(base, "POST")).toHaveLength(0);
  });
  it("create business error is translated and does not navigate", async () => {
    const original = server.handler;
    server.handler = (request) =>
      request.method === "POST"
        ? reply(
            { code: "130502", message: "upstream configuration error" },
            400,
          )
        : original(request);
    await createReady();
    fillBasic();
    submit();
    await screen.findByText(t("errorCode.130502"));
    expect(identity.push).not.toHaveBeenCalled();
    expect(matching(base, "POST")).toHaveLength(1);
  });
  it.each(["models", "graph-template"])(
    "%s fetch failure blocks creation with its business error",
    async (endpoint) => {
      const original = server.handler;
      const path =
        endpoint === "models"
          ? "/api/aidp-mgmt/models"
          : base + "/graph-template";
      server.handler = (request) =>
        request.url.pathname === path
          ? reply({ code: "130503", message: "provider unavailable" }, 503)
          : original(request);
      if (endpoint === "models") mount(<AidpCreateKbPage />);
      else {
        await createReady();
        fillBasic();
        enableGraph();
      }
      await screen.findByText(t("errorCode.130503"));
      expect(
        document.querySelector("footer button.ant-btn-primary"),
      ).toBeDisabled();
      submit();
      expect(matching(base, "POST")).toHaveLength(0);
    },
  );
  it("update preserves no-change and metadata failure behavior", async () => {
    const results: (typeof kb)[] = [];
    const modal = () => (
      <AidpUpdateKbModal
        open
        mode="metadata"
        knowledgeBase={kb}
        onCancel={() => {}}
        onSuccess={(value) => results.push(value)}
      />
    );
    const view = mount(modal());
    fireEvent.click(screen.getByRole("button", { name: t("common.confirm") }));
    await waitFor(() => expect(results).toHaveLength(1));
    expect(matching(permissionPath, "PATCH")).toHaveLength(0);
    expect(results[0]).toEqual(kb);
    view.unmount();
    server.handler = () =>
      reply({ metadata_status: "failed", permissions_saved: true });
    mount(modal());
    fireEvent.change(
      screen.getByPlaceholderText(t("aidpKnowledge.kbNamePlaceholder")),
      { target: { value: "ChangedName" } },
    );
    fireEvent.click(screen.getByRole("button", { name: t("common.confirm") }));
    await waitFor(() => expect(results).toHaveLength(2));
    expect(matching(permissionPath, "PATCH")[0].body).toEqual({
      name: "ChangedName",
      ingroup_permission: "PRIVATE",
      group_ids: [],
    });
    expect(results[1]).toMatchObject({
      kds_name: kb.kds_name,
      description: kb.description,
    });
    await screen.findByText(t("aidpKnowledge.updateKbMetadataFailed"));
  });
  it("permission-only update clears groups without submitting metadata", async () => {
    identity.user!.role = "SU";
    const results: (typeof kb)[] = [];
    server.handler = () =>
      reply({ metadata_status: "not_requested", permissions_saved: true });
    mount(
      <AidpUpdateKbModal
        open
        mode="permissions"
        knowledgeBase={{
          ...kb,
          ingroup_permission: "READ_ONLY",
          group_ids: [1],
        }}
        onCancel={() => {}}
        onSuccess={(value) => results.push(value)}
      />,
    );
    await select(
      "ingroup_permission",
      t("aidpKnowledge.createIngroupPermissionPrivate"),
    );
    fireEvent.click(screen.getByRole("button", { name: t("common.confirm") }));
    await waitFor(() => expect(results).toHaveLength(1));
    expect(matching(permissionPath, "PATCH")[0].body).toEqual({
      ingroup_permission: "PRIVATE",
      group_ids: [],
    });
  });
  it("upload preserves multipart, progress, partial errors and successful file size", async () => {
    const closes: number[] = [];
    mount(
      <AidpImportDrawer
        open
        title="Import"
        knowledgeBase={kb}
        onClose={() => closes.push(1)}
      />,
    );
    await chooseFiles([
      new File(["a".repeat(1024)], "good.txt"),
      new File(["b"], "bad.txt"),
    ]);
    await waitFor(() => expect(UploadTransport.sent).toHaveLength(1));
    const xhr = UploadTransport.sent[0];
    expect(
      xhr.body.getAll("files").map((value) => (value as File).name),
    ).toEqual(["good.txt", "bad.txt"]);
    expect(xhr.headers).not.toHaveProperty("Content-Type");
    expect(xhr.headers).not.toHaveProperty("api_key");
    expect(
      screen.getByRole("button", { name: t("common.confirm") }),
    ).toBeDisabled();
    await act(async () => xhr.progress(50, 100));
    const rings = screen.getAllByLabelText("50%");
    expect(rings[0].querySelector("circle:last-child")).toHaveAttribute(
      "fill",
      "none",
    );
    expect(
      Number(
        rings[0]
          .querySelector("circle:last-child")!
          .getAttribute("stroke-dashoffset"),
      ),
    ).toBeCloseTo(Math.PI * 6.5);
    await act(async () =>
      xhr.complete({
        summary: { total: 2, success: 1, failed: 1 },
        success_list: [{ file_name: "good.txt" }],
        failed_list: [{ file_name: "bad.txt", reason_zh: "Per-file rejected" }],
      }),
    );
    await screen.findByText("Per-file rejected");
    expect(screen.getByText(/^1K/)).toHaveTextContent(
      t("aidpKnowledge.importUploadComplete"),
    );
    expect(screen.queryByLabelText("50%")).toBeNull();
    expect(closes).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: t("common.confirm") }));
    expect(closes).toHaveLength(1);
  });
  it.each([
    [
      "business-code",
      JSON.stringify({ code: "130502", message: "raw configuration error" }),
      "errorCode.130502",
    ],
    ["raw-text", "Gateway unavailable", "Gateway unavailable"],
    [
      "upstream-reason",
      JSON.stringify({
        message: "Outer error",
        details: { upstream_reason: "Provider rejected file" },
      }),
      "Provider rejected file",
    ],
    [
      "message",
      JSON.stringify({ message: "File service failed" }),
      "File service failed",
    ],
  ])(
    "upload %s failure stays on the file row",
    async (_kind, response, expected) => {
      importFiles();
      await chooseFiles([new File(["x"], "failed.txt")]);
      await waitFor(() => expect(UploadTransport.sent).toHaveLength(1));
      await act(async () => UploadTransport.sent[0].complete(response, 500));
      const error = await screen.findByText(t(expected));
      expect(error.closest('[aria-live="polite"]')).toBeTruthy();
      expect(
        screen.getByRole("button", { name: t("common.confirm") }),
      ).toBeEnabled();
    },
  );
  it("one selection applies duplicate, type and 20 MiB boundaries without large allocations", async () => {
    importFiles();
    const sized = (name: string, size: number) =>
      Object.defineProperty(new File(["x"], name), "size", { value: size });
    const valid = ["json", "md", "html"].map((ext) =>
      sized(`valid.${ext}`, 20 * 1024 * 1024),
    );
    const oversized = ["json", "md", "html"].map((ext) =>
      sized(`large.${ext}`, 20 * 1024 * 1024 + 1),
    );
    await chooseFiles([
      ...valid,
      valid[0],
      ...oversized,
      new File(["x"], "invalid.exe"),
    ]);
    await waitFor(() => expect(UploadTransport.sent).toHaveLength(1));
    expect(
      UploadTransport.sent[0].body
        .getAll("files")
        .map((value) => (value as File).name),
    ).toEqual(valid.map((value) => value.name));
    expect(screen.getAllByText(/20 MB/).length).toBeGreaterThanOrEqual(3);
    expect(
      screen.getByText(t("aidpKnowledge.invalidFileType", { count: 1 })),
    ).toBeInTheDocument();
    expect(
      screen.getByText(t("aidpKnowledge.uploadHintSize")),
    ).toHaveTextContent(/json.*md.*html/);
  });
  it("selection accepts only the first 50 files", async () => {
    importFiles();
    await chooseFiles(
      Array.from(
        { length: 51 },
        (_, index) => new File(["x"], `file-${index}.txt`),
      ),
    );
    await waitFor(() => expect(UploadTransport.sent).toHaveLength(1));
    expect(UploadTransport.sent[0].body.getAll("files")).toHaveLength(50);
    expect(screen.queryByText("file-50.txt")).toBeNull();
  });
});
