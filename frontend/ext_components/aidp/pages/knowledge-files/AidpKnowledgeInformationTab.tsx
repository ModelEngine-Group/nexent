"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { App, Form, Modal, Select, Skeleton, Switch, Tooltip } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";

import type {
  AidpKbDetail,
  AidpModelItem,
} from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import log from "@/lib/logger";
import AidpSliderNumberField from "@/ext_components/aidp/pages/knowledge-create/AidpSliderNumberField";
import AidpKnowledgeDetailInformation from "@/ext_components/aidp/pages/knowledge-files/AidpKnowledgeDetailInformation";
import {
  formatDetailDateTime,
  graphConfigOf,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpKnowledgeDetailUtils";

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
  const { message } = App.useApp();
  const canEdit = detail.permission === "EDIT";
  const graphConfig = useMemo(() => graphConfigOf(detail), [detail]);
  const [savingSetting, setSavingSetting] = useState(false);
  const [settingModal, setSettingModal] = useState<
    "chunk_mode" | "topk" | "vlm" | null
  >(null);
  const [settingForm] = Form.useForm<{ value: number }>();
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
    settingForm.setFieldsValue({
      value:
        settingModal === "chunk_mode"
          ? (detail.chunk_mode ?? 0)
          : (detail.topk ?? 10),
    });
  }, [
    detail.caption_enable,
    detail.chunk_mode,
    detail.is_multimodal,
    detail.topk,
    detail.vlm_model,
    settingForm,
    settingModal,
    vlmForm,
  ]);

  const saveSetting = async () => {
    if (!settingModal) return;
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
        />
      )}

      <Modal
        title={t(
          settingModal === "chunk_mode"
            ? "aidpKnowledge.detailEditChunkMode"
            : settingModal === "topk"
              ? "aidpKnowledge.detailEditTopK"
              : "aidpKnowledge.detailEditVlm"
        )}
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
