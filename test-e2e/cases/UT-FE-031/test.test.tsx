import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  buildCapacityPayload,
  emptyCapacityForm,
  validateCapacityForm,
} from "@/app/[locale]/models/components/model/ModelCapacityFields";
import {
  advancedSettingsValueFromRecord,
  buildInferenceParamsPayload,
} from "@/app/[locale]/models/components/model/ModelAdvancedSettings";
import { isValidMaxTokens, parseMaxTokens } from "@/app/[locale]/models/components/model/ModelMaxTokensInput";
import {
  canAnalyzeAutomationMessage,
  createPreparingAutomationMessage,
  resolveAutomationProposalMessage,
} from "@/features/agentAutomation/chatAdapter";
import { parseAutomationProposal } from "@/features/agentAutomation/parseProposal";
import { formValuesToProposalPatch } from "@/features/agentAutomation/scheduleForm";
import { isValidAgentDescription, isValidAgentDisplayName, isValidAgentName } from "@/hooks/agent/useSaveGuard";
import { canManageModels } from "@/lib/auth";
import {
  DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES,
  canViewMonitoringDashboard,
} from "@/lib/monitoringAccess";
import { isEmbeddingModelCompatible, isMultimodalConstraintMismatch } from "@/lib/knowledgeBaseCompatibility";
import { detectProviderError, processProviderResponse } from "@/lib/providerError";
import {
  detectCsvDelimiter,
  getPreviewAccessReasonFromStatus,
  ignoreAbortError,
  parseCsvLine,
  updateChunkRangeState,
} from "@/lib/filePreviewUtils";
import {
  getMineCardMenuActions,
  isCancelableRepositoryStatus,
  isTakeDownableRepositoryStatus,
  pickLatestSharedVersionName,
} from "@/lib/agentRepositoryMine";
import {
  extractMcpErrorMessage,
  filterServiceCards,
  findMissingRequiredField,
  hasUnresolvedUrlTemplate,
  isValidPort,
  paginateItems,
} from "@/lib/mcpTools";
import { calculateConversationViewport } from "@/lib/conversationViewport";
import { shouldContinueConversationPageLoading } from "@/lib/conversationLoadPolicy";
import { extractMarkdownHeadings } from "@/components/common/markdownRenderer";
import { extractSkillInfoFromContent, isSkillMdFile, normalizeSkillFiles } from "@/lib/skillFileUtils";
import { getQuotaConflictTranslationKey, getQuotaExceededMessage, isQuotaExceededError } from "@/types/quota";
import { validateAidpFiles, validateFileType } from "@/services/uploadService";
import { getLocalFileDownloadUrl, getLocalFilePreviewUrl } from "@/services/storageService";
import { toApiError } from "@/services/api";
import { formatNotificationMessage } from "@/lib/notificationMessage";
import { buildRepositoryReviewDeepLink, parseReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { parseSelection, serializeSelection } from "@/app/[locale]/agents/components/knowledge-base-search";
import { transformMessagesToTaskMessages } from "@/app/[locale]/chat/streaming/messageTransformer";
import { upsertHistorySummaryInMessages } from "@/app/[locale]/chat/streaming/chatStreamHandler";
import { isNewAgentPaddingItem } from "@/types/agentRepository";
import { getToolParamOptions } from "@/const/agentConfig";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";


const t = ((key: string) => key) as any;

describe("D1 frontend functional components and state reducers", () => {
  it("UT-FE-031 calculates conversation pagination viewport and stop policy", () => {
    const viewport = calculateConversationViewport({
      containerHeight: 300, rowHeight: 40, groupHeaderHeight: 24, groupCounts: [1, 2, 30],
    });
    expect(viewport.initialLimit).toBeGreaterThan(0);
    expect(shouldContinueConversationPageLoading({
      hasMore: false, loadedAfter: 20, loadedBefore: 10, isNearLoadedBoundary: true,
    })).toBe(false);
  });
});
