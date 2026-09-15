const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");
const ts = require("typescript");

function serviceWithResponse(response) {
  const source = readFileSync(
    join(__dirname, "../services/memoryService.ts"),
    "utf8"
  );
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  });
  const exports = {};
  const requests = [];
  const dependencies = {
    "./api": {
      API_ENDPOINTS: { memory: { config: { load: "/load", set: "/set" } } },
      fetchWithErrorHandling: async (url, options) => {
        requests.push({ url, ...options });
        if (response instanceof Error) throw response;
        return { json: async () => response };
      },
    },
    "@/lib/auth": { getAuthHeaders: () => ({}) },
    "@/lib/logger": { default: { error() {} } },
  };
  runInNewContext(outputText, {
    exports,
    require: (name) => dependencies[name] || {},
    window: new EventTarget(),
    CustomEvent,
  });
  return { service: exports, requests };
}

test("strict configuration reads propagate failures instead of enabling memory", async () => {
  const error = new Error("configuration unavailable");
  const { service } = serviceWithResponse(error);
  await assert.rejects(service.loadMemoryConfig({ throwOnError: true }), error);
  assert.equal((await service.loadMemoryConfig()).memoryEnabled, true);
});

test("persisted disabled memory remains disabled on a fresh configuration read", async () => {
  const { service } = serviceWithResponse({ MEMORY_SWITCH: "N" });
  assert.equal(
    (await service.loadMemoryConfig({ throwOnError: true })).memoryEnabled,
    false
  );
});

test("successful saves notify mounted consumers and unsubscribe removes listeners", async () => {
  const { service, requests } = serviceWithResponse({ success: true });
  const changes = [];
  const unsubscribe = service.subscribeMemorySwitch((enabled) =>
    changes.push(enabled)
  );
  assert.equal(await service.setMemorySwitch(false), true);
  assert.deepEqual(changes, [false]);
  assert.deepEqual(JSON.parse(requests[0].body), {
    key: "MEMORY_SWITCH",
    value: false,
  });
  unsubscribe();
  await service.setMemorySwitch(true);
  assert.deepEqual(changes, [false]);
});

for (const response of [{ success: false }, new Error("save failed")]) {
  test(`failed saves do not announce a disabled switch: ${String(response)}`, async () => {
    const { service } = serviceWithResponse(response);
    const changes = [];
    service.subscribeMemorySwitch((enabled) => changes.push(enabled));
    assert.equal(await service.setMemorySwitch(false), false);
    assert.deepEqual(changes, []);
  });
}
