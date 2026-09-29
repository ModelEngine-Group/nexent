import React, { useEffect, useState } from "react";
import type { TFunction } from "i18next";

import {
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Slider,
  Switch,
  Tooltip,
} from "antd";
import type { FormInstance } from "antd";
import { DownOutlined, QuestionCircleOutlined } from "@ant-design/icons";

import { AIDP_KNOWLEDGE_BASE_NAME_PATTERN } from "@/const/knowledgeBase";
import { AidpKnowledgeBasePermissionFields } from "./AidpKnowledgeBaseModalParts";
import type { AidpGroupOption } from "../hooks/useAidpGroupOptions";

const GRAPH_PROMPT_MAX_BYTES = 2048;
const CHUNK_TOKEN_MIN = 256;
const CHUNK_TOKEN_MAX = 4096;
const OVERLAP_PERCENT_MAX = 50;

const byteLength = (value: string): number =>
  typeof TextEncoder === "undefined"
    ? value.length
    : new TextEncoder().encode(value).length;

interface AidpCreateKbSectionsProps {
  form: FormInstance;
  t: TFunction;
  canConfigureGroupPermissions: boolean;
  groupOptions: AidpGroupOption[];
  ingroupPermission?: string;
  llmModelOptions: string[];
  llmModelsLoading: boolean;
  vlmModelOptions: string[];
  vlmModelsLoading: boolean;
  embeddingModelOptions: string[];
  embeddingModelsLoading: boolean;
}

interface SliderNumberFieldProps {
  value?: number | null;
  onChange?: (value: number | null) => void;
  min: number;
  max: number;
  step: number;
  unit?: string;
  precision?: number;
  marks: Record<number, string>;
  ariaLabel: string;
}

const SliderNumberField: React.FC<SliderNumberFieldProps> = ({
  value,
  onChange,
  min,
  max,
  step,
  unit,
  precision,
  marks,
  ariaLabel,
}) => {
  const safeValue = typeof value === "number" ? value : min;
  return (
    <div className="w-full">
      <div className="flex w-full items-center gap-4">
        <Slider
          className="min-w-0 flex-1"
          min={min}
          max={max}
          step={step}
          value={safeValue}
          tooltip={{
            formatter: (sliderValue) => `${sliderValue}${unit || ""}`,
          }}
          onChange={(nextValue) => onChange?.(nextValue)}
          aria-label={ariaLabel}
        />
        <div className="flex w-[112px] shrink-0 items-center gap-2">
          <InputNumber
            aria-label={ariaLabel}
            className="w-full"
            min={min}
            max={max}
            step={step}
            precision={precision}
            controls={false}
            value={value}
            onChange={onChange}
          />
          {unit && (
            <span className="shrink-0 text-xs text-gray-500">{unit}</span>
          )}
        </div>
      </div>
      <div className="mt-1 flex justify-between text-xs text-gray-500">
        <span>{marks[min]}</span>
        <span>{marks[max]}</span>
      </div>
    </div>
  );
};

type CollapsibleSection = "graph" | "chunk" | "vector" | "retrieval";

