// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { App, Form, Modal, Select, Skeleton, Switch, Tooltip } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";

import type {
  AidpGraphConfigUpdate,
  AidpKbDetail,
  AidpModelItem,
} from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import log from "@/lib/logger";
import AidpSliderNumberField from "@/ext_components/aidp/pages/knowledge-create/AidpSliderNumberField";
import AidpKnowledgeDetailInformation, {
  type AidpDetailSetting,
} from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeDetailInformation";
import {
  formatDetailDateTime,
  graphConfigOf,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";

/** Modal title i18n keys for every editable detail setting. */
const SETTING_MODAL_TITLE_KEYS: Record<AidpDetailSetting, string> = {
  chunk_mode: "aidpKnowledge.detailEditChunkMode",
  topk: "aidpKnowledge.detailEditTopK",
  vlm: "aidpKnowledge.detailEditVlm",
  graph_llm: "aidpKnowledge.detailEditGraphModel",
  graph_hop: "aidpKnowledge.detailEditGraphHop",
  graph_thinking: "aidpKnowledge.detailEditGraphThinking",
  graph_synonym: "aidpKnowledge.detailEditGraphSynonym",
  graph_disambiguation: "aidpKnowledge.detailEditGraphDisambiguation",
};

/** Field-label i18n keys for the graph setting dialogs. */
const GRAPH_SETTING_LABEL_KEYS = {
  graph_llm: "aidpKnowledge.detailGraphModel",
  graph_hop: "aidpKnowledge.detailGraphHops",
  graph_thinking: "aidpKnowledge.detailGraphThinking",
  graph_synonym: "aidpKnowledge.detailGraphSynonym",
  graph_disambiguation: "aidpKnowledge.detailGraphDisambiguation",
} as const;

type AidpGraphSetting = Extract<AidpDetailSetting, `graph_${string}`>;

const isGraphSetting = (
  setting: AidpDetailSetting
): setting is AidpGraphSetting => setting.startsWith("graph_");

/** Tolerate both AIDP string flags ("是"/"否") and native booleans. */
const graphFlagOf = (value: unknown): boolean | undefined =>
  value === true || value === "是"
    ? true
    : value === false || value === "否"
      ? false
      : undefined;

/** Initial form value for a graph setting dialog, from the KB detail. */
const graphSettingInitialValue = (
  setting: AidpGraphSetting,
  detail: AidpKbDetail,
  graphConfig: Record<string, unknown>
): string | number | boolean | undefined => {
  switch (setting) {
    case "graph_llm": {
      const nested = graphConfig.llm_model_name;
      return (
        detail.llm_model_name ||
        (typeof nested === "string" && nested ? nested : undefined)
      );
    }
    case "graph_hop": {
      const hop = graphConfig.retrieve_subgraph_hop;
      if (typeof hop === "number") return hop;
      if (typeof hop === "string" && /^\d+$/.test(hop)) return Number(hop);
      return undefined;
    }
    case "graph_thinking": {
      const noThink = graphFlagOf(graphConfig.no_think_mode);
      return noThink === undefined ? undefined : !noThink;
    }
    case "graph_synonym":
      return graphFlagOf(graphConfig.synonym_merge_enable);
    default:
      return graphFlagOf(graphConfig.disambiguation_enable);
  }
};

interface AidpKnowledgeInformationTabProps {
  detail: AidpKbDetail;
  groupNames: string[];
  canConfigureGroupPermissions: boolean;
  detailFetching: boolean;
  onEditPermissions: () => void;
  onRefreshDetail: () => Promise<unknown>;
}

/**
 * "Basic information" tab of the AIDP knowledge base detail view.
 *
 * Renders the full knowledge base configuration and owns the inline setting
 * editors (chunk mode, vector TopK and caption/VLM model).
 */
const AidpKnowledgeInformationTab: React.FC<
  AidpKnowledgeInformationTabProps
> = ({
  detail,
  groupNames,
  canConfigureGroupPermissions,
  detailFetching,
  onEditPermissions,
  onRefreshDetail,
}) => {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const canEdit = detail.permission === "EDIT";
  const graphConfig = useMemo(() => graphConfigOf(detail), [detail]);
  const [savingSetting, setSavingSetting] = useState(false);
  const [settingModal, setSettingModal] = useState<AidpDetailSetting | null>(
    null
  );
  const [settingForm] = Form.useForm<{ value: number }>();
  const [graphForm] = Form.useForm<{ value: string | number | boolean }>();
  const [vlmForm] = Form.useForm<{
    caption_enable: boolean;
    vlm_model?: string;
  }>();

  // ---- VLM model options for the caption (VLM) edit dialog ----
  const { data: vlmModelsData, isLoading: vlmModelsLoading } = useQuery({
    queryKey: ["aidp-models", "vlm", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("vlm", "KnowledgeBase"),
    staleTime: 5 * 60 * 1000,
    enabled: canEdit,
  });
  const vlmModelOptions = useMemo(() => {
    const models: AidpModelItem[] = vlmModelsData?.models ?? [];
    return models
      .map((m) => m.model_name)
      .filter(
        (name): name is string => typeof name === "string" && name.length > 0
      );
  }, [vlmModelsData]);
  const captionEditEnabled = Form.useWatch("caption_enable", vlmForm);

  // ---- LLM model options for the graph model edit dialog ----
  const { data: llmModelsData, isLoading: llmModelsLoading } = useQuery({
    queryKey: ["aidp-models", "llm", "KnowledgeBase"],
    queryFn: () => aidpKnowledgeService.listModels("llm", "KnowledgeBase"),
    staleTime: 5 * 60 * 1000,
    enabled: canEdit,
  });
  const llmModelOptions = useMemo(() => {
    const models: AidpModelItem[] = llmModelsData?.models ?? [];
    return models
      .map((m) => m.model_name)
      .filter(
        (name): name is string => typeof name === "string" && name.length > 0
      );
  }, [llmModelsData]);

  useEffect(() => {
    if (!settingModal) return;
    if (settingModal === "vlm") {
      vlmForm.setFieldsValue({
        caption_enable:
          detail.is_multimodal === true || detail.caption_enable === 1,
        vlm_model: detail.vlm_model || undefined,
      });
      return;
    }
    if (isGraphSetting(settingModal)) {
      graphForm.setFieldsValue({
        value: graphSettingInitialValue(settingModal, detail, graphConfig),
      });
      return;
    }
    settingForm.setFieldsValue({
      value:
        settingModal === "chunk_mode"
          ? (detail.chunk_mode ?? 0)
          : (detail.topk ?? 10),
    });
  }, [detail, graphConfig, graphForm, settingForm, settingModal, vlmForm]);

  const saveSetting = async () => {
    if (!settingModal) return;
    if (isGraphSetting(settingModal)) {
      // Graph settings are saved as a single-field graph_config partial
      // update; the backend merges it into the stored AIDP configuration.
      const values = await graphForm.validateFields();
      const value = values.value;
      let graphConfigUpdate: AidpGraphConfigUpdate;
      switch (settingModal) {
        case "graph_llm":
          graphConfigUpdate = { llm_model_name: String(value) };
          break;
        case "graph_hop":
          graphConfigUpdate = { retrieve_subgraph_hop: Number(value) };
          break;
        case "graph_thinking":
          // The UI switch is "enable thinking"; AIDP stores the inverse flag.
          graphConfigUpdate = { no_think_mode: !value };
          break;
        case "graph_synonym":
          graphConfigUpdate = { synonym_merge_enable: Boolean(value) };
          break;
        default:
          graphConfigUpdate = { disambiguation_enable: Boolean(value) };
          break;
      }
      setSavingSetting(true);
      try {
        await aidpKnowledgeService.updateKb(detail.kds_id, {
          graph_config: graphConfigUpdate,
        });
        setSettingModal(null);
        await onRefreshDetail();
        message.success(t("aidpKnowledge.detailSettingSaved"));
      } catch (error) {
        log.error("Failed to save AIDP knowledge graph setting:", {
          id: detail.kds_id,
          setting: settingModal,
          error,
        });
        message.error(
          getAidpErrorMessage(
            error,
            t,
            t("aidpKnowledge.detailSettingSaveFailed")
          )
        );
      } finally {
        setSavingSetting(false);
      }
      return;
    }
    if (settingModal === "vlm") {
      // Mirrors the create-KB behavior: enabled requires a VLM model;
      // disabled omits the model field entirely so AIDP keeps its value.
      const values = await vlmForm.validateFields();
      setSavingSetting(true);
      try {
        await aidpKnowledgeService.updateKb(detail.kds_id, {
          ...(values.caption_enable
            ? { caption_enable: 1, vlm_model: values.vlm_model || "" }
            : { caption_enable: 0 }),
        });
        setSettingModal(null);
        await onRefreshDetail();
        message.success(t("aidpKnowledge.detailSettingSaved"));
      } catch (error) {
        log.error("Failed to save AIDP knowledge setting:", {
          id: detail.kds_id,
          setting: settingModal,
          error,
        });
        message.error(
          getAidpErrorMessage(
            error,
            t,
            t("aidpKnowledge.detailSettingSaveFailed")
          )
        );
      } finally {
        setSavingSetting(false);
      }
      return;
    }
    const values = await settingForm.validateFields();
    setSavingSetting(true);
    try {
      await aidpKnowledgeService.updateKb(detail.kds_id, {
        [settingModal]: values.value,
      });
      setSettingModal(null);
      await onRefreshDetail();
      message.success(t("aidpKnowledge.detailSettingSaved"));
    } catch (error) {
      log.error("Failed to save AIDP knowledge setting:", {
        id: detail.kds_id,
        setting: settingModal,
        error,
      });
      message.error(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.detailSettingSaveFailed")
        )
      );
    } finally {
      setSavingSetting(false);
    }
  };

  // Disabling the graph is permanent; the confirmation spells out both
  // consequences before the irreversible AIDP update is sent.
  const disableGraph = () => {
    // modal.confirm returns a thenable without .catch; consume it so a failed
    // confirmation stays in the dialog instead of an unhandled rejection.
    void Promise.resolve(
      modal.confirm({
        title: t("aidpKnowledge.detailGraphDisableTitle"),
        content: (
          <div className="whitespace-pre-wrap">
            {t("aidpKnowledge.detailGraphDisableContent")}
          </div>
        ),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        okButtonProps: { danger: true },
        centered: true,
        onOk: async () => {
          try {
            await aidpKnowledgeService.updateKb(detail.kds_id, {
              is_exist_graph: false,
            });
            await onRefreshDetail();
            message.success(t("aidpKnowledge.detailGraphDisableSuccess"));
          } catch (error) {
            log.error("Failed to disable AIDP knowledge graph:", {
              id: detail.kds_id,
              error,
            });
            message.error(
              getAidpErrorMessage(
                error,
                t,
                t("aidpKnowledge.detailSettingSaveFailed")
              )
            );
            throw error;
          }
        },
      })
    );
  };

  return (
    <>
      {detailFetching ? (
        <Skeleton active className="shrink-0" paragraph={{ rows: 5 }} />
      ) : (
        <AidpKnowledgeDetailInformation
          detail={detail}
          graphConfig={graphConfig}
          groupNames={groupNames}
          canConfigureGroupPermissions={canConfigureGroupPermissions}
          formatDateTime={formatDetailDateTime}
          onEditPermissions={onEditPermissions}
          onEditSetting={setSettingModal}
          onDisableGraph={disableGraph}
        />
      )}

      <Modal
        title={settingModal ? t(SETTING_MODAL_TITLE_KEYS[settingModal]) : ""}
        open={Boolean(settingModal)}
        centered
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        onCancel={() => setSettingModal(null)}
        onOk={() => void saveSetting()}
        confirmLoading={savingSetting}
        destroyOnHidden
      >
        {settingModal === "vlm" ? (
          <Form form={vlmForm} layout="vertical">
            <Form.Item
              label={
                <span className="flex min-h-5 items-center gap-2 leading-5">
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
              {captionEditEnabled && (
                <Form.Item
                  name="vlm_model"
                  rules={[
                    {
                      required: true,
                      message: t("aidpKnowledge.createVlmModelRequired"),
                    },
                  ]}
                  noStyle
                >
                  <Select
                    showSearch
                    allowClear
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
              )}
            </Form.Item>
          </Form>
        ) : settingModal && isGraphSetting(settingModal) ? (
          <Form form={graphForm} layout="vertical">
            <Form.Item
              name="value"
              label={t(GRAPH_SETTING_LABEL_KEYS[settingModal])}
              rules={[
                {
                  required: true,
                  message: t("aidpKnowledge.detailGraphValueRequired"),
                },
              ]}
            >
              {settingModal === "graph_llm" ? (
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
              ) : settingModal === "graph_hop" ? (
                <AidpSliderNumberField
                  min={1}
                  max={3}
                  step={1}
                  marks={{ 1: "1", 2: "2", 3: "3" }}
                  ariaLabel={t("aidpKnowledge.detailEditGraphHop")}
                />
              ) : (
                <Select
                  options={[
                    { value: true, label: t("aidpKnowledge.createYes") },
                    { value: false, label: t("aidpKnowledge.createNo") },
                  ]}
                />
              )}
            </Form.Item>
          </Form>
        ) : settingModal ? (
          <Form
            form={settingForm}
            layout="vertical"
            initialValues={{ value: 0 }}
          >
            <Form.Item
              name="value"
              label={t(
                settingModal === "chunk_mode"
                  ? "aidpKnowledge.detailChunkMode"
                  : "aidpKnowledge.detailVectorTopK"
              )}
              rules={[{ required: true }]}
            >
              {settingModal === "chunk_mode" ? (
                <Select
                  options={[
                    { value: 0, label: t("aidpKnowledge.chunkModeSmart") },
                    { value: 1, label: t("aidpKnowledge.chunkModeLegal") },
                  ]}
                />
              ) : (
                <AidpSliderNumberField
                  min={1}
                  max={100}
                  step={1}
                  marks={{ 1: "1", 100: "100" }}
                  ariaLabel={t("aidpKnowledge.detailVectorTopK")}
                />
              )}
            </Form.Item>
          </Form>
        ) : null}
      </Modal>
    </>
  );
};

export default AidpKnowledgeInformationTab;
