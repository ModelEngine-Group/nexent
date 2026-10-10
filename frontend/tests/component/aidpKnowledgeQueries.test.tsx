import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  focusManager,
} from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import aidpKnowledgeService from "@/ext_components/aidp/services/aidpKnowledgeService";
import {
  useAidpKnowledgeList,
  useAidpKnowledgeCache,
  useCreateAidpKnowledgeBase,
  useDeleteAidpKnowledgeBase,
  useAidpModels,
  useAidpGraphTemplate,
} from "@/ext_components/aidp/hooks/useAidpKnowledgeQueries";
import { ApiError } from "@/services/api";

const auth = vi.hoisted(() => ({ user: { id: "admin", tenantId: "tenant" } }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => auth,
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ enableAidpKnowledge: true, isDeploymentReady: true }),
}));
vi.mock("@/ext_components/aidp/services/aidpKnowledgeService", () => ({
  default: {
    listKbs: vi.fn(),
    createKb: vi.fn(),
    deleteKb: vi.fn(),
    listModels: vi.fn(),
    graphTemplate: vi.fn(),
    getKb: vi.fn(),
  },
}));

const clients: QueryClient[] = [];
const makeWrapper = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
};
const listResponse = (name: string) => ({
  value: [{ kds_id: "1", kds_name: name }],
  total_count: 1,
});
beforeEach(() => {
  auth.user = { id: "admin", tenantId: "tenant" };
  vi.resetAllMocks();
});
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  vi.useRealTimers();
  focusManager.setFocused(undefined);
});

it("polls the current page every 30 seconds and pauses while interacting or hidden", async () => {
  vi.useFakeTimers();
  focusManager.setFocused(true);
  vi.mocked(aidpKnowledgeService.listKbs).mockResolvedValue(
    listResponse("知识库")
  );
  const { wrapper } = makeWrapper();
  const { rerender } = renderHook(
    ({ paused }) => useAidpKnowledgeList(2, 20, "搜索", true, paused),
    {
      wrapper,
      initialProps: { paused: false },
    }
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(2);
  expect(aidpKnowledgeService.listKbs).toHaveBeenLastCalledWith(2, 20, "搜索");
  rerender({ paused: true });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(2);
  rerender({ paused: false });
  focusManager.setFocused(false);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(2);
  await act(async () => {
    focusManager.setFocused(true);
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(3);
});

it("keeps a late response from an earlier search out of the current page", async () => {
  let finishFirst!: (value: ReturnType<typeof listResponse>) => void;
  vi.mocked(aidpKnowledgeService.listKbs)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        })
    )
    .mockResolvedValueOnce(listResponse("新搜索结果"));
  const { client, wrapper } = makeWrapper();
  const { result, rerender } = renderHook(
    ({ page, keyword }) => useAidpKnowledgeList(page, 10, keyword),
    { wrapper, initialProps: { page: 1, keyword: "旧搜索" } }
  );
  await waitFor(() =>
    expect(aidpKnowledgeService.listKbs).toHaveBeenCalledWith(1, 10, "旧搜索")
  );
  rerender({ page: 2, keyword: "新搜索" });
  await waitFor(() =>
    expect(result.current.data?.value[0].kds_name).toBe("新搜索结果")
  );
  await act(async () => finishFirst(listResponse("旧搜索结果")));
  await waitFor(() =>
    expect(
      client.getQueryData([
        "aidpKnowledge",
        "tenant",
        "admin",
        "list",
        { page: 1, pageSize: 10, keyword: "旧搜索" },
      ])
    ).toEqual(listResponse("旧搜索结果"))
  );
  expect(result.current.data?.value[0].kds_name).toBe("新搜索结果");
});

it("isolates cached knowledge lists when the account changes", async () => {
  vi.mocked(aidpKnowledgeService.listKbs)
    .mockResolvedValueOnce(listResponse("管理员知识库"))
    .mockResolvedValueOnce(listResponse("成员知识库"));
  const { wrapper } = makeWrapper();
  const { result, rerender } = renderHook(
    () => useAidpKnowledgeList(1, 10, ""),
    { wrapper }
  );
  await waitFor(() =>
    expect(result.current.data?.value[0].kds_name).toBe("管理员知识库")
  );
  auth.user = { id: "member", tenantId: "tenant" };
  rerender();
  await waitFor(() =>
    expect(result.current.data?.value[0].kds_name).toBe("成员知识库")
  );
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(2);
});

