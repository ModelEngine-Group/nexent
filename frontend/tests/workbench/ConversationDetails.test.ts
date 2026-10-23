// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { QueryClient } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { createConversationDetailLoader } from "@/lib/conversationDetails";
import { conversationService } from "@/services/conversationService";
import type { ApiConversationDetail } from "@/types/conversation";

const clients: QueryClient[] = [];
function setup(identity = "tenant/user") {
  const client = new QueryClient();
  clients.push(client);
  return { client, loader: createConversationDetailLoader(client, identity) };
}
const detail = (version: number) =>
  ({
    conversation_id: 42,
    create_time: 0,
    message: [],
    workbench_config_version: version,
  }) as ApiConversationDetail;
function deferred() {
  let resolve!: (value: ApiConversationDetail) => void;
  const promise = new Promise<ApiConversationDetail>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
afterEach(() => clients.splice(0).forEach((client) => client.clear()));

it("shares six pending and settled restoration readers without a second GET", async () => {
  const response = deferred();
  const get = vi
    .spyOn(conversationService, "getById")
    .mockReturnValue(response.promise);
  const { loader } = setup();
  loader.activate("42");
  const first = loader.load("42");
  const other = loader.load("42");
  response.resolve(detail(1));
  expect(await first).toBe(await other);
  for (let i = 0; i < 4; i++) expect(await loader.load("42")).toBe(await first);
  loader.activate("42");
  expect(await loader.load("42")).toBe(await first);
  expect(get).toHaveBeenCalledExactlyOnceWith("42");
});

it("a real A to B to A activation obtains fresh detail", async () => {
  const get = vi
    .spyOn(conversationService, "getById")
    .mockResolvedValueOnce(detail(1))
    .mockResolvedValueOnce(detail(2))
    .mockResolvedValueOnce(detail(3));
  const { loader } = setup();
  loader.activate("42");
  await loader.load("42");
  loader.activate("43");
  await loader.load("43");
  loader.activate("42");
  expect((await loader.load("42")).workbench_config_version).toBe(3);
  expect(get.mock.calls.map(([id]) => id)).toEqual(["42", "43", "42"]);
});

it("late old A cannot replace a new A activation or cancel its readers", async () => {
  const old = deferred();
  const fresh = deferred();
  vi.spyOn(conversationService, "getById")
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(fresh.promise);
  const { loader } = setup();
  loader.activate("42");
  const a = loader.load("42");
  loader.activate("43");
  loader.activate("42");
  const next = loader.load("42");
  fresh.resolve(detail(2));
  expect(await next).toEqual(detail(2));
  old.resolve(detail(1));
  expect(await a).toEqual(detail(1));
  expect(await loader.load("42")).toEqual(detail(2));
});

it("a failed restoration is shared without fan-out retries and re-entry retries it", async () => {
  const get = vi
    .spyOn(conversationService, "getById")
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValueOnce(detail(2));
  const { loader } = setup();
  loader.activate("42");
  await expect(loader.load("42")).rejects.toThrow("unavailable");
  await expect(loader.load("42")).rejects.toThrow("unavailable");
  expect(get).toHaveBeenCalledTimes(1);
  loader.activate(undefined);
  loader.activate("42");
  expect(await loader.load("42")).toEqual(detail(2));
  expect(get).toHaveBeenCalledTimes(2);
});

it("a conflict refresh and post-run invalidation bypass prior detail", async () => {
  const get = vi
    .spyOn(conversationService, "getById")
    .mockResolvedValueOnce(detail(1))
    .mockResolvedValueOnce(detail(2))
    .mockResolvedValueOnce(detail(3));
  const { loader } = setup();
  await loader.load("42");
  expect(await loader.refresh("42")).toEqual(detail(2));
  expect(await loader.load("42")).toEqual(detail(2));
  loader.invalidate("42");
  expect(await loader.load("42")).toEqual(detail(3));
  expect(get).toHaveBeenCalledTimes(3);
});

it("scopes and remounts never reuse private conversation data; cleanup removes queries", async () => {
  const get = vi
    .spyOn(conversationService, "getById")
    .mockResolvedValue(detail(1));
  const { loader, client } = setup();
  await loader.load("42");
  const other = createConversationDetailLoader(client, "other-tenant/user");
  await other.load("42");
  const remounted = createConversationDetailLoader(client, "tenant/user");
  await remounted.load("42");
  expect(get).toHaveBeenCalledTimes(3);
  loader.clear();
  other.clear();
  remounted.clear();
  expect(client.getQueryCache().getAll()).toHaveLength(0);
});

it.each(["", "0", "-1", "NaN", "workbench-draft:local"])(
  "does not request invalid or unsent identity %s",
  async (id) => {
    const get = vi.spyOn(conversationService, "getById");
    await expect(setup().loader.load(id)).rejects.toThrow(
      "Invalid conversation ID"
    );
    expect(get).not.toHaveBeenCalled();
  }
);
