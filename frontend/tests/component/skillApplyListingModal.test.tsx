// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import { MineApplyListingModal } from "@/components/repository/skill/components/MineApplyListingModal";
import type { MyEditableSkillItem } from "@/types/skillRepository";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) =>
      options?.name ? `${key}: ${options.name}` : key,
  }),
}));
const skill: MyEditableSkillItem = {
  skill_id: 7,
  name: "Canvas-Design",
  tags: ["design"],
  repository_info: [],
};

function show(
  onConfirm = vi.fn().mockResolvedValue(undefined),
  loading = false
) {
  const onClose = vi.fn();
  const result = render(
    <App>
      <MineApplyListingModal
        open
        skill={skill}
        loading={loading}
        onClose={onClose}
        onConfirm={onConfirm}
      />
    </App>
  );
  return { ...result, onConfirm, onClose };
}

test("shows the skill name and accepts an optional empty note", async () => {
  const { onConfirm, onClose } = show();
  expect(
    screen.getByText("skillRepository.mine.applyTitle: Canvas-Design")
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(onConfirm).toHaveBeenCalledWith({
    icon: "skill",
    tags: ["design"],
    content: undefined,
  });
});

test("permits 1000 characters and prevents a payload above that limit", async () => {
  const { onConfirm } = show();
  const input = screen.getByLabelText("repository.mine.applyModal.content");
  fireEvent.change(input, { target: { value: "x".repeat(1001) } });
  expect(screen.getByRole("button", { name: "common.confirm" })).toBeDisabled();
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "x".repeat(1000) } });
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() =>
    expect(onConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ content: "x".repeat(1000) })
    )
  );
});

test("retains the note after failure and closes only after a successful retry", async () => {
  const submit = vi
    .fn()
    .mockRejectedValueOnce(new Error("Failed"))
    .mockResolvedValueOnce(undefined);
  const { onClose } = show(submit);
  fireEvent.change(
    screen.getByLabelText("repository.mine.applyModal.content"),
    { target: { value: "  Listing note  " } }
  );
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  expect(
    await screen.findByText("repository.mine.applyError")
  ).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
  expect(
    screen.getByLabelText("repository.mine.applyModal.content")
  ).toHaveValue("  Listing note  ");
  fireEvent.click(screen.getByRole("button", { name: "common.confirm" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(submit).toHaveBeenLastCalledWith(
    expect.objectContaining({ content: "Listing note" })
  );
});

test("blocks duplicate submission and dismissal while the request is pending", async () => {
  let resolve!: () => void;
  const submit = vi.fn(
    () =>
      new Promise<void>((done) => {
        resolve = done;
      })
  );
  const { onClose } = show(submit);
  const confirm = screen.getByRole("button", { name: "common.confirm" });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  expect(submit).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "common.cancel" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "common.close" }));
  expect(onClose).not.toHaveBeenCalled();
  resolve();
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
});

test("renders no listing dialog when the selected skill is missing", () => {
  render(
    <App>
      <MineApplyListingModal
        open
        skill={null}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />
    </App>
  );
  expect(
    screen.queryByRole("button", { name: "common.confirm" })
  ).not.toBeInTheDocument();
});
