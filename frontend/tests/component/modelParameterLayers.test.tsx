// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AgentModelParameters } from "../../components/model/AgentModelParameters";
import { ConversationModelParameters } from "../../components/model/ConversationModelParameters";
import {
  agentParameterValues,
  withAgentParameterValues,
} from "../../lib/modelParameterLayers";

const api = vi.hoisted(() => ({
  getModelOutlet: vi.fn(),
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
vi.mock("../../services/modelProfileService", () => api);
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const rule = (key: string) => ({
  key,
  visible: true,
  editable: true,
  required: false,
  allowed_scopes: ["outlet", "conversation"],
  schema: { type: "number" },
});
function setup(child: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <App>{child}</App>
    </QueryClientProvider>
  );
}
beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getModelOutlet.mockResolvedValue({
    config_revision: 1,
    profile: {
      parameter_values: { temperature: 0.8, top_k: 20 },
      parameter_rules: [rule("temperature"), rule("top_k"), rule("headers")],
      capabilities: { context: { combined_window: 200000 } },
    },
  });
  api.getConversationModelPreferences.mockResolvedValue({
    version: 1,
    parameter_values: {},
    defaults: { temperature: 0.8 },
    field_specs: [rule("temperature")],
    issues: [],
  });
  api.patchConversationModelPreferences.mockResolvedValue({});
});

it("keeps false and zero explicit, stores top_k in extra_params and preserves legacy custom values", () => {
  expect(
    agentParameterValues({
      temperature: 0,
      extra_params: { enable_thinking: false, top_k: 0 },
    })
  ).toEqual({ temperature: 0, enable_thinking: false, top_k: 0 });
  expect(
    withAgentParameterValues(
      {
        temperature: 0.4,
        extra_params: { top_k: 5, __custom__: { flag: false } },
      },
      { top_k: 0 }
    )
  ).toEqual({ extra_params: { top_k: 0, __custom__: { flag: false } } });
});

it("shows outlet defaults without persisting them; saves only an explicit Agent top_k and context window", async () => {
  const apply = vi.fn();
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{}}
      onApply={apply}
      onClose={vi.fn()}
    />
  );
  const input = await screen.findByRole("spinbutton", { name: "top_k" });
  expect(input).toHaveValue("20");
  expect(
    screen.queryByRole("spinbutton", { name: "headers" })
  ).not.toBeInTheDocument();
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.change(
    screen.getByRole("spinbutton", { name: "context_window_tokens" }),
    { target: { value: "64000" } }
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(apply).toHaveBeenCalledWith({
      extra_params: { top_k: 0 },
      context_window_tokens: 64000,
    })
  );
});

it("clearing an Agent override removes the field instead of copying the outlet default", async () => {
  const apply = vi.fn();
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{ temperature: 0.4 }}
      onApply={apply}
      onClose={vi.fn()}
    />
  );
  await screen.findByRole("spinbutton", { name: "temperature" });
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.useOutletDefault" })
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(apply).toHaveBeenCalledWith({}));
});

it("session displays Agent values above outlet defaults but saves only the explicit session change", async () => {
  setup(
    <ConversationModelParameters
      conversationId={11}
      modelId={42}
      agentDefaults={{ temperature: 0.4 }}
    />
  );
  fireEvent.click(
    screen.getByRole("button", { name: "modelProfile.parameters" })
  );
  const input = await screen.findByRole("spinbutton", { name: "temperature" });
  expect(input).toHaveValue("0.4");
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "common.save" }));
  await waitFor(() =>
    expect(api.patchConversationModelPreferences).toHaveBeenCalledWith(11, 42, {
      expected_version: 1,
      parameter_values: { temperature: 0 },
      delete_parameters: [],
    })
  );
});

it("failed outlet loading cannot apply an Agent configuration", async () => {
  api.getModelOutlet.mockRejectedValue(new Error("offline"));
  const apply = vi.fn();
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{}}
      onApply={apply}
      onClose={vi.fn()}
    />
  );
  await screen.findByText("modelProfile.loadFailed");
  expect(
    screen.queryByRole("button", { name: "common.confirm" })
  ).not.toBeInTheDocument();
  expect(apply).not.toHaveBeenCalled();
});
