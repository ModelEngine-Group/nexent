// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  base,
  kb,
  matching,
  mount,
  reply,
  select,
  server,
  settle,
  t,
} from "../../infra/automation/d1/frontend/aidp-fixtures";
import AidpKnowledgeFilesPage from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeFilesPage";

const detailPath = base + "/kb-a";
const modelsPath = "/api/aidp-mgmt/models";
const page = () => (
  <AidpKnowledgeFilesPage
    knowledgeBase={kb}
    onBack={() => {}}
    onDelete={() => {}}
    onUpdated={() => {}}
  />
);

// Backend-normalized graph detail: native booleans, int hop and the graph LLM
// lifted to the top level, exactly as the detail endpoint returns it.
const graphDetail = (overrides: Record<string, unknown> = {}) => ({
  ...kb,
  is_exist_graph: true,
  llm_model_name: "qwen-max",
  graph_config: {
    domain: "常规",
    prompt_language: "中文",
    prompt_text: "提取实体关系。",
    retrieve_subgraph_hop: 2,
    no_think_mode: false,
    synonym_merge_enable: false,
    disambiguation_enable: true,
  },
  ...overrides,
});

// Stateful KB detail: PUT updates are merged into the stored detail the same
// way the backend merges graph_config edits (nested LLM lifted to top level),
// so the refetch after a save renders the updated values.
const statefulDetail = (initial: Record<string, unknown>) => {
  const current = JSON.parse(JSON.stringify(initial));
  const original = server.handler;
  server.handler = (request) => {
    if (request.url.pathname === detailPath && request.method === "PUT") {
      const body = request.body as Record<string, unknown>;
      if (body.graph_config) {
        const updates = body.graph_config as Record<string, unknown>;
        Object.assign(current.graph_config, updates);
        if (typeof updates.llm_model_name === "string")
          current.llm_model_name = updates.llm_model_name;
      }
      if (typeof body.is_exist_graph === "boolean")
        current.is_exist_graph = body.is_exist_graph;
      return reply(current);
    }
    if (request.url.pathname === detailPath && request.method === "GET")
      return reply(current);
    return original(request);
  };
};

const openInformationTab = async () => {
  fireEvent.click(
    screen.getByText(t("aidpKnowledge.detailTabInformation")),
  );
  await waitFor(() =>
    expect(
      screen.getByText(t("aidpKnowledge.detailGraph")),
    ).toBeInTheDocument(),
  );
  // The tab fires its llm/vlm model queries on mount; let them resolve so
  // the model dialog has its options ready.
  await waitFor(() =>
    expect(matching(modelsPath).length).toBeGreaterThanOrEqual(2),
  );
  await settle();
};

const confirmButton = () =>
  screen.getByRole("button", { name: /确\s*定/ });
const cancelButton = () =>
  screen.getByRole("button", { name: /取\s*消/ });
const graphSwitch = () =>
  screen.getByRole("switch", { name: t("aidpKnowledge.detailGraph") });
const fieldValue = (label: string) =>
  screen.getByText(label).parentElement!.querySelector("dd")!;
const lastPutBody = () => matching(detailPath, "PUT").at(-1)!.body;
const editSetting = async (label: string) => {
  fireEvent.click(screen.getByRole("button", { name: label }));
  await screen.findByRole("dialog");
};

