import React, { useEffect, useState } from "react";
import type { TFunction } from "i18next";

import {
  Alert,
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
import styles from "./AidpCreateKbSections.module.css";
import type { AidpGroupOption } from "../hooks/useAidpGroupOptions";

const GRAPH_PROMPT_MAX_BYTES = 2048;
const CHUNK_TOKEN_MIN = 256;
const CHUNK_TOKEN_MAX = 4096;
const OVERLAP_PERCENT_MIN = 1;
const OVERLAP_PERCENT_MAX = 40;

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
      <div className="flex w-full items-start gap-4">
        <div className={styles.sliderTrackGroup}>
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
          <div className={styles.sliderMarks}>
            <span>{marks[min]}</span>
            <span>{marks[max]}</span>
          </div>
        </div>
        <div className={styles.sliderValueGroup}>
          <InputNumber
            aria-label={ariaLabel}
            className={styles.sliderValueInput}
            min={min}
            max={max}
            step={step}
            precision={precision}
            controls={false}
            value={value}
            onChange={onChange}
          />
          <span className={styles.sliderUnit}>{unit || ""}</span>
        </div>
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
      // The graph toggle lives in the Ant Design form, so sync its enabled state
      // to the independent accordion UI when a form value is loaded.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setExpanded((current) => ({ ...current, graph: true }));
    }
  }, [graphEnabled]);

  const toggleSection = (section: CollapsibleSection) =>
    setExpanded((current) => ({ ...current, [section]: !current[section] }));

  const label = (text: string, hint?: string) => (
    <span className={styles.formLabel}>
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
      <div className={styles.sectionHeading}>
        <div className={styles.sectionHeadingTitle}>
          <button
            type="button"
            className="flex h-9 items-center gap-2 rounded px-1 text-left text-lg font-semibold leading-7 text-gray-800 hover:bg-gray-50 disabled:cursor-not-allowed"
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
        {action && <div className={styles.sectionAction}>{action}</div>}
      </div>
    );
  };

  const sectionHint = (
    <Alert
      className={styles.infoBanner}
      type="info"
      showIcon
      message={t("aidpKnowledge.createGraphEnableHint")}
    />
  );

  return (
    <Form form={form} layout="vertical" className={styles.createForm}>
      <Alert
        className={`${styles.infoBanner} ${styles.createIntro}`}
        type="info"
        showIcon
        closable
        message={t("aidpKnowledge.createFormHint")}
      />

      <section className={`${styles.formSection} ${styles.basicSection}`}>
        <h3 className="mb-4 text-lg font-semibold leading-7 text-gray-800">
          {t("aidpKnowledge.createSectionBasic")}
        </h3>
        <div className={styles.formGrid}>
          <Form.Item
            name="name"
            label={t("aidpKnowledge.createKbNameLabel")}
            className={styles.firstColumn}
            rules={[
              {
                required: true,
                message: t("aidpKnowledge.createKbNameRequired"),
              },
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
            className={styles.fullSpan}
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

      <section className={styles.formSection}>
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
          <div className={`${styles.formGrid} mt-5`}>
            {graphEnabled && (
              <>
                <Form.Item
                  name="graph_domain"
                  label={t("aidpKnowledge.createGraphDomain")}
                  className={styles.fullSpan}
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
                  label={label(t("aidpKnowledge.createGraphHop"))}
                  rules={[{ type: "number", min: 1, max: 3 }]}
                >
                  <InputNumber style={{ width: "100%" }} min={1} max={3} />
                </Form.Item>
                <Form.Item
                  name="graph_thinking"
                  label={label(t("aidpKnowledge.createGraphThinking"))}
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
                  label={label(t("aidpKnowledge.createGraphPromptLanguage"))}
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
                  className={styles.fullSpan}
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
                  label={label(t("aidpKnowledge.createGraphSynonymMerge"))}
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
                  label={label(t("aidpKnowledge.createGraphDisambiguation"))}
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
                  className={styles.fullSpan}
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

      <section className={styles.formSection}>
        {sectionHeading("chunk", t("aidpKnowledge.createSectionChunk"))}
        <p className={styles.defaultsHint}>
          {t("aidpKnowledge.createDefaultsHint")}
        </p>
        <div id="aidp-create-chunk-panel" hidden={!expanded.chunk}>
          <div className={styles.chunkModeSection}>
            <div className={styles.formGrid}>
              <Form.Item
                name="chunk_mode"
                label={t("aidpKnowledge.createChunkMode")}
                className={styles.firstColumn}
                rules={[{ required: true }]}
              >
                <Radio.Group className="w-full">
                  <div className={styles.chunkChoices}>
                    <Radio
                      value={0}
                      className={`${styles.chunkOption} ${chunkMode === 0 ? styles.chunkOptionSelected : styles.chunkOptionUnselected}`}
                    >
                      <span className={styles.chunkOptionContent}>
                        <span className="font-medium text-gray-800">
                          {t("aidpKnowledge.createChunkModeSmart")}
                        </span>
                        <span
                          className={`${styles.chunkOptionHint} text-xs leading-5 text-gray-500`}
                        >
                          {t("aidpKnowledge.createChunkModeSmartHint")}
                        </span>
                      </span>
                    </Radio>
                    <Radio
                      value={1}
                      className={`${styles.chunkOption} ${chunkMode === 1 ? styles.chunkOptionSelected : styles.chunkOptionUnselected}`}
                    >
                      <span className={styles.chunkOptionContent}>
                        <span className="font-medium text-gray-800">
                          {t("aidpKnowledge.createChunkModeLegal")}
                        </span>
                        <span
                          className={`${styles.chunkOptionHint} text-xs leading-5 text-gray-500`}
                        >
                          {t("aidpKnowledge.createChunkModeLegalHint")}
                        </span>
                      </span>
                    </Radio>
                  </div>
                </Radio.Group>
              </Form.Item>
            </div>
          </div>
          <div className={styles.formGrid}>
            <Form.Item
              name="chunk_token_num"
              label={label(t("aidpKnowledge.createChunkTokenNum"))}
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
                  min: OVERLAP_PERCENT_MIN,
                  max: OVERLAP_PERCENT_MAX,
                  message: t("aidpKnowledge.createOverlapPercentRange", {
                    min: OVERLAP_PERCENT_MIN,
                    max: OVERLAP_PERCENT_MAX,
                  }),
                },
              ]}
            >
              <SliderNumberField
                min={OVERLAP_PERCENT_MIN}
                max={OVERLAP_PERCENT_MAX}
                step={0.5}
                unit="%"
                precision={1}
                marks={{
                  [OVERLAP_PERCENT_MIN]: `${OVERLAP_PERCENT_MIN}%`,
                  [OVERLAP_PERCENT_MAX]: `${OVERLAP_PERCENT_MAX}%`,
                }}
                ariaLabel={t("aidpKnowledge.createOverlapPercent")}
              />
            </Form.Item>
          </div>
        </div>
      </section>

      <section className={styles.formSection}>
        {sectionHeading("vector", t("aidpKnowledge.createSectionVector"))}
        <p className={styles.defaultsHint}>
          {t("aidpKnowledge.createDefaultsHint")}
        </p>
        <div id="aidp-create-vector-panel" hidden={!expanded.vector}>
          <div className={styles.formGrid}>
            <Form.Item
              name="embedding_model"
              label={label(t("aidpKnowledge.createEmbeddingModel"))}
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
            <Form.Item
              className={styles.vlmFormItem}
              label={
                <span className={styles.vlmLabelRow}>
                  <span>{t("aidpKnowledge.createVlmModel")}</span>
                  <Tooltip title={t("aidpKnowledge.createCaptionEnableHint")}>
                    <QuestionCircleOutlined
                      className="cursor-help text-gray-400"
                      aria-label={t("aidpKnowledge.createCaptionEnableHint")}
                    />
                  </Tooltip>
                  <Form.Item
                    name="caption_enable"
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch
                      aria-label={t("aidpKnowledge.createCaptionEnable")}
                    />
                  </Form.Item>
                </span>
              }
            >
              <Form.Item
                name="vlm_model"
                className={styles.vlmModelControl}
                rules={[
                  {
                    required: captionEnabled,
                    message: t("aidpKnowledge.createVlmModelRequired"),
                  },
                ]}
                noStyle
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
            </Form.Item>
          </div>
        </div>
      </section>

      <section className={`${styles.formSection} ${styles.lastSection}`}>
        {sectionHeading("retrieval", t("aidpKnowledge.createSectionRetrieval"))}
        <p className={styles.defaultsHint}>
          {t("aidpKnowledge.createDefaultsHint")}
        </p>
        <div id="aidp-create-retrieval-panel" hidden={!expanded.retrieval}>
          <div className={styles.formGrid}>
            <Form.Item
              name="similarity"
              label={label(t("aidpKnowledge.createSimilarity"))}
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
              label={label(t("aidpKnowledge.createTopk"))}
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
