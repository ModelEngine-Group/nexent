// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
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
  "opens without restore-default actions and preserves committed mounts (empty=%s)",
  async (emptySelection) => {
    const confirm = vi.fn();
    const selected = emptySelection
      ? []
      : [{ skill_id: 2, config_values: { region: "custom" } }];
    render(
      <SkillPicker
        open
        selected={selected}
        onCancel={vi.fn()}
        onConfirm={confirm}
      />
    );
    await screen.findByRole("option", { name: "Default Skill" });
    expect(
      screen.queryByRole("button", { name: "恢复默认" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "New Skill" })).toHaveAttribute(
      "aria-selected",
      emptySelection ? "false" : "true"
    );
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(confirm.mock.calls[0][0]).toEqual(selected);
  }
);
it("shared Close discards the pending skill draft without applying defaults or saving", async () => {
  const confirm = vi.fn(),
    cancel = vi.fn();
  render(
    <SkillPicker
      open
      selected={[{ skill_id: 2, config_values: {} }]}
      onCancel={cancel}
      onConfirm={confirm}
    />
  );
  await userEvent.click(
    await screen.findByRole("option", { name: "Default Skill" })
  );
  expect(
    screen.queryByRole("button", { name: "恢复默认" })
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("关闭", { selector: "button" }));
  expect(cancel).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
});
it("shows text-only Skill rows in both tabs without an edit route", async () => {
  const confirm = vi.fn();
  vi.mocked(fetchSkillsList).mockResolvedValue([
    { ...base, description: "Skill details", tags: ["Finance"] },
  ]);
  vi.mocked(fetchSkillRepositoryListings).mockResolvedValue({
    items: [
      {
        skill_repository_id: 5,
        name: "Repository Skill",
        description: "Repository details",
        tags: ["Shared"],
        status: "shared",
      },
    ],
  } as Awaited<ReturnType<typeof fetchSkillRepositoryListings>>);
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={confirm} />
  );
  expect(
    screen.queryByRole("button", { name: "管理标签" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "官方" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "自定义" })
  ).not.toBeInTheDocument();
  expect(
    document.querySelector('[data-picker-part="selection"]')
  ).not.toBeNull();
  const row = await screen.findByRole("option", { name: "Default Skill" });
  expect(row).toHaveTextContent("Skill details");
  expect(row).toHaveTextContent("Finance");
  expect(row.querySelector("svg")).toBeNull();
  expect(
    screen.queryByRole("button", { name: "编辑" })
  ).not.toBeInTheDocument();
  await userEvent.click(row);
  expect(row).toHaveAttribute("aria-selected", "true");
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  const repositoryRow = await screen.findByRole("option", {
    name: "Repository Skill",
  });
  expect(repositoryRow).toHaveTextContent("Repository details");
  expect(repositoryRow).toHaveTextContent("Shared");
  expect(repositoryRow.querySelector("svg")).toBeNull();
  expect(screen.getByRole("button", { name: "安装并选择" })).toBeEnabled();
  expect(push).not.toHaveBeenCalled();
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
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
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
  await userEvent.click(screen.getByRole("checkbox", { name: "全选" }));
  expect(confirm).not.toHaveBeenCalled();
  expect(screen.getByRole("option", { name: /New Skill/ })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await userEvent.click(screen.getByRole("checkbox", { name: "全选" }));
  await userEvent.click(await screen.findByRole("button", { name: "确认" }));
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
  await screen.findByRole("option", { name: /^Skill 1$/ });
  expect(screen.getAllByRole("option")).toHaveLength(10);
  await userEvent.click(screen.getByRole("checkbox", { name: "全选" }));
  for (const page of ["2"]) {
    await userEvent.click(screen.getByRole("button", { name: page }));
    await userEvent.click(screen.getByRole("checkbox", { name: "全选" }));
  }
  await userEvent.click(screen.getByRole("button", { name: "3" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "全选" }));
  expect(
    screen
      .getAllByRole("option")
      .every((option) => option.getAttribute("aria-selected") === "false")
  ).toBe(true);
  expect(
    await screen.findByText("最多选择 20 个 Skills，请缩小搜索范围后重试")
  ).toBeInTheDocument();
});
it("paginates ten skills and preserves selections across pages", async () => {
  vi.mocked(fetchSkillsList).mockResolvedValue(
    Array.from({ length: 11 }, (_, index) => ({
      ...base,
      skill_id: String(index + 1),
      name: `Paged Skill ${index + 1}`,
    }))
  );
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={vi.fn()} />
  );
  await screen.findByRole("option", { name: /^Paged Skill 1$/ });
  expect(screen.getAllByRole("option")).toHaveLength(10);
  await userEvent.click(
    screen.getByRole("option", { name: /^Paged Skill 1$/ })
  );
  await userEvent.click(screen.getByRole("button", { name: "2" }));
  expect(screen.getAllByRole("option")).toHaveLength(1);
  expect(
    screen.getByRole("option", { name: /^Paged Skill 11$/ })
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "1" }));
  expect(
    screen.getByRole("option", { name: /^Paged Skill 1$/ })
  ).toHaveAttribute("aria-selected", "true");
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
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
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
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 2, config_values: {} },
  ]);
  await userEvent.click(screen.getByRole("option", { name: /New Skill/ }));
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
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
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
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
  const fetchCount = vi.mocked(fetchSkillsList).mock.calls.length;
  resolveInstall({ skill_id: 99 } as Awaited<
    ReturnType<typeof installSkillFromRepository>
  >);
  await waitFor(() =>
    expect(installSkillFromRepository).toHaveBeenCalledOnce()
  );
  expect(fetchSkillsList).toHaveBeenCalledTimes(fetchCount);
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
  await userEvent.click(screen.getByRole("button", { name: "确认" }));
  expect(confirm.mock.calls[0][0]).toEqual([
    { skill_id: 1, config_values: { enabled: true } },
  ]);
});

