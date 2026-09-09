import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SkillPicker } from "@/features/workbench/components/SkillPicker";
import { fetchSkillsList, type SkillListItem } from "@/services/skillService";
import {
  fetchSkillRepositoryListings,
  installSkillFromRepository,
} from "@/services/skillRepositoryService";
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
const empty = vi.hoisted(() => []);
vi.mock("@/features/workbench/hooks/useResourceTags", () => ({
  useResourceTags: () => ({
    definitions: [],
    predicates: empty,
    visibleIds: null,
  }),
}));
vi.mock("@/services/skillService", () => ({ fetchSkillsList: vi.fn() }));
vi.mock("@/services/skillRepositoryService", () => ({
  fetchSkillRepositoryListings: vi.fn(),
  installSkillFromRepository: vi.fn(),
}));
const base = {
  skill_id: "1",
  name: "Default Skill",
  description: "Description",
  source: "local",
  config_schemas: [],
  config_values: {},
} as unknown as SkillListItem;
it.each([false, true])(
  "restores published defaults only on confirmation (empty=%s)",
  async (emptyDefaults) => {
    const confirm = vi.fn();
    const defaults = emptyDefaults
      ? []
      : [{ skill_id: 1, config_values: { region: "published" } }];
    const loadDefaults = vi.fn().mockResolvedValue(defaults);
    render(
      <SkillPicker
        open
        selected={[{ skill_id: 2, config_values: { region: "custom" } }]}
        onCancel={vi.fn()}
        onConfirm={confirm}
        loadDefaults={loadDefaults}
      />
    );
    await screen.findByRole("option", { name: /Default Skill/ });
    await userEvent.click(screen.getByRole("button", { name: "恢复默认" }));
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /New Skill/ })).toHaveAttribute(
        "aria-selected",
        "false"
      )
    );
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
    expect(confirm.mock.calls[0][0]).toEqual(defaults);
  }
);

