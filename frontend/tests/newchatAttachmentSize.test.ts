import assert from "node:assert/strict";
import test from "node:test";

test("newchat accepts files up to 10 MB and rejects larger files", async () => {
  const moduleUrl = new URL(
    "../app/[locale]/newchat/utils/attachment-size.ts",
    import.meta.url
  );
  const { isNewChatFileTooLarge } = await import(moduleUrl.href);
  const tenMegabytes = 10 * 1024 * 1024;

  assert.equal(isNewChatFileTooLarge(tenMegabytes - 1), false);
  assert.equal(isNewChatFileTooLarge(tenMegabytes), false);
  assert.equal(isNewChatFileTooLarge(tenMegabytes + 1), true);
});
