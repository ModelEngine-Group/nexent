// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { test } from "node:test";
import type { Page, Request } from "playwright/test";
import { waitForTfpRunTransport } from "./tfp-run-transport.ts";

function request(errorText?: string): Request {
  return { failure: () => errorText ? { errorText } : null } as Request;
}

test("retains a successful completion that arrives before the owned request is returned", async () => {
  const events = new EventEmitter();
  const owned = request();
  await waitForTfpRunTransport(events as unknown as Page, async () => {
    events.emit("requestfinished", owned);
    return owned;
  }, async () => assert.fail("normal completion needs no abort verification"));
  assert.deepEqual(events.eventNames(), []);
});

test("verifies only the owned browser abort, including an early abort", async () => {
  const events = new EventEmitter();
  const owned = request("net::ERR_ABORTED");
  let verified = 0;
  await waitForTfpRunTransport(events as unknown as Page, async () => {
    events.emit("requestfinished", request());
    events.emit("requestfailed", owned);
    return owned;
  }, async () => { verified += 1; });
  assert.equal(verified, 1);
  assert.deepEqual(events.eventNames(), []);
});

test("preserves a history failure after the owned request is aborted", async () => {
  const events = new EventEmitter();
  const owned = request("net::ERR_ABORTED");
  await assert.rejects(waitForTfpRunTransport(events as unknown as Page, async () => {
    setImmediate(() => events.emit("requestfailed", owned));
    return owned;
  }, async () => { throw new Error("Owned history is still streaming"); }), /still streaming/);
  assert.deepEqual(events.eventNames(), []);
});

test("rejects other network errors and ignores a sibling request's completion", async () => {
  const events = new EventEmitter();
  const page = events as unknown as Page;
  const broken = request("net::ERR_CONNECTION_RESET");
  const unexpectedRecovery = async () => assert.fail("only browser aborts may use history verification");
  await assert.rejects(waitForTfpRunTransport(page, async () => {
    events.emit("requestfailed", broken);
    return broken;
  }, unexpectedRecovery), /ERR_CONNECTION_RESET/);
  await assert.rejects(waitForTfpRunTransport(page, async () => {
    events.emit("requestfinished", request());
    return request();
  }, unexpectedRecovery, 5), { name: "TimeoutError" });
  assert.deepEqual(events.eventNames(), []);
});
