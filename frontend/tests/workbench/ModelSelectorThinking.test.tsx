// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import { ModelSelector } from "@/app/newchat/ui/model-selector";

const register = vi.hoisted(() =>
  vi.fn((entry: { getModelContext: () => unknown }) => {
    void entry;
    return () => undefined;
  })
);
const modelApi = vi.hoisted(() => ({
  modelContext: () => ({ register }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => modelApi,
}));
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  PopoverContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/ui/command", () => ({
  Command: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CommandInput: () => <input />,
  CommandList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CommandEmpty: () => null,
  CommandGroup: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  CommandItem: ({
    children,
    onSelect,
    value,
  }: {
    children: ReactNode;
    onSelect?: (value: string) => void;
    value: string;
  }) => (
    <button type="button" onClick={() => onSelect?.(value)}>
      {children}
    </button>
  ),
  CommandSeparator: () => null,
}));

const profileEditor = vi.hoisted(() => vi.fn());
vi.mock("@/components/model/ConversationModelParameters", () => ({
  ConversationModelParameters: (props: Record<string, unknown>) => {
    profileEditor(props);
    return <div data-testid="shared-profile-editor" />;
  },
}));

it.each([undefined, 123])(
  "SU-AC-01 uses the same profile editor for draft and saved Agent conversations (%s)",
  (conversationId) => {
    render(
      <ModelSelector
        models={[
          {
            id: "42",
            name: "Profile",
            profileSchemaVersion: 1,
            agentParameterDefaults: { temperature: 0.4 },
          },
        ]}
        value="42"
        conversationId={conversationId}
        parameterSettingsScopeKey="thread-scope"
      />
    );
    expect(screen.getByTestId("shared-profile-editor")).toBeVisible();
    expect(profileEditor).toHaveBeenCalledWith(
      expect.objectContaining({
        conversationId,
        draftScope: "thread-scope",
        modelId: 42,
        agentDefaults: { temperature: 0.4 },
      })
    );
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  }
);

it("SU-AC-05 does not fabricate a legacy parameter editor for an unresolved outlet", () => {
  render(
    <ModelSelector models={[{ id: "42", name: "Unresolved" }]} value="42" />
  );
  expect(screen.queryByTestId("shared-profile-editor")).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
});
