import React, { useState } from "react";
import type { TFunction } from "i18next";

import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Switch,
  Tooltip,
} from "antd";
import type { FormInstance } from "antd";
import { DownOutlined, QuestionCircleOutlined } from "@ant-design/icons";

import { AIDP_KNOWLEDGE_BASE_NAME_PATTERN } from "@/const/knowledgeBase";
import { AidpKnowledgeBasePermissionFields } from "./AidpKnowledgeBaseModalParts";
import AidpSliderNumberField from "./AidpSliderNumberField";
import styles from "./AidpCreateKbSections.module.css";
import type { AidpGroupOption } from "../hooks/useAidpGroupOptions";
import type { AidpGraphTemplate, AidpModelOption } from "@/types/aidpGraph";
import { graphChoices, graphParameter } from "@/lib/aidpGraphConfig";

const GRAPH_PROMPT_MAX_CHARS = 4096;
const CHUNK_TOKEN_MIN = 256;
const CHUNK_TOKEN_MAX = 4096;
const OVERLAP_PERCENT_MIN = 1;
const OVERLAP_PERCENT_MAX = 40;

interface AidpCreateKbSectionsProps {
  form: FormInstance;
  t: TFunction;
  canConfigureGroupPermissions: boolean;
  groupOptions: AidpGroupOption[];
  ingroupPermission?: string;
  llmModelOptions: AidpModelOption[];
  llmModelsLoading: boolean;
  vlmModelOptions: AidpModelOption[];
  vlmModelsLoading: boolean;
  embeddingModelOptions: AidpModelOption[];
  embeddingModelsLoading: boolean;
  graphTemplate?: AidpGraphTemplate;
  onRestorePrompt: () => void;
}

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
  graphTemplate,
  onRestorePrompt,
}) => {
  const graphEnabled = Form.useWatch("is_exist_graph", form) === true;
  const captionEnabled = Form.useWatch("caption_enable", form) === true;
  const chunkMode = Form.useWatch("chunk_mode", form);
  const [expanded, setExpanded] = useState<Record<CollapsibleSection, boolean>>(
    {
      graph: false,
      chunk: false,
      vector: false,
      retrieval: false,
    }
  );

  const toggleSection = (section: CollapsibleSection) =>
    setExpanded((current) => ({ ...current, [section]: !current[section] }));

  const graphRule = (
    key: string,
    convert: (value: unknown) => string = String
  ) => ({
    validator: (_rule: unknown, value: unknown) => {
      const parameter = graphParameter(graphTemplate, key);
      if (parameter && new RegExp(parameter.regexp, "u").test(convert(value)))
        return Promise.resolve();
      return Promise.reject(
        new Error(t("aidpKnowledge.createGraphValueInvalid"))
      );
    },
  });

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
    const isExpanded = expanded[section];
    const panelId = `aidp-create-${section}-panel`;

    return (
      <div className={styles.sectionHeading}>
        <div className={styles.sectionHeadingTitle}>
          <button
            type="button"
            className="flex h-9 items-center gap-2 rounded px-1 text-left text-lg font-semibold leading-7 text-gray-800 hover:bg-gray-50"
            aria-expanded={isExpanded}
            aria-controls={panelId}
            aria-label={
              isExpanded
                ? t("aidpKnowledge.createCollapseSection", { section: title })
                : t("aidpKnowledge.createExpandSection", { section: title })
            }
            onClick={() => toggleSection(section)}
          >
            <DownOutlined
              className={`text-xs transition-transform ${isExpanded ? "" : "-rotate-90"}`}
            />
            <span>{title}</span>
          </button>
          {hint && (
            <Tooltip title={hint}>
              <QuestionCircleOutlined
                className="cursor-help text-gray-400"
                aria-label={hint}
              />
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
      title={t("aidpKnowledge.createGraphEnableHint")}
    />
  );

  return (
    <Form form={form} layout="vertical" className={styles.createForm}>
      <Alert
        className={`${styles.infoBanner} ${styles.createIntro}`}
        type="info"
        showIcon
        closable
        title={t("aidpKnowledge.createFormHint")}
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
          t("aidpKnowledge.createGraphSectionHint"),
          <Form.Item name="is_exist_graph" valuePropName="checked" noStyle>
            <Switch aria-label={t("aidpKnowledge.createGraphEnable")} />
          </Form.Item>
        )}
        <div id="aidp-create-graph-panel" hidden={!expanded.graph}>
          {sectionHint}
          <div className={`${styles.formGrid} mt-5`} hidden={!graphEnabled}>
            {graphEnabled && (
              <>
                <Form.Item
                  name="graph_domain"
                  label={label(
                    t("aidpKnowledge.createGraphDomain"),
                    t("aidpKnowledge.createGraphDomainHint")
                  )}
                  className={styles.fullSpan}
                  rules={[graphRule("domain")]}
                >
                  <Select
                    options={graphChoices(graphTemplate, "domain").map(
                      (value) => ({
                        value,
                        label: t(
                          (
                            {
                              常规: "aidpKnowledge.createGraphDomainGeneral",
                              医疗: "aidpKnowledge.createGraphDomainMedical",
                              金融: "aidpKnowledge.createGraphDomainFinance",
                              法律法规: "aidpKnowledge.createGraphDomainLegal",
                            } as Record<string, string>
                          )[value] || value
                        ),
                      })
                    )}
                  />
                </Form.Item>
                <Form.Item
                  name="graph_hop"
                  label={label(
                    t("aidpKnowledge.createGraphHop"),
                    t("aidpKnowledge.createGraphHopHint")
                  )}
                  rules={[graphRule("retrieve_subgraph_hop")]}
                >
                  <InputNumber style={{ width: "100%" }} min={1} max={3} />
                </Form.Item>
                <Form.Item
                  name="graph_thinking"
                  label={label(
                    t("aidpKnowledge.createGraphThinking"),
                    t("aidpKnowledge.createGraphThinkingHint")
                  )}
                  rules={[
                    graphRule("no_think_mode", (value) =>
                      value ? "否" : "是"
                    ),
                  ]}
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
                  label={label(
                    t("aidpKnowledge.createGraphPromptLanguage"),
                    t("aidpKnowledge.createGraphLanguageHint")
                  )}
                  rules={[graphRule("prompt_language")]}
                >
                  <Select
                    options={graphChoices(graphTemplate, "prompt_language").map(
                      (value) => ({
                        value,
                        label: t(
                          value === "中文"
                            ? "aidpKnowledge.createGraphPromptZh"
                            : "aidpKnowledge.createGraphPromptEn"
                        ),
                      })
                    )}
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
                    graphRule("prompt_text", (value) =>
                      typeof value === "string" ? value : ""
                    ),
                  ]}
                  extra={
                    <Button
                      type="link"
                      className="!px-0"
                      disabled={!graphTemplate}
                      onClick={onRestorePrompt}
                    >
                      {t("aidpKnowledge.createGraphUseDefaultPrompt")}
                    </Button>
                  }
                >
                  <Input.TextArea
                    rows={6}
                    showCount={{
                      formatter: ({ value }) =>
                        `${Array.from(value).length} / ${GRAPH_PROMPT_MAX_CHARS}`,
                    }}
                  />
                </Form.Item>
                <Form.Item
                  name="graph_synonym_merge"
                  label={label(
                    t("aidpKnowledge.createGraphSynonymMerge"),
                    t("aidpKnowledge.createGraphSynonymHint")
                  )}
                  rules={[
                    graphRule("synonym_merge_enable", (value) =>
                      value ? "是" : "否"
                    ),
                  ]}
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
                  label={label(
                    t("aidpKnowledge.createGraphDisambiguation"),
                    t("aidpKnowledge.createGraphDisambiguationHint")
                  )}
                  rules={[
                    graphRule("disambiguation_enable", (value) =>
                      value ? "是" : "否"
                    ),
                  ]}
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
                    optionFilterProp="label"
                    options={llmModelOptions}
                  />
                </Form.Item>
              </>
            )}
          </div>
        </div>
      </section>

      <section className={styles.formSection}>
        {sectionHeading(
          "chunk",
          t("aidpKnowledge.createSectionChunk"),
          t("aidpKnowledge.createChunkSectionHint")
        )}
        <p className={styles.defaultsHint} hidden={!expanded.chunk}>
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
              label={label(
                t("aidpKnowledge.createChunkTokenNum"),
                t("aidpKnowledge.createChunkTokenHint")
              )}
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
              <AidpSliderNumberField
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
              <AidpSliderNumberField
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
        {sectionHeading(
          "vector",
          t("aidpKnowledge.createSectionVector"),
          t("aidpKnowledge.createVectorSectionHint")
        )}
        <p className={styles.defaultsHint} hidden={!expanded.vector}>
          {t("aidpKnowledge.createDefaultsHint")}
        </p>
        <div id="aidp-create-vector-panel" hidden={!expanded.vector}>
          <div className={styles.formGrid}>
            <Form.Item
              name="embedding_model"
              label={label(
                t("aidpKnowledge.createEmbeddingModel"),
                t("aidpKnowledge.createEmbeddingHint")
              )}
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
                optionFilterProp="label"
                options={embeddingModelOptions}
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
                  optionFilterProp="label"
                  options={vlmModelOptions}
                />
              </Form.Item>
            </Form.Item>
          </div>
        </div>
      </section>

      <section className={`${styles.formSection} ${styles.lastSection}`}>
        {sectionHeading(
          "retrieval",
          t("aidpKnowledge.createSectionRetrieval"),
          t("aidpKnowledge.createRetrievalSectionHint")
        )}
        <p className={styles.defaultsHint} hidden={!expanded.retrieval}>
          {t("aidpKnowledge.createDefaultsHint")}
        </p>
        <div id="aidp-create-retrieval-panel" hidden={!expanded.retrieval}>
          <div className={styles.formGrid}>
            <Form.Item
              name="similarity"
              label={label(
                t("aidpKnowledge.createSimilarity"),
                t("aidpKnowledge.createSimilarityHint")
              )}
              rules={[{ required: true, type: "number", min: 0, max: 1 }]}
            >
              <AidpSliderNumberField
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
              label={label(
                t("aidpKnowledge.createTopk"),
                t("aidpKnowledge.createTopkHint")
              )}
              rules={[{ required: true, type: "number", min: 1, max: 100 }]}
            >
              <AidpSliderNumberField
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
