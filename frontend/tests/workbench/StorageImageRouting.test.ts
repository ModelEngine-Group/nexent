// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { fetchWithAuth } from "@/lib/auth";
import {
  convertImageUrlToApiUrl,
  fetchImageBlob,
} from "@/services/storageService";

vi.mock("@/lib/auth", () => ({ fetchWithAuth: vi.fn() }));
vi.mock("@/lib/logger", () => ({ default: { info: vi.fn() } }));

beforeEach(() => vi.mocked(fetchWithAuth).mockReset());

it.each(["localhost:30081", "127.0.0.1:30081", "aidp.example"])(
  "fetches protected AIDP images through the backend proxy (%s)",
  async (host) => {
    const source = `http://${host}/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb/ViewImage/image.png`;
    const image = new Blob(["sample"], { type: "image/png" });
    vi.mocked(fetchWithAuth).mockResolvedValue({
      ok: true,
      headers: new Headers({ "Content-Type": "image/png" }),
      blob: async () => image,
    } as Response);

    const result = await fetchImageBlob(source);

    const request = new URL(
      String(vi.mocked(fetchWithAuth).mock.calls[0][0]),
      "http://localhost:3000"
    );
    expect(request.pathname).toBe("/api/image");
    expect(request.searchParams.get("url")).toBe(source);
    expect(result).toBe(image);
  }
);

it("preserves the existing local attachment image route", () => {
  const source = "http://localhost:3000/nexent/attachments/local.png";
  expect(convertImageUrlToApiUrl(source)).toBe(source);
});

it("preserves independent AIDP image routing", () => {
  const source = "/api/ind-aidp/images/agent/file.png";
  expect(convertImageUrlToApiUrl(source)).toBe(source);
});
