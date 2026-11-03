// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { Session } from "@/types/auth";

/** Compatibility surface; ordinary JWT credentials expire and require login. */
export const sessionService = {
  refreshToken: async (): Promise<Session | null> => null,
};
