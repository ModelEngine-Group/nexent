import { useState, useRef, useCallback } from "react";

import { useTranslation } from "react-i18next";
import { App } from "antd";

import { modelService } from "@/services/modelService";
import type { CapacitySuggestion, ModelType } from "@/types/modelConfig";

/**
 * Parameters accepted by `suggest()`. Mirrors the wire shape of
 * `modelService.suggestCapacity` so callers can forward form values with
 * minimal translation.
 */
export interface SuggestCapacityParams {
  modelName: string;
  baseUrl?: string;
  providerHint?: string;
  apiKey?: string;
  modelType?: ModelType;
}

/**
 * Shared state machine for the /suggest-capacity API call.
 *
 * Consolidates the capacity-suggestion lifecycle (loading flag, race-condition
 * token, suggestion result, accepted suggestion) that was previously duplicated
 * across ModelEditDialog, ProviderConfigEditDialog, ModelAddDialog (top-level),
 * and ModelAddDialog (gear modal). Each caller owns its own form state and
 * decides how to apply the suggestion; this hook owns only the API interaction
 * and the suggestion/accepted pair.
 *
 * The monotonic request token (`requestRef`) prevents a slow response from
 * overwriting state that a faster, later request has already populated -- the
 * same pattern each call site previously implemented inline.
 */
export function useCapacitySuggestion() {
  const { t } = useTranslation();
  const { message } = App.useApp();

  const [suggestion, setSuggestion] = useState<CapacitySuggestion | null>(null);
  const [acceptedSuggestion, setAcceptedSuggestion] =
    useState<CapacitySuggestion | null>(null);
  const [checking, setChecking] = useState(false);
  const requestRef = useRef(0);

  const suggest = useCallback(
    async (params: SuggestCapacityParams) => {
      if (!params.modelName.trim()) {
        message.warning(t("model.dialog.capacity.suggestion.missingInput"));
        return;
      }
      const myToken = (requestRef.current += 1);
      setChecking(true);
      try {
        const result = await modelService.suggestCapacity(params);
        if (myToken !== requestRef.current) return;
        setSuggestion(result);
        if (!result.suggestions) {
          setAcceptedSuggestion(null);
        }
      } catch {
        if (myToken !== requestRef.current) return;
        setSuggestion(null);
        setAcceptedSuggestion(null);
        message.error(t("model.dialog.capacity.suggestion.failed"));
      } finally {
        if (myToken === requestRef.current) {
          setChecking(false);
        }
      }
    },
    [t, message]
  );

  const reset = useCallback(() => {
    setSuggestion(null);
    setAcceptedSuggestion(null);
    setChecking(false);
  }, []);

  return {
    suggestion,
    setSuggestion,
    acceptedSuggestion,
    setAcceptedSuggestion,
    checking,
    suggest,
    reset,
  };
}
