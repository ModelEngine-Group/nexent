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
import { parseSelection, serializeSelection } from "@/app/[locale]/agents/[agentId]/components/knowledge-base-search";
import { transformMessagesToTaskMessages } from "@/app/[locale]/chat/streaming/messageTransformer";
import { upsertHistorySummaryInMessages } from "@/app/[locale]/chat/streaming/chatStreamHandler";
import { isNewAgentPaddingItem } from "@/types/agentRepository";
import { getToolParamOptions } from "@/const/agentConfig";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";


const t = ((key: string) => key) as any;

describe("D1 frontend functional components and state reducers", () => {
  it("UT-FE-002 validates the complete agent draft before save", () => {
    expect(isValidAgentName("agent_name")).toBe(true);
    expect(isValidAgentDisplayName("Agent display name")).toBe(true);
    expect(isValidAgentDescription("purpose")).toBe(true);
    expect(isValidAgentName(" ")).toBe(false);

    const repoRoot = process.env.NEXENT_REPO || process.env.NEXENT_REPO_ROOT;
    if (!repoRoot) {
      throw new Error("NEXENT_REPO must point to the local Nexent checkout");
    }
    const pageSource = readFileSync(join(repoRoot, "frontend/app/[locale]/agents/[agentId]/page.tsx"), "utf8");
    const versionSource = readFileSync(join(repoRoot, "frontend/app/[locale]/agents/agent-version.tsx"), "utf8");
    const selectorSource = readFileSync(
      join(repoRoot, "frontend/app/[locale]/agents/[agentId]/components/advanced/collaborative-agent-selector-modal.tsx"),
      "utf8",
    );
    expect(pageSource).toMatch(/onRefreshAgentInfo=\{refetchAgentInfo\}/);
    expect(versionSource).toMatch(/onRefreshAgentInfo: \(\) => Promise<Agent \| null>/);
    expect(selectorSource).toMatch(/agent\.collaborative\.selector\.versionName/);
    expect(selectorSource).toMatch(/name:\s*internalAgent\.version_name/);
  });
});
