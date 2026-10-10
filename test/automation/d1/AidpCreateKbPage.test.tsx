import React from "react";
import type { FormInstance } from "antd";
import { App } from "antd";
import type { AidpModelOption } from "@/types/aidpGraph";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AidpCreateKbPage from "@/ext_components/aidp/components/AidpCreateKbPage";
import {
  graphChoices,
  graphBoolean,
  parseAidpGraphTemplate,
} from "@/lib/aidpGraphConfig";

const api = vi.hoisted(() => ({
  listModels: vi.fn(),
  graphTemplate: vi.fn(),
  createKb: vi.fn(),
  push: vi.fn(),
}));
vi.mock("@/ext_components/aidp/services/aidpKnowledgeService", () => ({
  default: api,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: api.push, replace: vi.fn() }),
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ enableAidpKnowledge: true, isDeploymentReady: true }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "admin", tenantId: "tenant" },
  }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: { groups: [] } }),
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

// Keep Ant Design's real form state and validation while isolating visual controls.
interface SectionsHarnessProps {
  form: FormInstance;
  embeddingModelOptions: AidpModelOption[];
  llmModelOptions: AidpModelOption[];
  vlmModelOptions: AidpModelOption[];
  onRestorePrompt: () => void;
}

vi.mock("@/ext_components/aidp/components/AidpCreateKbSections", async () => {
  const { Form, Input, Switch } = await import("antd");
  return {
    default: (props: SectionsHarnessProps) => (
      <Form form={props.form}>
        <Form.Item name="name">
          <Input aria-label="name" />
        </Form.Item>
        <Form.Item name="embedding_model">
          <select aria-label="embedding">
            {props.embeddingModelOptions.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Form.Item>
        <Form.Item name="llm_model_name">
          <select aria-label="llm">
            {props.llmModelOptions.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Form.Item>
        <Form.Item name="vlm_model">
          <select aria-label="vlm">
            {props.vlmModelOptions.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </Form.Item>
        <Form.Item name="is_exist_graph" valuePropName="checked">
          <Switch aria-label="graph" />
        </Form.Item>
        <Form.Item name="caption_enable" valuePropName="checked">
          <Switch aria-label="caption" />
        </Form.Item>
        <Form.Item name="graph_domain">
          <select aria-label="domain">
            <option value="常规">General</option>
            <option value="金融">Finance</option>
          </select>
        </Form.Item>
        <Form.Item name="graph_prompt_language">
          <select aria-label="language">
            <option value="中文">Chinese</option>
            <option value="英文">English</option>
          </select>
        </Form.Item>
        <Form.Item name="graph_prompt_text">
          <Input aria-label="prompt" />
        </Form.Item>
        <button type="button" onClick={props.onRestorePrompt}>
          restore
        </button>
      </Form>
    ),
  };
});

function template(language = "chinese") {
  const entries = [
    ["retrieve_subgraph_hop", "2", "^[1-3]$"],
    ["no_think_mode", "是", "^(是|否)$"],
    [
      "prompt_language",
      language === "english" ? "英文" : "中文",
      "^(中文|英文)$",
    ],
    ["domain", "常规", "^(医疗|金融|常规|法律法规)$"],
    ["prompt_text", `${language} general`, "^[\\s\\S]{1,4096}$"],
    ["synonym_merge_enable", "否", "^(是|否)$"],
    ["disambiguation_enable", "否", "^(是|否)$"],
  ];
  return parseAidpGraphTemplate({
    value: entries.map(([param_key, param_value, regexp]) => ({
      param_key,
      param_value,
      regexp,
      param_name: param_key,
      param_desc: "",
      is_modifiable: true,
      ...(param_key === "prompt_text"
        ? {
            template: {
              常规: `${language} general`,
              金融: `${language} finance`,
            },
          }
        : {}),
    })),
  });
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App>
        <AidpCreateKbPage />
      </App>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.listModels.mockResolvedValue({
    models: [
      {
        model_name: "/models/embed",
        display_name: "bge-m3",
        model_type: "embedding",
      },
      { model_name: "graph-llm", display_name: "Graph LLM", model_type: "llm" },
      {
        model_name: "caption-vlm",
        display_name: "Caption VLM",
        model_type: "vlm",
      },
    ],
  });
  api.graphTemplate.mockImplementation(async (language) => template(language));
  api.createKb.mockResolvedValue({ kds_id: "new-kb" });
});

describe("AKPR-D1-011 unified model query and graph templates", () => {
  it("loads all three categories once, displays labels and submits model identifiers", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByRole("option", { name: "bge-m3" });
    await waitFor(() =>
      expect(screen.getByLabelText("embedding")).toHaveValue("/models/embed"),
    );
    expect(api.listModels).toHaveBeenCalledExactlyOnceWith("", "KnowledgeBase");
    expect(api.graphTemplate).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("name"), "资料库");
    await user.click(screen.getByLabelText("graph"));
    await waitFor(() =>
      expect(screen.getByLabelText("prompt")).toHaveValue("chinese general"),
    );
    await user.click(screen.getByText("aidpKnowledge.createSubmit"));
    await waitFor(() => expect(api.createKb).toHaveBeenCalledOnce());
    const body = api.createKb.mock.calls[0][0];
    expect(body.embedding_model).toBe("/models/embed");
    expect(body.graph_config).toEqual({
      domain: "常规",
      retrieve_subgraph_hop: "2",
      no_think_mode: "是",
      prompt_language: "中文",
      prompt_text: "chinese general",
      synonym_merge_enable: "否",
      disambiguation_enable: "否",
      llm_model_name: "graph-llm",
    });
    expect(body.topk).toBe(10);
    expect(body.similarity).toBe(0.6);
    expect(body.vlm_model).toBe("");
    expect(body).not.toHaveProperty("smartsplit");
  });

  it("switches server templates by domain and language, preserves manual text and restores on request", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByRole("option", { name: "bge-m3" });
    await user.click(screen.getByLabelText("graph"));
    await waitFor(() =>
      expect(screen.getByLabelText("prompt")).toHaveValue("chinese general"),
    );
    await user.selectOptions(screen.getByLabelText("domain"), "金融");
    await waitFor(() =>
      expect(screen.getByLabelText("prompt")).toHaveValue("chinese finance"),
    );
    await user.clear(screen.getByLabelText("prompt"));
    await user.type(screen.getByLabelText("prompt"), "手工提示词");
    await user.selectOptions(screen.getByLabelText("language"), "英文");
    await waitFor(() =>
      expect(api.graphTemplate).toHaveBeenCalledWith("english"),
    );
    expect(screen.getByLabelText("prompt")).toHaveValue("手工提示词");
    await user.click(screen.getByText("restore"));
    expect(screen.getByLabelText("prompt")).toHaveValue("english finance");
  });

  it("omits hidden graph and VLM selections after disabling both capabilities", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByRole("option", { name: "bge-m3" });
    await user.type(screen.getByLabelText("name"), "资料库");
    await user.click(screen.getByLabelText("graph"));
    await waitFor(() =>
      expect(screen.getByLabelText("prompt")).toHaveValue("chinese general"),
    );
    await user.click(screen.getByLabelText("graph"));
    await user.click(screen.getByLabelText("caption"));
    await user.click(screen.getByLabelText("caption"));
    await user.click(screen.getByText("aidpKnowledge.createSubmit"));
    await waitFor(() => expect(api.createKb).toHaveBeenCalledOnce());
    expect(api.createKb.mock.calls[0][0].graph_config).toBeUndefined();
    expect(api.createKb.mock.calls[0][0].vlm_model).toBe("");
  });

  it("blocks submission if the graph template fails to load", async () => {
    api.graphTemplate.mockRejectedValue(new Error("unavailable"));
    const user = userEvent.setup();
    mount();
    await screen.findByRole("option", { name: "bge-m3" });
    await user.click(screen.getByLabelText("graph"));
    await screen.findByText("unavailable");
    expect(
      screen.getByText("aidpKnowledge.createSubmit").closest("button"),
    ).toBeDisabled();
    expect(api.createKb).not.toHaveBeenCalled();
  });

  it("validates complete templates and reads Chinese choices and booleans", () => {
    expect(graphChoices(template(), "domain")).toEqual([
      "医疗",
      "金融",
      "常规",
      "法律法规",
    ]);
    expect(() => parseAidpGraphTemplate({ value: [] })).toThrow();
    expect(graphBoolean("否")).toBe(false);
    expect(graphBoolean("是")).toBe(true);
    expect(graphBoolean(undefined)).toBeUndefined();
  });
});
