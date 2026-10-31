// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zh from "@/public/locales/zh/common.json";
import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResourceSelectionActions } from "@/features/workbench/components/ResourceSelectionActions";

it("uses identical bulk controls for partial, full and empty selections", async () => {
  const toggle = vi.fn();
  const clear = vi.fn();
  const { rerender } = render(
    <ResourceSelectionActions
      allSelected={false}
      hasSelection
      onToggleAll={toggle}
      onClear={clear}
    />
  );
  await userEvent.click(screen.getByRole("button", { name: "全选" }));
  expect(toggle).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: "清空" }));
  expect(clear).toHaveBeenCalledOnce();
  rerender(
    <ResourceSelectionActions
      allSelected
      hasSelection
      onToggleAll={toggle}
      onClear={clear}
    />
  );
  expect(screen.getByRole("button", { name: "取消全选" })).toBeEnabled();
  rerender(
    <ResourceSelectionActions
      allSelected={false}
      hasSelection={false}
      empty
      onToggleAll={toggle}
      onClear={clear}
    />
  );
  expect(screen.getByRole("button", { name: "全选" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "清空" })).toBeDisabled();
});

beforeEach(async () => {
  await i18n.use(initReactI18next).init({
    lng: "zh",
    defaultNS: "common",
    keySeparator: false,
    resources: { zh: { common: zh } },
    interpolation: { escapeValue: false },
  });
});
