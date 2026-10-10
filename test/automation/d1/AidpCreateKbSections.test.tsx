import React from "react";
import { Form } from "antd";
import type { FormInstance } from "antd";
import type { TFunction } from "i18next";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import AidpCreateKbSections from "@/ext_components/aidp/components/AidpCreateKbSections";
import zh from "@/public/locales/zh/common.json";
import { parseAidpGraphTemplate } from "@/lib/aidpGraphConfig";

const hints = [
  "createChunkSectionHint",
  "createChunkTokenHint",
  "createOverlapPercentHint",
  "createVectorSectionHint",
  "createEmbeddingHint",
  "createCaptionEnableHint",
  "createRetrievalSectionHint",
  "createSimilarityHint",
  "createTopkHint",
  "createGraphSectionHint",
  "createGraphModelHint",
  "createGraphHopHint",
  "createGraphThinkingHint",
  "createGraphLanguageHint",
  "createGraphDomainHint",
  "createGraphPromptHint",
  "createGraphSynonymHint",
  "createGraphDisambiguationHint",
];
const t = ((key: string) =>
  (zh as Record<string, string>)[key] || key) as TFunction;
const entries = [
  ["retrieve_subgraph_hop", "2", "^[1-3]$"],
  ["no_think_mode", "是", "^(是|否)$"],
  ["prompt_language", "中文", "^(中文|英文)$"],
  ["domain", "常规", "^(医疗|金融|常规|法律法规)$"],
  ["prompt_text", "提取实体", "^[\\s\\S]{1,4096}$"],
  ["synonym_merge_enable", "否", "^(是|否)$"],
  ["disambiguation_enable", "否", "^(是|否)$"],
];
const template = parseAidpGraphTemplate({
  value: entries.map(([param_key, param_value, regexp]) => ({
    param_key,
    param_value,
    regexp,
    param_name: param_key,
    param_desc: "",
    is_modifiable: true,
  })),
});

describe("AKPR-D1-011 real creation controls and tooltip copy", () => {
  it("renders all 18 localized hints and enforces the server character constraint", async () => {
    let form: FormInstance;
    function Wrapper() {
      const [instance] = Form.useForm();
      form = instance;
      return (
        <AidpCreateKbSections
          form={instance}
          t={t}
          canConfigureGroupPermissions={false}
          groupOptions={[]}
          llmModelOptions={[]}
          llmModelsLoading={false}
          vlmModelOptions={[]}
          vlmModelsLoading={false}
          embeddingModelOptions={[]}
          embeddingModelsLoading={false}
          graphTemplate={template}
          onRestorePrompt={() => {}}
        />
      );
    }
    render(<Wrapper />);
    await act(async () => {
      form.setFieldsValue({
        graph_prompt_text: "提取实体",
        graph_domain: "常规",
        graph_prompt_language: "中文",
        graph_thinking: false,
      });
    });
    await userEvent
      .setup()
      .click(
        screen.getByRole("switch", {
          name: t("aidpKnowledge.createGraphEnable"),
        }),
      );
    for (const hint of hints)
      expect(
        screen.getByLabelText(t(`aidpKnowledge.${hint}`)),
      ).toBeInTheDocument();
    expect(
      document.getElementById("aidp-create-graph-panel"),
    ).not.toHaveTextContent(t("aidpKnowledge.createGraphTopk"));
    await act(async () => {
      form.setFieldValue("graph_prompt_text", "字😀".repeat(2048));
    });
    await expect(
      form!.validateFields(["graph_prompt_text"]),
    ).resolves.toMatchObject({ graph_prompt_text: "字😀".repeat(2048) });
    await act(async () => {
      form.setFieldValue("graph_prompt_text", "字".repeat(4097));
    });
    await expect(
      form!.validateFields(["graph_prompt_text"]),
    ).rejects.toHaveProperty("errorFields");
    await act(async () => {
      form.setFieldValue("graph_prompt_text", "");
    });
    await expect(
      form!.validateFields(["graph_prompt_text"]),
    ).rejects.toHaveProperty("errorFields");
  });
});