const AidpCreateKbSections: React.FC<AidpCreateKbSectionsProps> = ({
  form,
  t,
  canConfigureGroupPermissions,
  groupOptions,
  ingroupPermission,
  llmModelOptions,
  llmModelsLoading,
  vlmModelOptions,
  vlmModelsLoading,
  embeddingModelOptions,
  embeddingModelsLoading,
}) => {
  const graphEnabled = Form.useWatch("is_exist_graph", form) === true;
  const captionEnabled = Form.useWatch("caption_enable", form) === true;
  const chunkMode = Form.useWatch("chunk_mode", form);
  const [expanded, setExpanded] = useState<Record<CollapsibleSection, boolean>>(
    {
      graph: false,
      chunk: true,
      vector: true,
      retrieval: true,
    }
  );

  useEffect(() => {
    if (graphEnabled) {
      setExpanded((current) => ({ ...current, graph: true }));
    }
  }, [graphEnabled]);

  const toggleSection = (section: CollapsibleSection) =>
    setExpanded((current) => ({ ...current, [section]: !current[section] }));

  const label = (text: string, hint?: string) => (
    <span className="inline-flex items-center gap-1.5">
      <span>{text}</span>
      {hint && (
        <Tooltip title={hint}>
          <QuestionCircleOutlined
            className="cursor-help text-gray-400"
            aria-label={hint}
          />
        </Tooltip>
      )}
    </span>
  );

  const sectionHeading = (
    section: CollapsibleSection,
    title: string,
    hint?: string,
    action?: React.ReactNode
  ) => {
    const isGraph = section === "graph";
    const isExpanded = expanded[section];
    const disabled = isGraph && !graphEnabled;
    const panelId = `aidp-create-${section}-panel`;

    return (
      <div className="flex min-h-8 items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            className="flex h-7 items-center gap-2 rounded px-1 text-left text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-400"
            aria-expanded={isExpanded && !disabled}
            aria-controls={panelId}
            aria-label={
              isExpanded
                ? t("aidpKnowledge.createCollapseSection", { section: title })
                : t("aidpKnowledge.createExpandSection", { section: title })
            }
            disabled={disabled}
            onClick={() => toggleSection(section)}
          >
            <DownOutlined
              className={`text-xs transition-transform ${isExpanded ? "" : "-rotate-90"}`}
            />
            <span>{title}</span>
          </button>
          {hint && (
            <Tooltip title={hint}>
              <QuestionCircleOutlined className="cursor-help text-gray-400" />
            </Tooltip>
          )}
        </div>
        {action}
      </div>
    );
  };

  const sectionHint = (
    <p className="mb-4 mt-1 text-xs text-gray-500">
      {t("aidpKnowledge.createDefaultsHint")}
    </p>
  );

  return (
    <Form form={form} layout="vertical" className="w-full">
      <section className="border-b border-gray-200 pb-6 pt-2">
        <h3 className="mb-4 text-sm font-semibold text-gray-800">
          {t("aidpKnowledge.createSectionBasic")}
        </h3>
        <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
          <Form.Item
            name="name"
            label={t("aidpKnowledge.kbName")}
            className="md:col-span-2"
            rules={[
              { required: true, message: t("aidpKnowledge.kbNameRequired") },
              {
                pattern: AIDP_KNOWLEDGE_BASE_NAME_PATTERN,
                message: t("aidpKnowledge.kbNameInvalid"),
              },
            ]}
          >
            <Input
              maxLength={255}
              showCount
              placeholder={t("aidpKnowledge.kbNamePlaceholder")}
            />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("aidpKnowledge.kbDescription")}
            className="md:col-span-2"
            rules={[
              {
                required: true,
                whitespace: true,
                message: t("aidpKnowledge.kbDescriptionRequired"),
              },
            ]}
          >
            <Input.TextArea
              rows={3}
              maxLength={255}
              showCount
              placeholder={t("aidpKnowledge.kbDescriptionPlaceholder")}
            />
          </Form.Item>
          {canConfigureGroupPermissions && (
            <>
              <div className="mb-2 mt-1 text-xs font-medium text-gray-500 md:col-span-2">
                {t("aidpKnowledge.createSectionPermission")}
              </div>
              <AidpKnowledgeBasePermissionFields
                t={t}
                groupOptions={groupOptions}
                ingroupPermission={ingroupPermission}
              />
            </>
          )}
        </div>
      </section>

      <section className="border-b border-gray-200 py-5">
        <div className="flex min-h-8 items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-gray-800">
              {t("aidpKnowledge.createSectionSafety")}
            </h3>
            <Tooltip title={t("aidpKnowledge.createSafetyGuardHint")}>
              <QuestionCircleOutlined
                className="cursor-help text-gray-400"
                aria-label={t("aidpKnowledge.createSafetyGuardHint")}
              />
            </Tooltip>
          </div>
          <Form.Item
            name="sensitive_intercept_enalbe"
            valuePropName="checked"
            noStyle
          >
            <Switch aria-label={t("aidpKnowledge.createSafetyGuard")} />
          </Form.Item>
        </div>
      </section>

      <section className="border-b border-gray-200 py-5">
        {sectionHeading(
          "graph",
          t("aidpKnowledge.createSectionGraph"),
          t("aidpKnowledge.createGraphEnableHint"),
          <Form.Item name="is_exist_graph" valuePropName="checked" noStyle>
            <Switch aria-label={t("aidpKnowledge.createGraphEnable")} />
          </Form.Item>
        )}
        <div
          id="aidp-create-graph-panel"
          hidden={!expanded.graph || !graphEnabled}
        >
          {graphEnabled && sectionHint}
          <div className="mt-5 grid grid-cols-1 gap-x-6 md:grid-cols-2">
            {graphEnabled && (
              <>
                <Form.Item
                  name="graph_domain"
                  label={t("aidpKnowledge.createGraphDomain")}
                  className="md:col-span-2"
                >
                  <Select
                    options={[
                      {
                        value: "general",
                        label: t("aidpKnowledge.createGraphDomainGeneral"),
                      },
                      {
                        value: "medical",
                        label: t("aidpKnowledge.createGraphDomainMedical"),
                      },
                      {
                        value: "finance",
                        label: t("aidpKnowledge.createGraphDomainFinance"),
                      },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="graph_topk"
                  label={label(
                    t("aidpKnowledge.createGraphTopk"),
                    t("aidpKnowledge.createGraphTopkHint")
                  )}
                  rules={[{ type: "number", min: 1, max: 100 }]}
                >
                  <InputNumber style={{ width: "100%" }} min={1} max={100} />
                </Form.Item>
                <Form.Item
                  name="graph_hop"
                  label={t("aidpKnowledge.createGraphHop")}
                  rules={[{ type: "number", min: 1, max: 3 }]}
                >
                  <InputNumber style={{ width: "100%" }} min={1} max={3} />
                </Form.Item>
                <Form.Item
                  name="graph_thinking"
                  label={t("aidpKnowledge.createGraphThinking")}
                >
                  <Select
                    options={[
                      { value: false, label: t("aidpKnowledge.createNo") },
                      { value: true, label: t("aidpKnowledge.createYes") },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="graph_prompt_language"
                  label={t("aidpKnowledge.createGraphPromptLanguage")}
                >
                  <Select
                    options={[
                      {
                        value: "chinese",
                        label: t("aidpKnowledge.createGraphPromptZh"),
                      },
                      {
                        value: "english",
                        label: t("aidpKnowledge.createGraphPromptEn"),
                      },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="graph_prompt_text"
                  label={label(
                    t("aidpKnowledge.createGraphPromptText"),
                    t("aidpKnowledge.createGraphPromptHint")
                  )}
                  className="md:col-span-2"
                  rules={[
                    {
                      validator: (_rule, value: string) =>
                        byteLength(value || "") <= GRAPH_PROMPT_MAX_BYTES
                          ? Promise.resolve()
                          : Promise.reject(
                              new Error(
                                t("aidpKnowledge.createGraphPromptTooLong")
                              )
                            ),
                    },
                  ]}
                >
                  <Input.TextArea rows={6} />
                </Form.Item>
                <Form.Item
                  name="graph_synonym_merge"
                  label={t("aidpKnowledge.createGraphSynonymMerge")}
                >
                  <Select
                    options={[
                      { value: false, label: t("aidpKnowledge.createNo") },
                      { value: true, label: t("aidpKnowledge.createYes") },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="graph_disambiguation"
                  label={t("aidpKnowledge.createGraphDisambiguation")}
                >
                  <Select
                    options={[
                      { value: false, label: t("aidpKnowledge.createNo") },
                      { value: true, label: t("aidpKnowledge.createYes") },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="llm_model_name"
                  label={label(
                    t("aidpKnowledge.createGraphModel"),
                    t("aidpKnowledge.createGraphModelHint")
                  )}
                  className="md:col-span-2"
                  rules={[
                    {
                      required: true,
                      message: t("aidpKnowledge.createGraphModelRequired"),
                    },
                  ]}
                >
                  <Select
                    showSearch
                    allowClear
                    loading={llmModelsLoading}
                    notFoundContent={
                      llmModelsLoading
                        ? t("aidpKnowledge.createModelLoading")
                        : t("aidpKnowledge.createModelNone")
                    }
                    placeholder={t("aidpKnowledge.createModelSearch")}
                    options={llmModelOptions.map((name) => ({
                      label: name,
                      value: name,
                    }))}
                  />
                </Form.Item>
              </>
            )}
          </div>
        </div>
      </section>

      <section className="border-b border-gray-200 py-5">
        {sectionHeading("chunk", t("aidpKnowledge.createSectionChunk"))}
        <div id="aidp-create-chunk-panel" hidden={!expanded.chunk}>
          {sectionHint}
          <div className="mb-5">
            <Form.Item
              name="chunk_mode"
              label={t("aidpKnowledge.createChunkMode")}
              rules={[{ required: true }]}
            >
              <Radio.Group className="w-full">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Radio
                    value={0}
                    className={`!m-0 rounded-md border p-4 ${chunkMode === 0 ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-blue-400"}`}
                  >
                    <span className="font-medium text-gray-800">
                      {t("aidpKnowledge.createChunkModeSmart")}
                    </span>
                    <span className="mt-1 block pl-6 text-xs leading-5 text-gray-500">
                      {t("aidpKnowledge.createChunkModeSmartHint")}
                    </span>
                  </Radio>
                  <Radio
                    value={1}
                    className={`!m-0 rounded-md border p-4 ${chunkMode === 1 ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-blue-400"}`}
                  >
                    <span className="font-medium text-gray-800">
                      {t("aidpKnowledge.createChunkModeLegal")}
                    </span>
                    <span className="mt-1 block pl-6 text-xs leading-5 text-gray-500">
                      {t("aidpKnowledge.createChunkModeLegalHint")}
                    </span>
                  </Radio>
                </div>
              </Radio.Group>
            </Form.Item>
          </div>
          <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
            <Form.Item
              name="chunk_token_num"
              label={t("aidpKnowledge.createChunkTokenNum")}
              rules={[
                {
                  required: true,
                  message: t("aidpKnowledge.createChunkTokenNumRequired"),
                },
                {
                  type: "number",
                  min: CHUNK_TOKEN_MIN,
                  max: CHUNK_TOKEN_MAX,
                  message: t("aidpKnowledge.createChunkTokenNumRange", {
                    min: CHUNK_TOKEN_MIN,
                    max: CHUNK_TOKEN_MAX,
                  }),
                },
              ]}
            >
              <SliderNumberField
                min={CHUNK_TOKEN_MIN}
                max={CHUNK_TOKEN_MAX}
                step={1}
                unit="Token"
                marks={{
                  [CHUNK_TOKEN_MIN]: String(CHUNK_TOKEN_MIN),
                  [CHUNK_TOKEN_MAX]: String(CHUNK_TOKEN_MAX),
                }}
                ariaLabel={t("aidpKnowledge.createChunkTokenNum")}
              />
            </Form.Item>
            <Form.Item
              name="chunk_overlap_percent"
              label={label(
                t("aidpKnowledge.createOverlapPercent"),
                t("aidpKnowledge.createOverlapPercentHint")
              )}
              rules={[
                {
                  required: true,
                  message: t("aidpKnowledge.createOverlapPercentRequired"),
                },
                {
                  type: "number",
                  min: 0,
                  max: OVERLAP_PERCENT_MAX,
                  message: t("aidpKnowledge.createOverlapPercentRange", {
                    max: OVERLAP_PERCENT_MAX,
                  }),
                },
              ]}
            >
              <SliderNumberField
                min={0}
                max={OVERLAP_PERCENT_MAX}
                step={0.5}
                unit="%"
                precision={1}
                marks={{
                  0: "0%",
                  [OVERLAP_PERCENT_MAX]: `${OVERLAP_PERCENT_MAX}%`,
                }}
                ariaLabel={t("aidpKnowledge.createOverlapPercent")}
              />
            </Form.Item>
          </div>
        </div>
      </section>

      <section className="border-b border-gray-200 py-5">
        {sectionHeading("vector", t("aidpKnowledge.createSectionVector"))}
        <div id="aidp-create-vector-panel" hidden={!expanded.vector}>
          {sectionHint}
          <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
            <Form.Item
              name="embedding_model"
              label={t("aidpKnowledge.createEmbeddingModel")}
              rules={[{ required: true }]}
            >
              <Select
                showSearch
                loading={embeddingModelsLoading}
                notFoundContent={
                  embeddingModelsLoading
                    ? t("aidpKnowledge.createModelLoading")
                    : t("aidpKnowledge.createModelNone")
                }
                options={embeddingModelOptions.map((name) => ({
                  label: name,
                  value: name,
                }))}
              />
            </Form.Item>
            <div className="min-w-0">
              <div className="mb-2 flex h-8 items-center justify-between gap-3">
                <label
                  htmlFor="aidp-create-vlm-model"
                  className="flex items-center gap-2 text-sm text-gray-800"
                >
                  {t("aidpKnowledge.createVlmModel")}
                  <Tooltip title={t("aidpKnowledge.createCaptionEnableHint")}>
                    <QuestionCircleOutlined
                      className="cursor-help text-gray-400"
                      aria-label={t("aidpKnowledge.createCaptionEnableHint")}
                    />
                  </Tooltip>
                </label>
                <Form.Item
                  name="caption_enable"
                  valuePropName="checked"
                  noStyle
                >
                  <Switch aria-label={t("aidpKnowledge.createCaptionEnable")} />
                </Form.Item>
              </div>
              <Form.Item
                name="vlm_model"
                rules={[
                  {
                    required: captionEnabled,
                    message: t("aidpKnowledge.createVlmModelRequired"),
                  },
                ]}
              >
                <Select
                  id="aidp-create-vlm-model"
                  showSearch
                  allowClear
                  disabled={!captionEnabled}
                  loading={vlmModelsLoading}
                  notFoundContent={
                    vlmModelsLoading
                      ? t("aidpKnowledge.createModelLoading")
                      : t("aidpKnowledge.createModelNone")
                  }
                  placeholder={t("aidpKnowledge.createModelSearch")}
                  options={vlmModelOptions.map((name) => ({
                    label: name,
                    value: name,
                  }))}
                />
              </Form.Item>
            </div>
          </div>
        </div>
      </section>

      <section className="py-5">
        {sectionHeading("retrieval", t("aidpKnowledge.createSectionRetrieval"))}
        <div id="aidp-create-retrieval-panel" hidden={!expanded.retrieval}>
          {sectionHint}
          <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
            <Form.Item
              name="similarity"
              label={t("aidpKnowledge.createSimilarity")}
              rules={[{ required: true, type: "number", min: 0, max: 1 }]}
            >
              <SliderNumberField
                min={0}
                max={1}
                step={0.01}
                precision={2}
                marks={{ 0: "0", 1: "1" }}
                ariaLabel={t("aidpKnowledge.createSimilarity")}
              />
            </Form.Item>
            <Form.Item
              name="topk"
              label={t("aidpKnowledge.createTopk")}
              rules={[{ required: true, type: "number", min: 1, max: 100 }]}
            >
              <SliderNumberField
                min={1}
                max={100}
                step={1}
                marks={{ 1: "1", 100: "100" }}
                ariaLabel={t("aidpKnowledge.createTopk")}
              />
            </Form.Item>
          </div>
        </div>
      </section>
    </Form>
  );
};

export default AidpCreateKbSections;
