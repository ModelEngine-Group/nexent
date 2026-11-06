// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { readFileSync } from "node:fs";
import path from "node:path";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { describe, expect, it, vi } from "vitest";

import { buildModelSlots } from "../../app/[locale]/models/components/model/ModelSlotSelect";
import { ParamDialog } from "@/components/resource-picker/ParamDialog";
import { ModelParamsModal } from "@/components/resource-picker/ModelParamsModal";
import { SearchRow } from "@/components/resource-picker/ResourceDrawer";

const catalogs = Object.fromEntries(
  ["zh", "en"].map((language) => [
    language,
    JSON.parse(
      readFileSync(
        path.resolve(`public/locales/${language}/common.json`),
        "utf8"
      )
    ) as Record<string, string>,
  ])
);

async function locale(language: string) {
  const instance = createInstance();
  await instance.use(initReactI18next).init({
    lng: language,
    fallbackLng: "en",
    defaultNS: "common",
    keySeparator: false,
    resources: Object.fromEntries(
      Object.entries(catalogs).map(([key, common]) => [key, { common }])
    ),
    interpolation: { escapeValue: false },
  });
  return instance;
}

describe("resource picker localization", () => {
  it.each([
    ["zh", "hover", false],
    ["en", "hover", true],
    ["zh", "focus", true],
    ["en", "focus", false],
  ] as const)(
    "shows sampling help in %s on %s (readonly=%s) without changing the draft",
    async (language, trigger, disabled) => {
      const instance = await locale(language);
      const onChange = vi.fn();
      const onClose = vi.fn();
      const onConfirm = vi.fn();
      render(
        <I18nextProvider i18n={instance}>
          <ModelParamsModal
            open
            modelOptions={[{ value: 1, label: "Model" }]}
            selectedModelId={1}
            onSelectModel={vi.fn()}
            value={{ temperature: 0, top_p: 1 }}
            onChange={onChange}
            onClose={onClose}
            onConfirm={onConfirm}
            disabled={disabled}
          />
        </I18nextProvider>
      );
      for (const field of ["temperature", "topP"]) {
        const label = screen.getByText(instance.t(`modelParams.${field}`));
        const icon = within(label.closest("[data-config-label]")!).getByRole(
          "img",
          { name: "question-circle" }
        );
        if (trigger === "hover") await userEvent.hover(icon);
        else fireEvent.focus(icon);
        expect(await screen.findByRole("tooltip")).toHaveTextContent(
          instance.t(`modelParams.${field}Info`)
        );
        if (trigger === "hover") await userEvent.unhover(icon);
        else fireEvent.blur(icon);
        await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
      }
      expect(onChange).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      expect(onConfirm).not.toHaveBeenCalled();
    }
  );

  it.each(["zh", "en"])(
    "resolves all ten model hints in %s",
    async (language) => {
      const instance = await locale(language);
      const slots = buildModelSlots((key, options) =>
        String(instance.t(key, options))
      );
      expect(slots).toHaveLength(10);
      for (const slot of slots) {
        expect(slot.hint.length).toBeGreaterThan(20);
        if (language === "en") expect(slot.hint).not.toMatch(/[\u4e00-\u9fff]/);
        const key = `modelConfig.slot.hint.${slot.option === "main" ? "llm" : slot.option === "multi_embedding" ? "multiEmbedding" : slot.option}`;
        expect(catalogs[language][key]).toBe(slot.hint);
      }
    }
  );
  it.each(["zh", "en"])(
    "resolves affected copy in %s without fallback",
    async (language) => {
      const instance = await locale(language);
      const files = [
        "components/resource-picker/ModelParamsModal.tsx",
        "components/resource-picker/KnowledgeDrawer.tsx",
        "components/resource-picker/ModelDrawer.tsx",
        "components/resource-picker/ResourceDrawer.tsx",
        "features/workbench/components/KnowledgePopoverContent.tsx",
        "features/workbench/components/SkillPopoverContent.tsx",
        "features/workbench/WorkbenchPage.tsx",
        "features/workbench/components/AgentPicker.tsx",
        "features/workbench/components/SkillPicker.tsx",
        "features/workbench/components/ResourceSelectionActions.tsx",
        "app/[locale]/newchat/assistant-ui/conversation-knowledge-scope-modal.tsx",
        "components/resource-picker/SkillConfigModal.tsx",
        "components/resource-picker/ToolConfigModal.tsx",
        "app/[locale]/newchat/assistant-ui/composer.tsx",
      ];
      const keys = new Set<string>();
      for (const file of files) {
        const source = readFileSync(path.resolve(file), "utf8");
        for (const match of source.matchAll(/\bt\(\s*"([^"]+)"/g)) {
          if (
            /^(ui\.localization\.|chat\.knowledgeScope\.retrievalSettings$|modelParams\.|resourcePicker\.|workbench\.(skills|resources|controls)\.|chat\.composer\.(loading|emptySkills|emptyKnowledge)$|knowledgeBase\.document$)/.test(
              match[1]
            )
          ) {
            keys.add(match[1]);
          }
        }
      }
      expect(keys.size).toBeGreaterThan(20);
      for (const key of keys) {
        expect(catalogs[language][key], key).toBeTruthy();
        const text = instance.t(key, {
          count: 2,
          date: "2026-10-12",
          name: "Fixture",
        });
        expect(text, key).not.toBe(key);
        expect(text, key).not.toContain("{{");
        if (language === "en") expect(text, key).not.toMatch(/[\u4e00-\u9fff]/);
      }
    }
  );

  it("updates dialog actions on locale change and preserves callbacks", async () => {
    const instance = await locale("zh");
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    render(
      <I18nextProvider i18n={instance}>
        <ParamDialog
          open
          title="Parameters"
          onClose={onClose}
          onConfirm={onConfirm}
        >
          Content
        </ParamDialog>
      </I18nextProvider>
    );
    expect(screen.getByRole("button", { name: "确定" })).toBeInTheDocument();
    await act(() => instance.changeLanguage("en"));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("button", { name: "确定" })
    ).not.toBeInTheDocument();
  });

  it("retains caller-supplied dialog action labels", async () => {
    const instance = await locale("en");
    render(
      <I18nextProvider i18n={instance}>
        <ParamDialog
          open
          title="Parameters"
          onClose={vi.fn()}
          onConfirm={vi.fn()}
          confirmText="Save changes"
          cancelText="Back"
        >
          Content
        </ParamDialog>
      </I18nextProvider>
    );
    await act(() => instance.changeLanguage("zh"));
    expect(
      screen.getByRole("button", { name: "Save changes" })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeInTheDocument();
  });

  it("updates the drawer tag placeholder without changing search input", async () => {
    const instance = await locale("zh");
    const onSearch = vi.fn();
    render(
      <I18nextProvider i18n={instance}>
        <SearchRow
          placeholder="Search resources"
          tagOptions={[]}
          onSearch={onSearch}
        />
      </I18nextProvider>
    );
    fireEvent.change(screen.getByPlaceholderText("Search resources"), {
      target: { value: "report" },
    });
    expect(onSearch).toHaveBeenLastCalledWith("report");
    expect(screen.getByText("标签")).toBeInTheDocument();
    await act(() => instance.changeLanguage("en"));
    expect(screen.getByText("Tags")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search resources")).toHaveValue(
      "report"
    );
  });
});
