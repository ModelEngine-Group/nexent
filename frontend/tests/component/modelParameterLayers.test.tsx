// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AgentModelParameters } from "../../components/model/AgentModelParameters";
import { ConversationModelParameters, ConversationModelParameterSummary } from "../../components/model/ConversationModelParameters";
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

it("keeps false and zero explicit, stores canonical parameter_values and preserves legacy custom values", () => {
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
  ).toEqual({
    parameter_values: { top_k: 0 },
    custom_overrides: { flag: false },
  });
});

it("Agent scope excludes length editing and drops retired context overrides while saving explicit parameters", async () => {
  const apply = vi.fn();
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{ context_window_tokens: 64000 }}
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
  expect(
    screen.queryByRole("spinbutton", { name: "context_window_tokens" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(apply).toHaveBeenCalledWith({
      parameter_values: { top_k: 0 },
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
  await waitFor(() =>
    expect(apply).toHaveBeenCalledWith({ parameter_values: {} })
  );
});

it("session displays Agent values above outlet defaults but saves only the explicit session change", async () => {
  setup(
    <ConversationModelParameters
      conversationId={11}
      modelId={42}
      agentDefaults={{ temperature: 0.4 }}
    />
  );
  const advanced = await screen.findByRole("button", {
    name: "workbench.controls.advanced",
  });
  await waitFor(() => expect(advanced).toBeEnabled());
  fireEvent.click(advanced);
  const input = await screen.findByRole("spinbutton", {
    name: "workbench.controls.temperature",
  });
  expect(input).toHaveValue(0.4);
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.blur(input);
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

it("reads current Agent parameters and writes current format without copying defaults", () => {
  expect(
    agentParameterValues({
      parameter_values: { temperature: 0, enable_thinking: false },
    })
  ).toEqual({ temperature: 0, enable_thinking: false });
  expect(
    withAgentParameterValues(
      { parameter_values: { top_p: 0.8 }, context_window_tokens: 4096 },
      {}
    )
  ).toEqual({ parameter_values: {} });
});

it("Agent thinking hides degree while off and prefills half the output limit on enable", async () => {
  const apply = vi.fn();
  api.getModelOutlet.mockResolvedValue({
    config_revision: 1,
    profile: {
      parameter_values: { enable_thinking: false },
      parameter_rules: [
        { ...rule("enable_thinking"), schema: { type: "boolean" } },
        {
          ...rule("reasoning_budget_tokens"),
          schema: { type: "integer", minimum: 1 },
          condition: { key: "enable_thinking", op: "eq", value: true },
        },
      ],
      capabilities: { context: { combined_window: 8192, output_limit: 1024 } },
    },
  });
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{}}
      onApply={apply}
      onClose={vi.fn()}
    />
  );
  const toggle = await screen.findByRole("switch");
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  fireEvent.click(toggle);
  expect(
    await screen.findByRole("combobox", { name: "modelProfile.thinkingMode" })
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("spinbutton", {
      name: "modelProfile.thinkingDegree",
    })
  ).toHaveValue("512");
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(apply).toHaveBeenCalledWith({
      parameter_values: { enable_thinking: true, reasoning_budget_tokens: 512 },
    })
  );
});

it("Agent toggle-only outlet never invents an effort or budget parameter", async () => {
  const apply = vi.fn();
  api.getModelOutlet.mockResolvedValue({
    config_revision: 1,
    profile: {
      parameter_values: { enable_thinking: false },
      parameter_rules: [
        { ...rule("enable_thinking"), schema: { type: "boolean" } },
      ],
      capabilities: { context: { combined_window: 8192, output_limit: 1024 } },
    },
  });
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{}}
      onApply={apply}
      onClose={vi.fn()}
    />
  );
  fireEvent.click(await screen.findByRole("switch"));
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(apply).toHaveBeenCalledWith({
      parameter_values: { enable_thinking: true },
    })
  );
});

it.each([
  {
    key: "reasoning_effort",
    schema: { type: "string", enum: ["low", "medium", "high"] },
    expected: "low",
  },
  {
    key: "reasoning_budget_tokens",
    schema: { type: "integer", minimum: 1 },
    expected: 512,
  },
])(
  "session enabling thinking prefills $key through the shared policy",
  async ({ key, schema, expected }) => {
    api.getConversationModelPreferences.mockResolvedValue({
      version: 1,
      parameter_values: {},
      defaults: { enable_thinking: false },
      output_limit: 1024,
      field_specs: [
        { ...rule("enable_thinking"), schema: { type: "boolean" } },
        {
          ...rule(key),
          schema,
          condition: { key: "enable_thinking", op: "eq", value: true },
        },
      ],
      issues: [],
    });
    setup(<ConversationModelParameters conversationId={11} modelId={42} />);
    const toggle = await screen.findByRole("switch");
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(api.patchConversationModelPreferences).toHaveBeenCalledWith(
        11,
        42,
        {
          expected_version: 1,
          parameter_values: { enable_thinking: true, [key]: expected },
          delete_parameters: [],
        }
      )
    );
  }
);