it("keeps the current selection when loading defaults fails", async () => {
  const confirm = vi.fn();
  render(
    <SkillPicker
      open
      selected={[{ skill_id: 2, config_values: {} }]}
      onCancel={vi.fn()}
      onConfirm={confirm}
      loadDefaults={vi.fn().mockRejectedValue(new Error("Unavailable"))}
    />
  );
  await screen.findByRole("option", { name: /New Skill/ });
  await userEvent.click(screen.getByRole("button", { name: "恢复默认" }));
  await screen.findByText("Unavailable");
  expect(screen.getByRole("option", { name: /New Skill/ })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(confirm).not.toHaveBeenCalled();
});
it("editing navigates without selecting the skill", async () => {
  const confirm = vi.fn();
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={confirm} />
  );
  const card = (await screen.findByRole("option", { name: /Default Skill/ }))
    .parentElement!;
  await userEvent.click(within(card).getByRole("button", { name: "编辑" }));
  expect(push).toHaveBeenCalledWith("/skill-space?tab=mine&edit_skill_id=1");
  expect(screen.getByRole("option", { name: /Default Skill/ })).toHaveAttribute(
    "aria-selected",
    "false"
  );
  expect(confirm).not.toHaveBeenCalled();
});
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchSkillsList).mockResolvedValue([
    base,
    { ...base, skill_id: "2", name: "New Skill" },
  ]);
  vi.mocked(fetchSkillRepositoryListings).mockResolvedValue({
    items: [
      { skill_repository_id: 5, name: "Repository Skill", status: "shared" },
    ],
  } as Awaited<ReturnType<typeof fetchSkillRepositoryListings>>);
});
it("UT-FE-WB-022 a no-config selection remains pending until confirmation", async () => {
  const confirm = vi.fn();
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={confirm} />
  );
  await userEvent.click(
    await screen.findByRole("option", { name: /New Skill/ })
  );
  expect(confirm).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 2, config_values: {} },
  ]);
});
it("selects and deselects search results without losing hidden selections", async () => {
  const confirm = vi.fn();
  render(
    <SkillPicker
      open
      selected={[{ skill_id: 1, config_values: {} }]}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByRole("option", { name: /Default Skill/ });
  await userEvent.type(
    screen.getByPlaceholderText("搜索 Skill 名称或描述"),
    "New"
  );
  await userEvent.click(screen.getByRole("button", { name: /^全选$/ }));
  expect(confirm).not.toHaveBeenCalled();
  expect(screen.getByRole("option", { name: /New Skill/ })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await userEvent.click(screen.getByRole("button", { name: "取消全选" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "确认选择" })
  );
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 1, config_values: {} },
  ]);
});
it("bulk selection respects the twenty-skill limit", async () => {
  vi.mocked(fetchSkillsList).mockResolvedValue(
    Array.from({ length: 21 }, (_, index) => ({
      ...base,
      skill_id: String(index + 1),
      name: `Skill ${index + 1}`,
    }))
  );
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={vi.fn()} />
  );
  await screen.findByRole("option", { name: /Skill 21/ });
  await userEvent.click(screen.getByRole("button", { name: /^全选$/ }));
  expect(
    screen
      .getAllByRole("option")
      .every((option) => option.getAttribute("aria-selected") === "false")
  ).toBe(true);
  expect(
    await screen.findByText("最多选择 20 个 Skills，请缩小搜索范围后重试")
  ).toBeInTheDocument();
});
it("UT-FE-WB-023 required configuration blocks confirmation until complete", async () => {
  vi.mocked(fetchSkillsList).mockResolvedValue([
    {
      ...base,
      config_schemas: [{ name: "region", type: "string", required: true }],
    },
  ]);
  const confirm = vi.fn();
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={confirm} />
  );
  await userEvent.click(
    await screen.findByRole("option", { name: /Default Skill/ })
  );
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.type(screen.getByLabelText("Default Skill region"), "CN");
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 1, config_values: { region: "CN" } },
  ]);
});
it("UT-FE-WB-035 published instance values are displayed without fetching draft instances", async () => {
  vi.mocked(fetchSkillsList).mockResolvedValue([
    {
      ...base,
      config_schemas: [{ name: "region", type: "string" }],
      config_values: { region: "draft-default" },
    },
  ]);
  render(
    <SkillPicker
      open
      selected={[{ skill_id: 1, config_values: { region: "published-v3" } }]}
      onCancel={vi.fn()}
      onConfirm={vi.fn()}
    />
  );
  await screen.findByRole("option", { name: /Default Skill/ });
  await userEvent.click(screen.getByRole("option", { name: /Default Skill/ }));
  expect(screen.getByRole("option", { name: /Default Skill/ })).toHaveAttribute(
    "aria-selected",
    "false"
  );
  await userEvent.click(screen.getByRole("option", { name: /Default Skill/ }));
  expect(await screen.findByLabelText("Default Skill region")).toHaveValue(
    "published-v3"
  );
  await userEvent.clear(screen.getByLabelText("Default Skill region"));
  await userEvent.type(
    screen.getByLabelText("Default Skill region"),
    "discard-me"
  );
  await userEvent.click(
    within(
      screen
        .getByLabelText("Default Skill region")
        .closest('[role="dialog"]') as HTMLElement
    ).getByRole("button", { name: /取\s*消/ })
  );
  await userEvent.click(screen.getByRole("option", { name: /Default Skill/ }));
  expect(screen.getByLabelText("Default Skill region")).toHaveValue(
    "published-v3"
  );
});
it("UT-FE-WB-036 confirming a new set excludes cancelled defaults and supports empty selection", async () => {
  const confirm = vi.fn();
  render(
    <SkillPicker
      open
      selected={[{ skill_id: 1, config_values: {} }]}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await userEvent.click(
    await screen.findByRole("option", { name: /Default Skill/ })
  );
  await userEvent.click(screen.getByRole("option", { name: /New Skill/ }));
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 2, config_values: {} },
  ]);
  await userEvent.click(screen.getByRole("option", { name: /New Skill/ }));
  await userEvent.click(screen.getByText("确认选择"));
  expect(confirm.mock.calls[1][0]).toEqual([]);
});
it("UT-FE-WB-024 install selects the returned Skill ID even when renamed", async () => {
  vi.mocked(installSkillFromRepository).mockResolvedValue({
    skill_id: 99,
  } as Awaited<ReturnType<typeof installSkillFromRepository>>);
  const confirm = vi.fn();
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={confirm} />
  );
  await screen.findByRole("option", { name: /Default Skill/ });
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  vi.mocked(fetchSkillsList).mockResolvedValue([
    base,
    { ...base, skill_id: "99", name: "Renamed Skill" },
  ]);
  await userEvent.click(
    await screen.findByRole("option", { name: /Repository Skill/ })
  );
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: /Renamed Skill/ })
    ).toHaveAttribute("aria-selected", "true")
  );
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 99, config_values: {} },
  ]);
});

it("UT-FE-WB-038 ignores a completed install after leaving the repository tab", async () => {
  let resolveInstall!: (
    value: Awaited<ReturnType<typeof installSkillFromRepository>>
  ) => void;
  vi.mocked(installSkillFromRepository).mockReturnValue(
    new Promise((resolve) => {
      resolveInstall = resolve;
    })
  );
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={vi.fn()} />
  );
  await screen.findByRole("option", { name: /Default Skill/ });
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  await userEvent.click(
    await screen.findByRole("option", { name: /Repository Skill/ })
  );
  await userEvent.click(screen.getByRole("tab", { name: "我的" }));
  resolveInstall({ skill_id: 99 } as Awaited<
    ReturnType<typeof installSkillFromRepository>
  >);
  await waitFor(() =>
    expect(installSkillFromRepository).toHaveBeenCalledOnce()
  );
  expect(fetchSkillsList).toHaveBeenCalledOnce();
  expect(
    screen.queryByRole("option", { name: /Renamed Skill/ })
  ).not.toBeInTheDocument();
});

it("UT-FE-WB-023 renders boolean and enum controls with typed values", async () => {
  vi.mocked(fetchSkillsList).mockResolvedValue([
    {
      ...base,
      config_schemas: [
        { name: "enabled", type: "boolean", required: true },
        {
          name: "region",
          type: "string",
          required: true,
          enum: ["CN", "US"],
        },
      ],
      config_values: { enabled: false, region: "CN" },
    },
  ]);
  const confirm = vi.fn();
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={confirm} />
  );
  await userEvent.click(
    await screen.findByRole("option", { name: /Default Skill/ })
  );
  await userEvent.click(screen.getByLabelText("Default Skill enabled"));
  expect(
    screen.getByRole("combobox", { name: "Default Skill region" })
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 1, config_values: { enabled: true } },
  ]);
});