it("refreshes the active list after creation and deletion", async () => {
  vi.mocked(aidpKnowledgeService.listKbs).mockResolvedValue(
    listResponse("知识库")
  );
  vi.mocked(aidpKnowledgeService.createKb).mockResolvedValue({
    kds_id: "2",
    kds_name: "新建",
  });
  vi.mocked(aidpKnowledgeService.deleteKb).mockResolvedValue();
  const { wrapper } = makeWrapper();
  const { result } = renderHook(
    () => ({
      list: useAidpKnowledgeList(1, 10, ""),
      create: useCreateAidpKnowledgeBase(),
      remove: useDeleteAidpKnowledgeBase(),
    }),
    { wrapper }
  );
  await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
  await act(async () => {
    await result.current.create.mutateAsync({
      name: "新建",
      description: "新建知识库的测试描述",
    });
  });
  await waitFor(() =>
    expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(2)
  );
  await act(async () => {
    await result.current.remove.mutateAsync("2");
  });
  await waitFor(() =>
    expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(3)
  );
  expect(aidpKnowledgeService.createKb).toHaveBeenCalledWith({
    name: "新建",
    description: "新建知识库的测试描述",
  });
  expect(aidpKnowledgeService.deleteKb).toHaveBeenCalledWith("2");
});

it("updates cached rows without changing pagination metadata", async () => {
  vi.mocked(aidpKnowledgeService.listKbs).mockResolvedValue({
    ...listResponse("旧名称"),
    total_reliable: false,
  });
  const { wrapper } = makeWrapper();
  const { result } = renderHook(
    () => ({
      list: useAidpKnowledgeList(1, 10, ""),
      cache: useAidpKnowledgeCache(),
    }),
    { wrapper }
  );
  await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
  expect(result.current.list.data?.value[0].kds_name).toBe("旧名称");
  act(() =>
    result.current.cache.updateKnowledgeBase({
      kds_id: "1",
      kds_name: "新名称",
    })
  );
  await waitFor(() =>
    expect(result.current.list.data?.value[0].kds_name).toBe("新名称")
  );
  expect(result.current.list.data?.total_reliable).toBe(false);
  expect(result.current.list.data?.total_count).toBe(1);
});

it("preserves a business error and waits for an explicit retry", async () => {
  const error = new ApiError("130504", "Authentication failed");
  vi.mocked(aidpKnowledgeService.listKbs)
    .mockRejectedValueOnce(error)
    .mockResolvedValueOnce(listResponse("恢复"));
  const { wrapper } = makeWrapper();
  const { result } = renderHook(() => useAidpKnowledgeList(1, 10, ""), {
    wrapper,
  });
  await waitFor(() => expect(result.current.error).toBe(error));
  expect(aidpKnowledgeService.listKbs).toHaveBeenCalledTimes(1);
  await act(async () => {
    await result.current.refetch();
  });
  await waitFor(() =>
    expect(result.current.data?.value[0].kds_name).toBe("恢复")
  );
});

it("reuses the model query and loads graph templates by language only when enabled", async () => {
  vi.mocked(aidpKnowledgeService.listModels).mockResolvedValue({
    service: "",
    app: "KnowledgeBase",
    total_count: 0,
    models: [],
  });
  vi.mocked(aidpKnowledgeService.graphTemplate).mockResolvedValue({
    value: [],
  });
  const { wrapper } = makeWrapper();
  const { result, rerender } = renderHook(
    ({
      graph,
      language,
    }: {
      graph: boolean;
      language: "chinese" | "english";
    }) => ({
      models: useAidpModels(),
      modelsAgain: useAidpModels(),
      template: useAidpGraphTemplate(language, graph),
    }),
    { wrapper, initialProps: { graph: false, language: "chinese" } }
  );
  await waitFor(() => expect(result.current.models.isSuccess).toBe(true));
  expect(aidpKnowledgeService.listModels).toHaveBeenCalledTimes(1);
  expect(aidpKnowledgeService.listModels).toHaveBeenCalledWith(
    "",
    "KnowledgeBase"
  );
  expect(aidpKnowledgeService.graphTemplate).not.toHaveBeenCalled();
  rerender({ graph: true, language: "chinese" });
  await waitFor(() => expect(result.current.template.isSuccess).toBe(true));
  rerender({ graph: true, language: "english" });
  await waitFor(() =>
    expect(aidpKnowledgeService.graphTemplate).toHaveBeenCalledWith("english")
  );
});
