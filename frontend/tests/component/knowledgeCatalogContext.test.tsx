// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  KnowledgeBaseProvider,
  useKnowledgeBaseContext,
} from "../../app/[locale]/knowledges/contexts/KnowledgeBaseContext";
import knowledgeBaseService from "@/services/knowledgeBaseService";

const configuration = vi.hoisted(() => ({
  datamateUrl: null as string | null,
}));
const translate = (key: string) => key;
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: translate }) }));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ appConfig: configuration }),
}));
vi.mock("@/services/knowledgeBaseService", () => ({
  default: { getKnowledgeBasesInfo: vi.fn() },
}));

describe("local catalog server pagination", () => {
  beforeEach(() => {
    configuration.datamateUrl = null;
    vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo)
      .mockReset()
      .mockResolvedValue({ knowledgeBases: [], total: 30, hasMore: false });
  });

  it("retains offset, limit and filters through explicit refreshes", async () => {
    const { result } = renderHook(useKnowledgeBaseContext, {
      wrapper: KnowledgeBaseProvider,
    });
    await act(async () => {
      await result.current.fetchKnowledgeBases(true, false, false, {
        offset: 24,
        limit: 12,
        keyword: "test",
        sources: ["nexent"],
      });
    });
    expect(knowledgeBaseService.getKnowledgeBasesInfo).toHaveBeenLastCalledWith(
      true,
      false,
      null,
      null,
      expect.objectContaining({ offset: 24, limit: 12, keyword: "test" }),
      { strict: true }
    );
    await act(async () => {
      await result.current.refreshKnowledgeBaseData();
    });
    expect(knowledgeBaseService.getKnowledgeBasesInfo).toHaveBeenLastCalledWith(
      false,
      true,
      null,
      null,
      expect.objectContaining({ offset: 24, limit: 12, sources: ["nexent"] }),
      { strict: true }
    );
    await act(async () => {
      await result.current.refreshKnowledgeBaseDataWithDataMate();
    });
    expect(knowledgeBaseService.getKnowledgeBasesInfo).toHaveBeenLastCalledWith(
      false,
      true,
      null,
      null,
      expect.objectContaining({ offset: 24, limit: 12 }),
      { strict: true }
    );
  });

  it("resets offset when the caller starts a new filter and exposes failures", async () => {
    const { result } = renderHook(useKnowledgeBaseContext, {
      wrapper: KnowledgeBaseProvider,
    });
    await act(async () => {
      await result.current.fetchKnowledgeBases(true, false, false, {
        offset: 12,
        limit: 12,
      });
    });
    await act(async () => {
      await result.current.fetchKnowledgeBases(true, false, false, {
        offset: 0,
        limit: 20,
        keyword: "new",
      });
    });
    expect(knowledgeBaseService.getKnowledgeBasesInfo).toHaveBeenLastCalledWith(
      true,
      false,
      null,
      null,
      { offset: 0, limit: 20, keyword: "new" },
      { strict: true }
    );
    vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockRejectedValueOnce(
      new Error("offline")
    );
    await act(async () => {
      await result.current.fetchKnowledgeBases(true, false, false);
    });
    expect(result.current.state.error).toBe(
      "knowledgeBase.error.fetchListRetry"
    );
    expect(result.current.state.isLoading).toBe(false);
  });
  it("reads the canonical page after DataMate synchronization instead of appending all synced records", async () => {
    configuration.datamateUrl = "http://datamate.test";
    vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo)
      .mockResolvedValueOnce({
        knowledgeBases: [],
        total: 25,
        dataMateSyncError: undefined,
      })
      .mockResolvedValueOnce({
        knowledgeBases: [],
        total: 25,
        hasMore: true,
        nextOffset: 24,
      });
    const { result } = renderHook(useKnowledgeBaseContext, {
      wrapper: KnowledgeBaseProvider,
    });
    await act(async () => {
      await result.current.fetchKnowledgeBases(true, false, true, {
        offset: 12,
        limit: 12,
      });
    });
    expect(knowledgeBaseService.getKnowledgeBasesInfo).toHaveBeenNthCalledWith(
      2,
      true,
      false,
      null,
      "http://datamate.test",
      { offset: 12, limit: 12 },
      { strict: true }
    );
    expect(result.current.listPagination.total).toBe(25);
    expect(result.current.listPagination.nextOffset).toBe(24);
  });

  it("ignores an older page response after a newer page has completed", async () => {
    let resolveFirst!: (value: {
      knowledgeBases: never[];
      total: number;
    }) => void;
    const firstResult = new Promise<{ knowledgeBases: never[]; total: number }>(
      (resolve) => {
        resolveFirst = resolve;
      }
    );
    vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo)
      .mockReturnValueOnce(firstResult)
      .mockResolvedValueOnce({ knowledgeBases: [], total: 20 });
    const { result } = renderHook(useKnowledgeBaseContext, {
      wrapper: KnowledgeBaseProvider,
    });
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.fetchKnowledgeBases(true, false, false, {
        offset: 12,
        limit: 12,
      });
    });
    await act(async () => {
      await result.current.fetchKnowledgeBases(true, false, false, {
        offset: 0,
        limit: 20,
      });
    });
    await act(async () => {
      resolveFirst({ knowledgeBases: [], total: 99 });
      await pending;
    });
    expect(result.current.listPagination.total).toBe(20);
    expect(result.current.state.isLoading).toBe(false);
  });
});
