import { describe, expect, it } from "vitest";

import { extractFilenameFromContentDisposition } from "@/services/agentConfigService";

describe("extractFilenameFromContentDisposition", () => {
  it("decodes RFC 5987 UTF-8 filenames", () => {
    const header =
      "attachment; filename*=UTF-8''%E6%99%BA%E8%83%BD%E4%BD%93%E5%AF%BC%E5%87%BA.zip";
    expect(extractFilenameFromContentDisposition(header)).toBe(
      "智能体导出.zip"
    );
  });

  it("falls back to quoted plain filenames", () => {
    const header = 'attachment; filename="agent_export.zip"';
    expect(extractFilenameFromContentDisposition(header)).toBe("agent_export.zip");
  });

  it("falls back to unquoted plain filenames", () => {
    const header = "attachment; filename=agent_export.zip";
    expect(extractFilenameFromContentDisposition(header)).toBe("agent_export.zip");
  });

  it("returns null when the header is missing", () => {
    expect(extractFilenameFromContentDisposition(null)).toBeNull();
  });

  it("ignores malformed filename* encodings and falls back to filename", () => {
    const header =
      'attachment; filename="fallback.zip"; filename*=UTF-8\'\'%E0%A4%A';
    expect(extractFilenameFromContentDisposition(header)).toBe("fallback.zip");
  });
});
