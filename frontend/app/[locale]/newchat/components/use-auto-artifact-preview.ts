// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ArtifactAttachmentLike,
  ConversationArtifact,
} from "../utils/conversation-artifacts";

const DOCUMENT_EXTENSIONS = new Set([
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
  "pdf",
  "txt",
  "md",
  "markdown",
  "csv",
  "tsv",
  "html",
  "htm",
]);
const OFFICE_EXTENSIONS = new Set([
  "doc",
  "docx",
  "xls",
  "xlsx",
  "ppt",
  "pptx",
]);

export function artifactPreviewIdentity(
  artifact: ConversationArtifact
): string {
  return (
    (artifact.attachment as ArtifactAttachmentLike).object_name || artifact.key
  );
}

function documentPriority(artifact: ConversationArtifact): number {
  const attachment = artifact.attachment as ArtifactAttachmentLike;
  const extension = attachment.name?.split(".").pop()?.toLowerCase() ?? "";
  const part = attachment.content?.[0] as { data?: string } | undefined;
  if (
    !DOCUMENT_EXTENSIONS.has(extension) ||
    !(
      attachment.object_name ||
      attachment.preview_url ||
      attachment.download_url ||
      attachment.presigned_url ||
      attachment.url ||
      part?.data
    )
  )
    return 0;
  return OFFICE_EXTENSIONS.has(extension) ? 3 : extension === "pdf" ? 2 : 1;
}

interface AutoArtifactPreviewOptions {
  scopeKey: string;
  artifacts: readonly ConversationArtifact[];
  isRunning: boolean;
  isLoading: boolean;
  enabled: boolean;
}

/** Observe live output publication without treating restored history as a new run. */
export function useAutoArtifactPreview({
  scopeKey,
  artifacts,
  isRunning,
  isLoading,
  enabled,
}: AutoArtifactPreviewOptions) {
  const [selection, setSelection] = useState<{
    scope: string;
    identity: string;
  } | null>(null);
  const tracking = useRef({
    scope: scopeKey,
    ready: false,
    running: false,
    observedRun: false,
    dismissed: false,
    priority: 0,
    seen: new Set<string>(),
    pending: null as ConversationArtifact | null,
  });

  useEffect(() => {
    if (tracking.current.scope !== scopeKey || isLoading) {
      tracking.current = {
        scope: scopeKey,
        ready: false,
        running: false,
        observedRun: false,
        dismissed: false,
        priority: 0,
        seen: new Set(),
        pending: null,
      };
      // Loading or switching the external runtime invalidates the old selection.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelection(null);
    }
    const state = tracking.current;
    if (isLoading) return;
    if (!state.ready) {
      state.ready = true;
      state.seen = new Set(artifacts.map(artifactPreviewIdentity));
    }
    if (isRunning && !state.running) {
      state.observedRun = true;
      state.dismissed = false;
      state.pending = null;
      state.priority = 0;
    }
    state.running = isRunning;
    for (const artifact of artifacts) {
      const identity = artifactPreviewIdentity(artifact);
      if (state.seen.has(identity)) continue;
      if (documentPriority(artifact) === 0) continue;
      state.seen.add(identity);
      if (
        enabled &&
        state.observedRun &&
        documentPriority(artifact) > 0 &&
        documentPriority(artifact) >= state.priority
      ) {
        state.pending = artifact;
        state.priority = documentPriority(artifact);
      }
    }
    if (enabled && !isRunning && !state.dismissed && state.pending) {
      const identity = artifactPreviewIdentity(state.pending);
      state.pending = null;
      // Live run completion is an external runtime event, not derived render state.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelection({ scope: scopeKey, identity });
    }
  }, [scopeKey, artifacts, isRunning, isLoading, enabled]);

  const open = useCallback(
    (artifact: ConversationArtifact) => {
      setSelection({
        scope: scopeKey,
        identity: artifactPreviewIdentity(artifact),
      });
    },
    [scopeKey]
  );
  const close = useCallback(() => {
    tracking.current.dismissed = true;
    tracking.current.pending = null;
    setSelection(null);
  }, []);

  return {
    selected:
      !isLoading && selection?.scope === scopeKey
        ? (artifacts.find(
            (artifact) =>
              artifactPreviewIdentity(artifact) === selection.identity
          ) ?? null)
        : null,
    open,
    close,
  };
}
