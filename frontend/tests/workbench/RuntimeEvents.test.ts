import { expect, it, vi } from "vitest";
import { notifyWorkbenchConfigResolved } from "@/features/workbench/runtimeEvents";

it("UT-FE-WB-034 accepts normalized version acknowledgements as object or JSON", () => {
  const version = vi.fn();
  notifyWorkbenchConfigResolved(
    { schema_version: 3, config_version: 2 },
    version
  );
  notifyWorkbenchConfigResolved(
    '{"schema_version":3,"config_version":4}',
    version
  );
  expect(version.mock.calls).toEqual([[2], [4]]);
});
it("UT-FE-WB-034 ignores malformed or incompatible version acknowledgements", () => {
  const version = vi.fn();
  for (const value of [
    null,
    "{",
    { schema_version: 2, config_version: 2 },
    { schema_version: 3, config_version: -1 },
    { schema_version: 3, config_version: "3" },
  ]) {
    notifyWorkbenchConfigResolved(value, version);
  }
  expect(version).not.toHaveBeenCalled();
});
