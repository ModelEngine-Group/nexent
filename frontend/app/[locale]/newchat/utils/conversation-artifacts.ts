// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useMemo } from "react";
import type { CompleteAttachment } from "@assistant-ui/react";
import { API_ENDPOINTS } from "@/services/api";
import { skillFileUploadsRegistry } from "../adapter/remote-chat-model-adapter";

/**
 * Loose shape of an assistant-ui thread message as consumed by the artifacts
 * aggregation. Only the fields actually read are declared, mirroring the
 * relaxed typing used by `thread.tsx` for restored content parts.
 */
export interface ArtifactMessageLike {
  id: string;
  role?: string;
  createdAt?: Date | string;
  content?: readonly {
    type?: string;
    /** Marker used by the history adapter for restored artifact messages. */
    isSkillFiles?: boolean;
    skillFileAttachments?: CompleteAttachment[];
  }[];
}

/**
 * One agent-generated file in a conversation, flattened from the per-message
 * attachment payloads for the conversation-level artifacts panel.
 */
export interface ConversationArtifact {
  /** Stable identity combining the source message and attachment id. */
  key: string;
  /** assistant-ui message id the file belongs to. */
  messageId: string;
  /** Message creation time, used to show when the file was generated. */
  createdAt?: Date;
  attachment: CompleteAttachment;
}

/** Attachment fields the artifacts panel reads; keeps rendering loosely typed. */
export type ArtifactAttachmentLike = CompleteAttachment & {
  name?: string;
  contentType?: string;
  size?: number;
  object_name?: string;
  preview_url?: string;
  download_url?: string;
  url?: string;
  presigned_url?: string;
};

/**
 * Collects every agent-generated file across a conversation's messages.
 *
 * Assistant-generated files arrive through two paths that must both be
 * covered:
 *
 * - Streaming: the chat adapter appends a marker text part carrying
 *   `skillFileAttachments` on the assistant message itself.
 * - History restore: the thread history adapter stores the attachments in
 *   `skillFileUploadsRegistry` keyed by message id and leaves only an
 *   `isSkillFiles` marker part on the message.
 *
 * The per-part payload wins when present so live updates are picked up
 * immediately; the registry is the fallback for restored messages.
 */
export function collectConversationArtifacts(
  messages: readonly ArtifactMessageLike[]
): ConversationArtifact[] {
  const artifacts: ConversationArtifact[] = [];
  for (const message of messages) {
    if (message.role !== "assistant") continue;

    const attachments = readMessageArtifacts(message);
    const createdAt = message.createdAt
      ? new Date(message.createdAt)
      : undefined;

    attachments.forEach((attachment, index) => {
      artifacts.push({
        // Attachment ids restart per streaming chunk, so the position within
        // the message keeps the key unique when several chunks contribute.
        key: `${message.id}:${attachment.id}:${index}`,
        messageId: message.id,
        createdAt: Number.isNaN(createdAt?.getTime()) ? undefined : createdAt,
        attachment,
      });
    });
  }
  return artifacts;
}

function readMessageArtifacts(
  message: ArtifactMessageLike
): CompleteAttachment[] {
  const parts = message.content ?? [];
  // Streaming path: the last marker part carries the cumulative attachment
  // list for the message, so later parts supersede earlier ones.
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index];
    if (part?.type === "text" && part.skillFileAttachments?.length) {
      return part.skillFileAttachments;
    }
  }
  // History restore path: attachments live in the module-level registry.
  return skillFileUploadsRegistry.get(message.id) ?? [];
}

/**
 * Memoized wrapper for component consumption. `messages` identity changes on
 * every streamed token, which keeps the artifact list live during generation.
 */
export function useConversationArtifacts(
  messages: readonly ArtifactMessageLike[]
): ConversationArtifact[] {
  return useMemo(() => collectConversationArtifacts(messages), [messages]);
}

/** Raw URL stashed on a file attachment content part, if any. */
const readAttachmentPartUrl = (
  attachment: ArtifactAttachmentLike
): string | undefined => {
  const part = attachment.content?.[0] as { data?: string } | undefined;
  return part?.data;
};

/**
 * Downloads an artifact's bytes so it can be attached to the composer.
 *
 * Prefers the backend stream endpoint for the artifact's `object_name` (same
 * origin, no CORS concerns) and falls back to the attachment's own URLs when
 * no object name is available.
 */
export async function fetchArtifactFile(
  attachment: ArtifactAttachmentLike
): Promise<File> {
  const name = attachment.name || "Generated file";
  const contentType = attachment.contentType || "application/octet-stream";
  const sources: string[] = [];
  if (attachment.object_name) {
    sources.push(
      API_ENDPOINTS.storage.file(attachment.object_name, "stream", name)
    );
  }
  for (const url of [
    attachment.download_url,
    attachment.preview_url,
    attachment.presigned_url,
    attachment.url,
    readAttachmentPartUrl(attachment),
  ]) {
    if (url) sources.push(url);
  }
  if (sources.length === 0) {
    throw new Error(`No downloadable source for artifact: ${name}`);
  }

  let lastError: unknown;
  for (const url of sources) {
    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`Fetch failed with status ${response.status}`);
      }
      const blob = await response.blob();
      return new File([blob], name, { type: contentType });
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError instanceof Error
    ? lastError
    : new Error(`Failed to fetch artifact: ${name}`);
}
