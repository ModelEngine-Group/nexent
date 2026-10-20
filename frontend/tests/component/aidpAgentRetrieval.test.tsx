// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { KnowledgeBaseConfigActions } from "@/app/agents/[agentId]/components/knowledge-base-search";

const state = vi.hoisted(() => ({
  updateTools: vi.fn(),
  tool: {
    id: 9,
    name: "aidp_search",
    source: "local",
    initParams: [
      { name: "kds_list", value: '["kb"]', type: "string", required: false },
      { name: "top_k", value: 7, type: "number", required: false },
      { name: "vector_candidates", value: 30, type: "number", required: false },
    ],
  },
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (select: (s: unknown) => unknown) =>
    select({
      editedAgent: { tools: [state.tool] },
      updateTools: state.updateTools,
    }),
}));
vi.mock("@/hooks/agent/useAgentReadOnly", () => ({
  useAgentReadOnly: () => false,
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ aidpEnabled: true, isDeploymentReady: true }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ availableTools: [state.tool], isLoading: false }),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  useKnowledgeBasesForToolConfig: () => ({
    data: [{ id: "kb", name: "KB" }],
    isLoading: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/components/resource-picker/KnowledgeDrawer", () => ({
  KnowledgeDrawer: () => null,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

it("agent settings cancel draft and confirm coupled fields in a single store update", () => {
  render(<KnowledgeBaseConfigActions />);
  fireEvent.click(
    screen.getByRole("button", { name: "agent.knowledge.button.configure" })
  );
  fireEvent.click(
    screen.getByRole("switch", {
      name: "aidpRetrieval.fields.reranking_enable",
    })
  );
  expect(state.updateTools).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("common.cancel"));
  expect(state.updateTools).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "agent.knowledge.button.configure" })
  );
  expect(
    screen.getByRole("switch", {
      name: "aidpRetrieval.fields.reranking_enable",
    })
  ).toHaveAttribute("aria-checked", "true");
  fireEvent.click(
    screen.getByRole("switch", {
      name: "aidpRetrieval.fields.reranking_enable",
    })
  );
  fireEvent.click(screen.getByText("common.confirm"));
  expect(state.updateTools).toHaveBeenCalledOnce();
  const saved = state.updateTools.mock.calls[0][0][0];
  const params = Object.fromEntries(
    saved.initParams.map((p: { name: string; value: unknown }) => [
      p.name,
      p.value,
    ])
  );
  expect(params).toMatchObject({
    kds_list: '["kb"]',
    top_k: 7,
    vector_candidates: 30,
    reranking_enable: false,
    graph_reranking_enable: false,
  });
  expect(state.tool.initParams).toHaveLength(3);
});