describe("AIDP-FE-GRAPH-01", () => {
  it("disabled graph renders the disabled hint without a switch", async () => {
    statefulDetail(graphDetail({ is_exist_graph: false }));
    mount(page());
    await openInformationTab();
    expect(
      screen.getByText(t("aidpKnowledge.detailGraphDisabled")),
    ).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: t("aidpKnowledge.detailEditGraphModel"),
      }),
    ).toBeNull();
    // The whole graph field block is hidden while disabled.
    expect(
      screen.queryByText(t("aidpKnowledge.detailGraphModel")),
    ).toBeNull();
  });

  it("graph setting edits send single-field native payloads and refresh", async () => {
    statefulDetail(graphDetail());
    mount(page());
    await openInformationTab();
    expect(fieldValue(t("aidpKnowledge.detailGraphModel"))).toHaveTextContent(
      "qwen-max",
    );
    expect(fieldValue(t("aidpKnowledge.detailGraphHops"))).toHaveTextContent(
      "2",
    );

    // LLM model.
    await editSetting(t("aidpKnowledge.detailEditGraphModel"));
    await select("value", "llm-a");
    fireEvent.click(confirmButton());
    await screen.findByText(t("aidpKnowledge.detailSettingSaved"));
    expect(lastPutBody()).toEqual({
      graph_config: { llm_model_name: "llm-a" },
    });
    await waitFor(() =>
      expect(
        fieldValue(t("aidpKnowledge.detailGraphModel")),
      ).toHaveTextContent("llm-a"),
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    // Hop count commits on blur through the slider number field.
    await editSetting(t("aidpKnowledge.detailEditGraphHop"));
    const hopInput = screen.getByRole("spinbutton", {
      name: t("aidpKnowledge.detailEditGraphHop"),
    });
    fireEvent.change(hopInput, { target: { value: "3" } });
    fireEvent.blur(hopInput);
    fireEvent.click(confirmButton());
    await waitFor(() =>
      expect(fieldValue(t("aidpKnowledge.detailGraphHops"))).toHaveTextContent(
        "3",
      ),
    );
    expect(lastPutBody()).toEqual({
      graph_config: { retrieve_subgraph_hop: 3 },
    });

    // Thinking toggle is stored as the inverse no_think_mode flag.
    await editSetting(t("aidpKnowledge.detailEditGraphThinking"));
    await select("value", t("aidpKnowledge.createNo"));
    fireEvent.click(confirmButton());
    await waitFor(() =>
      expect(
        fieldValue(t("aidpKnowledge.detailGraphThinking")),
      ).toHaveTextContent(t("common.no")),
    );
    expect(lastPutBody()).toEqual({
      graph_config: { no_think_mode: true },
    });

    await editSetting(t("aidpKnowledge.detailEditGraphSynonym"));
    await select("value", t("aidpKnowledge.createYes"));
    fireEvent.click(confirmButton());
    await waitFor(() =>
      expect(
        fieldValue(t("aidpKnowledge.detailGraphSynonym")),
      ).toHaveTextContent(t("common.yes")),
    );
    expect(lastPutBody()).toEqual({
      graph_config: { synonym_merge_enable: true },
    });

    await editSetting(t("aidpKnowledge.detailEditGraphDisambiguation"));
    await select("value", t("aidpKnowledge.createNo"));
    fireEvent.click(confirmButton());
    await waitFor(() =>
      expect(
        fieldValue(t("aidpKnowledge.detailGraphDisambiguation")),
      ).toHaveTextContent(t("common.no")),
    );
    expect(lastPutBody()).toEqual({
      graph_config: { disambiguation_enable: false },
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("disabling requires the exact confirmation and locks the graph display", async () => {
    statefulDetail(graphDetail());
    mount(page());
    await openInformationTab();
    fireEvent.click(graphSwitch());
    const dialog = await screen.findByRole("dialog");
    // antd renders the confirm title in both the modal header and the
    // confirm body; at least one visible title element must exist.
    const titles = within(dialog).getAllByText(
      t("aidpKnowledge.detailGraphDisableTitle"),
    );
    expect(titles.length).toBeGreaterThan(0);
    // The confirmation must spell out the exact two-line consequence text.
    expect(dialog.querySelector("div.whitespace-pre-wrap")!.textContent).toBe(
      t("aidpKnowledge.detailGraphDisableContent"),
    );
    expect(matching(detailPath, "PUT")).toHaveLength(0);
    fireEvent.click(cancelButton());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(matching(detailPath, "PUT")).toHaveLength(0);

    fireEvent.click(graphSwitch());
    await screen.findByRole("dialog");
    fireEvent.click(confirmButton());
    await screen.findByText(t("aidpKnowledge.detailGraphDisableSuccess"));
    expect(matching(detailPath, "PUT")).toHaveLength(1);
    expect(matching(detailPath, "PUT")[0].body).toEqual({
      is_exist_graph: false,
    });
    await waitFor(() =>
      expect(
        screen.getByText(t("aidpKnowledge.detailGraphDisabled")),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("switch")).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: t("aidpKnowledge.detailEditGraphModel"),
      }),
    ).toBeNull();
  });

  it("disable failure keeps the confirmation open for retry", async () => {
    statefulDetail(graphDetail());
    const layered = server.handler;
    let failures = 0;
    server.handler = (request) => {
      if (
        request.url.pathname === detailPath &&
        request.method === "PUT" &&
        failures === 0
      ) {
        failures += 1;
        return reply({ code: "130503", message: "upstream down" }, 500);
      }
      return layered(request);
    };
    mount(page());
    await openInformationTab();
    fireEvent.click(graphSwitch());
    await screen.findByRole("dialog");
    fireEvent.click(confirmButton());
    await screen.findByText(t("errorCode.130503"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(matching(detailPath, "PUT")).toHaveLength(1);
    await waitFor(() => expect(confirmButton()).toBeEnabled());
    fireEvent.click(confirmButton());
    await screen.findByText(t("aidpKnowledge.detailGraphDisableSuccess"));
    expect(matching(detailPath, "PUT")).toHaveLength(2);
    expect(matching(detailPath, "PUT")[1].body).toEqual({
      is_exist_graph: false,
    });
    await waitFor(() =>
      expect(
        screen.getByText(t("aidpKnowledge.detailGraphDisabled")),
      ).toBeInTheDocument(),
    );
  });

  it("read-only viewers get a disabled switch and no edit buttons", async () => {
    statefulDetail(graphDetail({ permission: "READ_ONLY" }));
    mount(page());
    await openInformationTab();
    const switchElement = graphSwitch();
    expect(switchElement).toBeDisabled();
    fireEvent.click(switchElement);
    await settle();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(matching(detailPath, "PUT")).toHaveLength(0);
    for (const label of [
      "detailEditGraphModel",
      "detailEditGraphHop",
      "detailEditGraphThinking",
      "detailEditGraphSynonym",
      "detailEditGraphDisambiguation",
    ]) {
      expect(
        screen.queryByRole("button", {
          name: t(`aidpKnowledge.${label}`),
        }),
      ).toBeNull();
    }
    // Fields stay visible for read-only inspection.
    expect(
      fieldValue(t("aidpKnowledge.detailGraphModel")),
    ).toHaveTextContent("qwen-max");
  });
});
