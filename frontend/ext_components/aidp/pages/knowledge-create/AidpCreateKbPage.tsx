// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter } from "next/navigation";

import {
  Alert,
  App,
  Button,
  Breadcrumb,
  ConfigProvider,
  Form,
  Space,
  Steps,
} from "antd";

import type { AidpGraphConfig } from "@/ext_components/aidp/shared/types/management";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { ApiError } from "@/services/api";
import { useErrorHandler } from "@/hooks/useErrorHandler";
import {
  getAidpErrorMessage,
  isAidpDuplicateError,
} from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { useAidpGroupOptions } from "@/ext_components/aidp/shared/hooks/useAidpGroupOptions";
import { scrollToFirstAidpFormError } from "@/ext_components/aidp/shared/utils/aidpFormErrors";
import {
  useAidpModels,
  useAidpGraphTemplate,
  useCreateAidpKnowledgeBase,
} from "@/ext_components/aidp/pages/knowledge-create/hooks/useAidpCreateQueries";
import {
  graphParameter,
  graphPrompt,
  modelOptions,
} from "@/ext_components/aidp/pages/knowledge-create/utils/aidpGraphConfig";
import {
  AIDP_DEFAULT_CHUNK_OVERLAP_PERCENT,
  AIDP_DEFAULT_CHUNK_TOKEN_NUM,
  AIDP_DEFAULT_SIMILARITY,
  AIDP_DEFAULT_TOPK,
  chunkOverlapTokens,
} from "@/ext_components/aidp/shared/utils/aidpChunking";

