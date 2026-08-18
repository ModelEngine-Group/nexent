import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import { handleHealthRequest } from "../server-health.js";

class FakeResponse extends EventEmitter {
  statusCode;
  headers;
  body;

  writeHead(statusCode, headers) {
    this.statusCode = statusCode;
    this.headers = headers;
  }

  end(body = "") {
    this.body = body;
    this.emit("finish");
  }
}

test("live and ready return process-local health", () => {
  const live = new FakeResponse();
  const ready = new FakeResponse();

  assert.equal(
    handleHealthRequest("/health/live", { method: "GET" }, live),
    true
  );
  assert.equal(
    handleHealthRequest("/health/ready", { method: "GET" }, ready),
    true
  );

  assert.equal(live.statusCode, 200);
  assert.deepEqual(JSON.parse(live.body), { status: "alive" });
  assert.equal(ready.statusCode, 200);
  assert.deepEqual(JSON.parse(ready.body), { status: "ready" });
});

test("health routes reject unsupported methods", () => {
  const response = new FakeResponse();

  assert.equal(
    handleHealthRequest("/health/live", { method: "POST" }, response),
    true
  );
  assert.equal(response.statusCode, 405);
  assert.deepEqual(JSON.parse(response.body), {
    message: "Method not allowed.",
  });
});

test("non-health routes are ignored", () => {
  assert.equal(
    handleHealthRequest(
      "/api/frontend-config",
      { method: "GET" },
      new FakeResponse()
    ),
    false
  );
});
