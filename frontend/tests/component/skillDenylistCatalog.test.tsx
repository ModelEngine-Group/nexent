// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { renderHook, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { createQueryWrapper } from "./resourceDrawerTestUtils";

const fetchSkills = vi.hoisted(() => vi.fn());
vi.mock("@/services/agentConfigService", () => ({ fetchSkills }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

test("uses the policy-aware mount catalog and retains blocked metadata separately from selectable skills", async () => {
  fetchSkills.mockResolvedValue({
    success: true,
    data: [
      { skill_id: 7, name: "retained", blocked_by_denylist: true },
      { skill_id: 8, name: "available", blocked_by_denylist: false },
    ],
  });
  const { result } = renderHook(() => useSkillList(), {
    wrapper: createQueryWrapper(),
  });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(fetchSkills).toHaveBeenCalledWith(undefined, "mount");
  expect(result.current.skills?.map((skill) => skill.skill_id)).toEqual([7, 8]);
  expect(result.current.availableSkills.map((skill) => skill.skill_id)).toEqual(
    [8]
  );
});