import AidpCreateKbSections from "@/ext_components/aidp/pages/knowledge-create/AidpCreateKbSections";
import AidpCreateOntologyStep from "@/ext_components/aidp/pages/knowledge-create/AidpCreateOntologyStep";
import aidpOntologyService from "@/ext_components/aidp/shared/services/aidpOntologyService";
import styles from "@/ext_components/aidp/pages/knowledge-create/AidpCreateKbSections.module.css";
import typography from "@/ext_components/aidp/shared/styles/aidpKnowledgeTypography.module.css";
import { aidpKnowledgeTypographyTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";

/**
 * Default AIDP knowledge base configuration.
 *
 * The creation screen uses AIDP's defaults (512 tokens, 10% overlap, similarity
 * 0, Top K 10 and captioning off). Model identifiers and graph defaults come
 * from AIDP's model and graph template endpoints.
 */
const AIDP_CREATE_DEFAULTS = {
  chunk_token_num: AIDP_DEFAULT_CHUNK_TOKEN_NUM,
  /** Overlap as a percentage of the chunk size; 10% of 512 = 51 tokens. */
  chunk_overlap_percent: AIDP_DEFAULT_CHUNK_OVERLAP_PERCENT,
  chunk_mode: 0,
  is_personal: 0,
  topk: AIDP_DEFAULT_TOPK,
  similarity: AIDP_DEFAULT_SIMILARITY,
  caption_enable: 0,
  summary_enable: false,
  is_exist_graph: false,
  sensitive_intercept_enable: false,
  graph_domain: "常规" as const,
  graph_hop: 2,
  /** UI switch; the submitted `no_think_mode` is its inverse. */
  graph_thinking: false,
  graph_prompt_language: "中文" as const,
  graph_synonym_merge: false,
  graph_disambiguation: false,
};

/**
 * Dedicated AIDP knowledge base creation page.
 *
 * Collects all creation parameters in one page and creates the knowledge base
 * directly. Files are uploaded from the knowledge base detail page.
 */
const AidpCreateKbPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { handleError, getI18nErrorMessage } = useErrorHandler();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();

  const [form] = Form.useForm();
  const [validating, setValidating] = useState(false);
  const [invalidFields, setInvalidFields] = useState<string[]>([]);
  const [step, setStep] = useState(0);
  const [selectedDomainId, setSelectedDomainId] = useState<string | null>(null);
  const createMutation = useCreateAidpKnowledgeBase();
  const loading = validating || createMutation.isPending;
  /** Guards against a second create while one submission is in flight. */
  const submittingRef = useRef(false);

  // The entry only serves AIDP; an ES deployment has no creation entry here,
  // so a direct visit goes back to the knowledge base page.
  useEffect(() => {
    if (!isDeploymentReady) return;
    if (!enableAidpKnowledge) {
      router.replace(`/${locale}/knowledges`);
    }
  }, [enableAidpKnowledge, isDeploymentReady, locale, router]);

  // ---- Permissions and groups ----
  const {
    isUser,
    canConfigureGroupPermissions,
    canReadGroups,
    groupOptions,
    groupsLoading,
    groupsError,
  } = useAidpGroupOptions();
  const ingroupPermission = Form.useWatch("ingroup_permission", form);

  const modelsQuery = useAidpModels();
  const llmModelOptions = useMemo(
    () => modelOptions(modelsQuery.data?.models ?? [], "llm"),
    [modelsQuery.data]
  );
  const vlmModelOptions = useMemo(
    () => modelOptions(modelsQuery.data?.models ?? [], "vlm"),
    [modelsQuery.data]
  );
  const embeddingModelOptions = useMemo(
    () => modelOptions(modelsQuery.data?.models ?? [], "embedding"),
    [modelsQuery.data]
  );
  const graphEnabled = Form.useWatch("is_exist_graph", form) === true;
  const promptLanguage = Form.useWatch("graph_prompt_language", form) || "中文";
  const graphDomain = Form.useWatch("graph_domain", form) || "常规";
  const templateQuery = useAidpGraphTemplate(
    promptLanguage === "英文" ? "english" : "chinese",
    graphEnabled
  );
  const configurationError =
    modelsQuery.error || (graphEnabled ? templateQuery.error : null);
  const configurationErrorMessage =
    configurationError instanceof ApiError
      ? getI18nErrorMessage(configurationError.code)
      : configurationError?.message ||
        t("aidpKnowledge.createConfigurationLoadFailed");
  const initializedGraph = useRef(false);
  const previousDefaultPrompt = useRef("");
  useEffect(() => {
    const data = templateQuery.data;
    if (!data || !graphEnabled) return;
    if (!initializedGraph.current) {
      const value = (key: string) => graphParameter(data, key)?.param_value;
      const defaults: Record<string, unknown> = {
        graph_domain: value("domain"),
        graph_hop: Number(value("retrieve_subgraph_hop")),
        graph_thinking: value("no_think_mode") === "否",
        graph_synonym_merge: value("synonym_merge_enable") === "是",
        graph_disambiguation: value("disambiguation_enable") === "是",
      };
      Object.entries(defaults).forEach(([field, initial]) => {
        if (!form.isFieldTouched(field)) form.setFieldValue(field, initial);
      });
      initializedGraph.current = true;
    }
    const nextPrompt = graphPrompt(
      data,
      form.getFieldValue("graph_domain") || graphDomain
    );
    const currentPrompt = form.getFieldValue("graph_prompt_text") || "";
    if (
      !form.isFieldTouched("graph_prompt_text") ||
      currentPrompt === previousDefaultPrompt.current
    ) {
      form.setFieldValue("graph_prompt_text", nextPrompt);
    }
    previousDefaultPrompt.current = nextPrompt;
  }, [form, graphDomain, graphEnabled, templateQuery.data]);
  const restoreDefaultPrompt = useCallback(() => {
    const prompt = graphPrompt(templateQuery.data, graphDomain);
    form.setFieldValue("graph_prompt_text", prompt);
    previousDefaultPrompt.current = prompt;
  }, [form, graphDomain, templateQuery.data]);
  useEffect(() => {
    for (const [field, options] of [
      ["embedding_model", embeddingModelOptions],
      ["llm_model_name", llmModelOptions],
      ["vlm_model", vlmModelOptions],
    ] as const) {
      if (
        options.length &&
        !form.isFieldTouched(field) &&
        !options.some((option) => option.value === form.getFieldValue(field))
      ) {
        form.setFieldValue(field, options[0].value);
      }
    }
  }, [embeddingModelOptions, form, llmModelOptions, vlmModelOptions]);

  // ---- Defaults ----
  useEffect(() => {
    form.setFieldsValue({
      chunk_token_num: AIDP_CREATE_DEFAULTS.chunk_token_num,
      chunk_overlap_percent: AIDP_CREATE_DEFAULTS.chunk_overlap_percent,
      chunk_mode: AIDP_CREATE_DEFAULTS.chunk_mode,
      topk: AIDP_CREATE_DEFAULTS.topk,
      similarity: AIDP_CREATE_DEFAULTS.similarity,
      caption_enable: AIDP_CREATE_DEFAULTS.caption_enable === 1,
      summary_enable: AIDP_CREATE_DEFAULTS.summary_enable,
      is_exist_graph: AIDP_CREATE_DEFAULTS.is_exist_graph,
      sensitive_intercept_enable:
        AIDP_CREATE_DEFAULTS.sensitive_intercept_enable,
      graph_domain: AIDP_CREATE_DEFAULTS.graph_domain,
      graph_hop: AIDP_CREATE_DEFAULTS.graph_hop,
      graph_thinking: AIDP_CREATE_DEFAULTS.graph_thinking,
      graph_prompt_language: AIDP_CREATE_DEFAULTS.graph_prompt_language,
      graph_synonym_merge: AIDP_CREATE_DEFAULTS.graph_synonym_merge,
      graph_disambiguation: AIDP_CREATE_DEFAULTS.graph_disambiguation,
      graph_prompt_text: "",
      ingroup_permission: isUser ? "PRIVATE" : "READ_ONLY",
      group_ids: [],
    });
  }, [form, isUser]);

  const goBackToList = () => router.push(`/${locale}/knowledges`);

  /** Jump to the created knowledge base detail page. */
  const openCreatedKb = (kbId: string) => {
    router.push(`/${locale}/knowledges/detail?kb=${encodeURIComponent(kbId)}`);
  };

  const goNext = async () => {
    if (step === 0) {
      try {
        await form.validateFields(["name", "description"]);
      } catch (error) {
        scrollToFirstAidpFormError(form, error);
        return;
      }
    }
    setStep((previous) => Math.min(previous + 1, 1));
  };

  const handleSubmit = async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setValidating(true);
    try {
      // Step 0 fields are unmounted on step 1. Its values were validated by
      // goNext() before leaving step 0, so read the preserved store directly
      // instead of validating fields that are no longer mounted.
      const values = form.getFieldsValue(true);
      const permission = isUser
        ? "PRIVATE"
        : values.ingroup_permission || "READ_ONLY";
      const groupIds =
        isUser || permission === "PRIVATE"
          ? []
          : Array.isArray(values.group_ids)
            ? values.group_ids
            : [];

      const chunkTokens =
        values.chunk_token_num ?? AIDP_CREATE_DEFAULTS.chunk_token_num;
      const overlapPercent =
        values.chunk_overlap_percent ??
        AIDP_CREATE_DEFAULTS.chunk_overlap_percent;
      const overlapTokens = chunkOverlapTokens(
        chunkTokens,
        Number(overlapPercent)
      );

      const graphConfig: AidpGraphConfig | undefined = values.is_exist_graph
        ? {
            domain: values.graph_domain || AIDP_CREATE_DEFAULTS.graph_domain,
            retrieve_subgraph_hop: String(
              values.graph_hop ?? AIDP_CREATE_DEFAULTS.graph_hop
            ),
            // The UI switch is the inverse of the submitted thinking mode.
            no_think_mode: values.graph_thinking ? "否" : "是",
            prompt_language:
              values.graph_prompt_language ||
              AIDP_CREATE_DEFAULTS.graph_prompt_language,
            prompt_text: values.graph_prompt_text,
            synonym_merge_enable: values.graph_synonym_merge ? "是" : "否",
            disambiguation_enable: values.graph_disambiguation ? "是" : "否",
            llm_model_name: values.llm_model_name,
          }
        : undefined;

      setValidating(false);
      const created = await createMutation.mutateAsync({
        name: (values.name ?? "").trim(),
        description: (values.description ?? "").trim(),
        chunk_token_num: chunkTokens,
        chunk_overlap_num: overlapTokens,
        chunk_mode: values.chunk_mode ?? AIDP_CREATE_DEFAULTS.chunk_mode,
        embedding_model: values.embedding_model,
        topk: values.topk ?? AIDP_CREATE_DEFAULTS.topk,
        similarity: values.similarity ?? AIDP_CREATE_DEFAULTS.similarity,
        is_personal: AIDP_CREATE_DEFAULTS.is_personal,
        caption_enable: values.caption_enable ? 1 : 0,
        vlm_model: values.caption_enable ? values.vlm_model || "" : "",
        summary_enable: values.summary_enable === true,
        summary_preview: values.summary_enable === true,
        summary_model: values.summary_enable
          ? values.summary_model || undefined
          : undefined,
        sensitive_intercept_enable: values.sensitive_intercept_enable ? 1 : 0,
        is_exist_graph: !!values.is_exist_graph,
        graph_config: graphConfig,
        ingroup_permission: permission,
        group_ids: groupIds,
      });

      message.success(t("aidpKnowledge.createKbSuccess"));
      const createdId = String(created.kds_id || "");
      if (createdId && selectedDomainId) {
        try {
          await aidpOntologyService.createBinding(selectedDomainId, createdId);
        } catch {
          message.warning(t("aidpKnowledge.createBindingFailed"), 8);
        }
      }
      if (createdId) openCreatedKb(createdId);
    } catch (error) {
      if (scrollToFirstAidpFormError(form, error, { defer: true })) {
        const fields = (error as { errorFields: { name: (string | number)[] }[] })
          .errorFields;
        setInvalidFields(fields.map((field) => String(field.name[0])));
        return;
      }
      handleError(error, {
        showMessage: false,
        handleSession: false,
      });
      message.error(
        isAidpDuplicateError(error)
          ? t("aidpKnowledge.createKbDuplicateName")
          : getAidpErrorMessage(error, t, t("aidpKnowledge.createKbFailed"))
      );
    } finally {
      setValidating(false);
      submittingRef.current = false;
    }
  };

  const pageContent = (
    <div
      className={`${typography.page} relative flex h-full min-h-0 w-full flex-col`}
    >
      <header className="shrink-0 px-6 pt-4">
        <Breadcrumb
          items={[
            {
              title: (
                <button
                  type="button"
                  disabled={loading}
                  onClick={goBackToList}
                  className={`${typography.breadcrumbLink} disabled:cursor-not-allowed`}
                >
                  {t("aidpKnowledge.breadcrumbKnowledgeBase")}
                </button>
              ),
            },
            {
              title: (
                <span className={typography.pageTitle}>
                  {t("aidpKnowledge.createPageTitle")}
                </span>
              ),
            },
          ]}
        />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-4">
        <Steps
          className="mb-5"
          current={step}
          items={[
            { title: t("aidpKnowledge.createStepConfig") },
            { title: t("aidpKnowledge.createStepOntology") },
          ]}
        />
        {(modelsQuery.isError || (graphEnabled && templateQuery.isError)) && (
          <Alert
            type="error"
            showIcon
            title={configurationErrorMessage}
            action={
              <Button
                onClick={() => {
                  void modelsQuery.refetch();
                  if (graphEnabled) void templateQuery.refetch();
                }}
              >
                {t("common.retry")}
              </Button>
            }
          />
        )}
        {canConfigureGroupPermissions &&
          (groupsError || (!canReadGroups && !groupsLoading)) && (
            <Alert
              className="mb-4"
              type="error"
              showIcon
              title={
                groupsError
                  ? getAidpErrorMessage(
                      groupsError,
                      t,
                      t("aidpKnowledge.groupsLoadFailed")
                    )
                  : t("aidpKnowledge.groupsPermissionRequired")
              }
            />
          )}
        {modelsQuery.isSuccess && embeddingModelOptions.length === 0 && (
          <Alert
            className="mb-4"
            type="error"
            showIcon
            title={t("aidpKnowledge.createEmbeddingUnavailable")}
          />
        )}
        {step === 0 && (
          <AidpCreateKbSections
            form={form}
            invalidFields={invalidFields}
            groupsLoading={groupsLoading}
            groupsUnavailable={!!groupsError || !canReadGroups}
            t={t}
            canConfigureGroupPermissions={canConfigureGroupPermissions}
            groupOptions={groupOptions}
            ingroupPermission={ingroupPermission}
            llmModelOptions={llmModelOptions}
            llmModelsLoading={modelsQuery.isLoading}
            vlmModelOptions={vlmModelOptions}
            vlmModelsLoading={modelsQuery.isLoading}
            embeddingModelOptions={embeddingModelOptions}
            embeddingModelsLoading={modelsQuery.isLoading}
            graphTemplate={templateQuery.data}
            onRestorePrompt={restoreDefaultPrompt}
          />
        )}
        {step === 1 && (
          <AidpCreateOntologyStep
            selectedDomainId={selectedDomainId}
            onSelect={setSelectedDomainId}
          />
        )}
      </div>

      <footer className={styles.createFooter}>
        <div />
        <Space size={10} wrap>
          <Button onClick={goBackToList} disabled={loading}>
            {t("common.cancel")}
          </Button>
          {step > 0 && (
            <Button
              disabled={loading}
              onClick={() => setStep((previous) => Math.max(previous - 1, 0))}
            >
              {t("aidpKnowledge.createPrevious")}
            </Button>
          )}
          {step < 1 && (
            <Button disabled={loading} onClick={() => void goNext()}>
              {t("aidpKnowledge.createNext")}
            </Button>
          )}
          <Button
            type="primary"
            loading={loading}
            disabled={
              modelsQuery.isPending ||
              modelsQuery.isError ||
              (modelsQuery.isSuccess && embeddingModelOptions.length === 0) ||
              (canConfigureGroupPermissions &&
                ingroupPermission !== "PRIVATE" &&
                (groupsLoading || !!groupsError || !canReadGroups)) ||
              (graphEnabled &&
                (templateQuery.isPending || templateQuery.isError))
            }
            onClick={() => void handleSubmit()}
          >
            {t("aidpKnowledge.createSubmit")}
          </Button>
        </Space>
      </footer>
      {loading && (
        <div
          className={`${typography.muted} absolute bottom-[4.5rem] left-1/2 -translate-x-1/2 rounded bg-white px-3 py-1 text-xs leading-5 shadow`}
        >
          {t("aidpKnowledge.createSubmitting")}
        </div>
      )}
    </div>
  );

  return (
    <ConfigProvider theme={aidpKnowledgeTypographyTheme}>
      {pageContent}
    </ConfigProvider>
  );
};

export default AidpCreateKbPage;