it("Agent always-on reasoning still exposes its declared effort without inventing a toggle", async () => {
  api.getModelOutlet.mockResolvedValue({
    config_revision: 1,
    profile: {
      parameter_values: { enable_thinking: true, reasoning_effort: "low" },
      parameter_rules: [
        {
          ...rule("reasoning_effort"),
          schema: { type: "string", enum: ["low", "high"] },
        },
      ],
      capabilities: { context: { combined_window: 8192, output_limit: 1024 } },
    },
  });
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{}}
      onApply={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(
    await screen.findByRole("combobox", { name: "modelProfile.thinkingDegree" })
  ).toBeEnabled();
  expect(screen.getByRole("switch")).toBeChecked();
  expect(screen.getByRole("switch")).toBeDisabled();
});

it("restores inherited Agent thinking by clearing only the thinking overrides", async () => {
  const apply = vi.fn();
  api.getModelOutlet.mockResolvedValue({
    config_revision: 1,
    profile: {
      parameter_values: { enable_thinking: false },
      parameter_rules: [
        { ...rule("enable_thinking"), schema: { type: "boolean" } },
        {
          ...rule("reasoning_budget_tokens"),
          schema: { type: "integer", minimum: 1 },
          condition: { key: "enable_thinking", op: "eq", value: true },
        },
      ],
      capabilities: { context: { combined_window: 8192, output_limit: 1024 } },
    },
  });
  setup(
    <AgentModelParameters
      modelId={42}
      name="Model"
      value={{
        parameter_values: {
          enable_thinking: true,
          reasoning_budget_tokens: 256,
        },
      }}
      onApply={apply}
      onClose={vi.fn()}
    />
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "modelProfile.useOutletDefault" })
  );
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.getByRole("switch")).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(apply).toHaveBeenCalledWith({ parameter_values: {} })
  );
});


it("SCB-02 session advanced settings omit length limits while retaining sampling", async () => {
  api.getConversationModelPreferences.mockResolvedValue({version:1,parameter_values:{},defaults:{temperature:.6,top_p:.9,max_output_tokens:1024},field_specs:[rule("temperature"),rule("top_p"),rule("max_output_tokens"),rule("context_window_tokens")],issues:[]});
  setup(<ConversationModelParameters conversationId={11} modelId={42}/>);
  const advanced=await screen.findByRole("button",{name:"workbench.controls.advanced"});
  await waitFor(()=>expect(advanced).toBeEnabled());fireEvent.click(advanced);
  const temperature = await screen.findByRole("spinbutton",{name:"workbench.controls.temperature"});
  await waitFor(() => expect(temperature).toBeVisible());
  expect(screen.queryByRole("spinbutton",{name:"max_output_tokens"})).not.toBeInTheDocument();
  expect(screen.queryByRole("spinbutton",{name:"context_window_tokens"})).not.toBeInTheDocument();
});

it("SCB-01 model trigger summary reflects effective Agent/session reasoning values", async () => {
  api.getConversationModelPreferences.mockResolvedValue({version:1,parameter_values:{reasoning_effort:"high"},defaults:{enable_thinking:true,reasoning_effort:"low"},field_specs:[{...rule("reasoning_effort"),schema:{type:"string",enum:["low","medium","high"]}}],issues:[]});
  setup(<ConversationModelParameterSummary conversationId={11} modelId={42} agentDefaults={{reasoning_effort:"medium"}}/>);
  expect(await screen.findByText("modelProfile.thinkingLevel.high")).toBeVisible();
});

it("SYNC-02 shows a degree-only profile in session controls without writing a synthetic toggle", async () => {
  api.getConversationModelPreferences.mockResolvedValue({
    version: 1,
    parameter_values: { reasoning_effort: "high" },
    defaults: { reasoning_effort: "low" },
    issues: [],
    field_specs: [
      {
        ...rule("reasoning_effort"),
        schema: { type: "string", enum: ["low", "high"] },
      },
    ],
  });
  setup(<ConversationModelParameters conversationId={11} modelId={42} />);
  const effort = await screen.findByRole("combobox", {
    name: "chat.modelSelector.reasoningEffort",
  });
  await waitFor(() => expect(effort).toBeEnabled());
  expect(screen.getByRole("switch")).toBeChecked();
  expect(screen.getByRole("switch")).toBeDisabled();
  fireEvent.mouseDown(effort);
  fireEvent.click(
    await screen.findByText("modelProfile.thinkingLevel.low")
  );
  await waitFor(() =>
    expect(api.patchConversationModelPreferences).toHaveBeenCalledWith(11, 42, {
      expected_version: 1,
      parameter_values: { reasoning_effort: "low" },
      delete_parameters: [],
    })
  );
});

it("SYNC-02 restores the degree-only profile summary from saved session parameters", async () => {
  api.getConversationModelPreferences.mockResolvedValue({
    version: 1,
    parameter_values: { reasoning_effort: "high" },
    defaults: { reasoning_effort: "low" },
    issues: [],
    field_specs: [
      {
        ...rule("reasoning_effort"),
        schema: { type: "string", enum: ["low", "high"] },
      },
    ],
  });
  setup(<ConversationModelParameterSummary conversationId={11} modelId={42} />);
  expect(
    await screen.findByText("modelProfile.thinkingLevel.high")
  ).toBeVisible();
});
