// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";
import { App } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  getConversationModelSelection,
  patchConversationModelSelection,
} from "@/services/modelProfileService";
import type { ModelOption } from "@/app/newchat/ui/model-selector";
import { automaticModelId } from "@/lib/modelSelection";
import { subscribeRejectedSelection } from "./rejectedSelection";
import {
  readModelSelectionDraft,
  selectModelDraft,
} from "@/lib/conversationModelDrafts";

export function useConversationModelControls(
  models: readonly ModelOption[],
  sessionKey: string,
  defaultModelId?: string,
  controlledModelId?: string,
  conversationId?: number
) {
  const client = useQueryClient();
  const { message } = App.useApp();
  const { t } = useTranslation();
  const persisted = Boolean(conversationId && controlledModelId === undefined);
  const queryKey = [
    "conversation-model-preferences",
    conversationId,
    "selection",
  ];
  const selection = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      getConversationModelSelection(conversationId!, signal),
    enabled: persisted,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const save = useMutation({
    mutationFn: (modelId: string) =>
      patchConversationModelSelection(
        conversationId!,
        Number(modelId),
        selection.data!.version
      ),
    onSuccess: async (result) => {
      client.setQueryData(queryKey, result);
      await client.invalidateQueries({
        queryKey: ["conversation-model-preferences", conversationId],
      });
    },
    onError: async () => {
      message.error(t("modelProfile.preferencesFailed"));
      await client.invalidateQueries({ queryKey });
    },
  });
  const [, refreshDraft] = useState(0);
  const [rejected, setRejected] = useState<Record<string, boolean>>({});
  const selectedId =
    controlledModelId ??
    (persisted
      ? selection.data?.selected_model_id?.toString()
      : readModelSelectionDraft(sessionKey)) ??
    (models.some((model) => model.id === defaultModelId)
      ? defaultModelId
      : automaticModelId(models));
  const model = models.find((item) => item.id === selectedId);
  const scope = JSON.stringify([sessionKey, selectedId]);
  useEffect(
    () =>
      subscribeRejectedSelection((id) => {
        if (String(id) === selectedId)
          setRejected((current) => ({ ...current, [scope]: true }));
      }),
    [selectedId, scope]
  );
  const snapshot = useMemo(
    () => (model ? { model_id: Number(model.id) } : undefined),
    [model?.id]
  );
  return {
    models,
    error:
      (selectedId && !model) || rejected[scope]
        ? t("modelProfile.modelUnavailable")
        : persisted && selection.isError
          ? t("modelProfile.preferencesFailed")
          : undefined,
    selectedModelId: selectedId,
    onModelChange: (modelId: string) => {
      if (!models.some((item) => item.id === modelId)) return;
      setRejected((current) => ({
        ...current,
        [JSON.stringify([sessionKey, modelId])]: false,
      }));
      if (persisted) {
        if (selection.data && !save.isPending) save.mutate(modelId);
      } else {
        selectModelDraft(sessionKey, modelId);
        refreshDraft((version) => version + 1);
      }
    },
    canSend:
      Boolean(model) &&
      !rejected[scope] &&
      !save.isPending &&
      (!persisted || (!selection.isError && !!selection.data)),
    snapshot,
  };
}
