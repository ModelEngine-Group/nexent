// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useAuiState } from "@assistant-ui/react";
import type { SourceAttributes } from "@/types/source";
import {
  buildCitationDisplayIndexMap,
  getCitationKey,
  withCitationDisplayIndices,
} from "@/lib/citationDisplay";
import {
  searchSourcesRegistry,
  conversationSourcesRegistry,
  type SearchSource,
} from "../adapter/remote-chat-model-adapter";
import type { PanelSourceItem } from "./sources-panel";

export interface MessageSourcePart extends SourceAttributes {
  type?: string;
  sourceType?: string;
  publishedDate?: string;
  url?: string;
  title?: string;
  text?: string;
  filename?: string;
  downloadUrl?: string;
  objectName?: string;
  citeIndex?: number | string;
  toolSign?: string;
  isImage?: boolean;
  imageKey?: string;
  messageId?: string;
  retrievalHighlightTerms?: string[];
}

const emptySources: readonly SearchSource[] = [];
const snapshots = new WeakMap<
  readonly MessageSourcePart[],
  {
    messageId: string | undefined;
    registered: readonly SearchSource[];
    model: MessageSources;
  }
>();

export interface MessageSources {
  messageId: string | undefined;
  content: readonly MessageSourcePart[];
  all: PanelSourceItem[];
  sources: PanelSourceItem[];
  images: PanelSourceItem[];
  displayIndices: Map<string, number>;
  byKey: Map<string, PanelSourceItem>;
  byLegacyIndex: Map<number, PanelSourceItem>;
}

/** Cache only as long as the immutable message content remains reachable. */
export function getMessageSources(
  messageId: string | undefined,
  content: readonly MessageSourcePart[],
  registered: readonly SearchSource[] = emptySources
): MessageSources {
  const cached = snapshots.get(content);
  if (
    cached &&
    cached.messageId === messageId &&
    cached.registered === registered
  )
    return cached.model;
  const contentSources = content.filter((part) => part.type === "source");
  const rawSources: MessageSourcePart[] = [];
  const objects = new Set<MessageSourcePart>();
  const identities = new Set<string>();
  // History can put the same image in both collections. Zero is a placeholder,
  // so uncited images need their image key or URL instead of a citation key.
  for (const source of [...contentSources, ...registered]) {
    const index = Number(source.citeIndex);
    const citationKey =
      Number.isInteger(index) && index > 0
        ? getCitationKey({ citeIndex: index, toolSign: source.toolSign })
        : undefined;
    const identity = citationKey
      ? `citation:${citationKey}`
      : source.isImage && source.imageKey
        ? `image-key:${source.imageKey}`
        : source.isImage && source.url
          ? `image-url:${source.url}`
          : undefined;
    if (objects.has(source) || (identity && identities.has(identity))) continue;
    objects.add(source);
    if (identity) identities.add(identity);
    rawSources.push(source);
  }
  const items: PanelSourceItem[] = rawSources.map((source) => {
    const index = Number(source.citeIndex);
    return {
      sourceType:
        source.sourceType === "file" || source.sourceType === "document"
          ? "document"
          : "url",
      url: source.url,
      title:
        source.title ||
        source.filename ||
        source.url ||
        `Source ${source.citeIndex ?? ""}`,
      text: source.text,
      filename: source.filename,
      downloadUrl: source.downloadUrl,
      objectName: source.objectName,
      publishedDate: source.publishedDate,
      citeIndex: Number.isFinite(index) ? index : undefined,
      toolSign: source.toolSign,
      isImage: source.isImage,
      imageKey: source.imageKey,
      retrievalHighlightTerms: source.retrievalHighlightTerms,
      searchType: source.searchType,
      sourceMetadata: source.sourceMetadata,
      sourceReference: source.sourceReference,
    };
  });
  const displayIndices = buildCitationDisplayIndexMap(content, items);
  const all = withCitationDisplayIndices(items, displayIndices);
  const sources: PanelSourceItem[] = [],
    images: PanelSourceItem[] = [];
  const byKey = new Map<string, PanelSourceItem>();
  const byLegacyIndex = new Map<number, PanelSourceItem>();
  for (const item of all) {
    (item.isImage ? images : sources).push(item);
    const key = getCitationKey(item);
    if (key !== undefined && !byKey.has(key)) byKey.set(key, item);
    if (item.citeIndex !== undefined && !byLegacyIndex.has(item.citeIndex))
      byLegacyIndex.set(item.citeIndex, item);
  }
  const model = {
    messageId,
    content,
    all,
    sources,
    images,
    displayIndices,
    byKey,
    byLegacyIndex,
  };
  snapshots.set(content, { messageId, registered, model });
  return model;
}

export function findMessageSource(model: MessageSources, citationKey: string) {
  const key = citationKey.trim().toLowerCase();
  return (
    model.byKey.get(key) ??
    (/^\d+$/.test(key) ? model.byLegacyIndex.get(Number(key)) : undefined)
  );
}

export function useMessageSources(): MessageSources {
  const messageId = useAuiState(
    (state) => state.message.id as string | undefined
  );
  const content = useAuiState(
    (state) => state.message.content as readonly MessageSourcePart[]
  );
  const registryId =
    content.find((part) => part.type === "source" && part.messageId)
      ?.messageId ?? messageId;
  const registered = registryId
    ? (searchSourcesRegistry.get(registryId) ??
      conversationSourcesRegistry.get(registryId))
    : undefined;
  return getMessageSources(messageId, content, registered ?? emptySources);
}
