// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useAgentFileImport } from "@/hooks/agent/useAgentFileImport";
import { openImportWizardWithFile } from "@/lib/agentImportUtils";

vi.mock("antd", () => ({
  App: { useApp: () => ({ message: { error: vi.fn() } }) },
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/agentImportUtils", () => ({
  openImportWizardWithFile: vi.fn(),
}));

it("opens the wizard with parsed file data and clears it on cancellation", async () => {
  const data = { agent_id: 42, agent_info: { 42: { name: "fixture_agent" } } };
  vi.mocked(openImportWizardWithFile)
    .mockImplementationOnce(async ({ onSuccess }) => onSuccess(data))
    .mockResolvedValueOnce(undefined);
  const { result } = renderHook(useAgentFileImport);

  expect(result.current.importData).toBeNull();
  await act(async () => result.current.openImport());
  expect(result.current.importData).toBe(data);
  act(() => result.current.closeImport());
  expect(result.current.importData).toBeNull();
  await act(async () => result.current.openImport());
  expect(result.current.importData).toBeNull();
});