it("overlapping skill repository requests keep confirmation blocked until the current result settles", async () => {
  type Result = Awaited<ReturnType<typeof fetchSkillRepositoryListings>>;
  let finishOld!: (result: Result) => void;
  let finishCurrent!: (result: Result) => void;
  vi.mocked(fetchSkillRepositoryListings)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve;
        })
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishCurrent = resolve;
        })
    );
  render(
    <SkillPicker open selected={[]} onCancel={vi.fn()} onConfirm={vi.fn()} />
  );
  await screen.findByRole("option", { name: /Default Skill/ });
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  const confirm = screen.getByRole("button", { name: "确认" });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByPlaceholderText("搜索 Skill 名称或描述"), {
    target: { value: "Latest" },
  });
  await waitFor(() =>
    expect(fetchSkillRepositoryListings).toHaveBeenCalledTimes(2)
  );
  await act(async () => {
    finishOld({
      items: [{ skill_repository_id: 40, name: "Old result" }],
      pagination: { total: 1 },
    } as Result);
  });
  expect(confirm).toBeDisabled();
  expect(
    screen.queryByRole("option", { name: /Old result/ })
  ).not.toBeInTheDocument();
  await act(async () => {
    finishCurrent({
      items: [{ skill_repository_id: 41, name: "Latest result" }],
      pagination: { total: 1 },
    } as Result);
  });
  await screen.findByRole("option", { name: /Latest result/ });
  expect(confirm).toBeEnabled();
});

it("shared refresh retries a failed catalog without losing saved mounts", async () => {
  vi.mocked(fetchSkillsList)
    .mockRejectedValueOnce(new Error("catalog unavailable"))
    .mockResolvedValue([base]);
  const confirm = vi.fn();
  render(
    <SkillPicker
      open
      selected={[{ skill_id: 1, config_values: { region: "saved" } }]}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByText("catalog unavailable");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "确认" })).toBeDisabled()
  );
  await userEvent.click(screen.getByRole("button", { name: "刷新" }));
  expect(
    await screen.findByRole("option", { name: "Default Skill" })
  ).toHaveAttribute("aria-selected", "true");
  expect(fetchSkillsList).toHaveBeenCalledTimes(2);
  expect(confirm).not.toHaveBeenCalled();
});

it("repository page_size follows the shared 10/20/50 selector", async () => {
  render(
    <SkillPicker open selected={[]} onConfirm={vi.fn()} onCancel={vi.fn()} />
  );
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  await waitFor(() =>
    expect(fetchSkillRepositoryListings).toHaveBeenLastCalledWith(
      expect.objectContaining({ page_size: 10 })
    )
  );
  for (const size of [20, 50]) {
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByText(`${size} 条/页`, { exact: true }));
    await waitFor(() =>
      expect(fetchSkillRepositoryListings).toHaveBeenLastCalledWith(
        expect.objectContaining({ page_size: size })
      )
    );
  }
});
