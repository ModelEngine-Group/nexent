import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isSingleSimpleEmoji } from "./agentRepositoryIcon";

describe("isSingleSimpleEmoji", () => {
  it("accepts a single pictographic emoji", () => {
    assert.equal(isSingleSimpleEmoji("🤖"), true);
  });

  it("accepts emoji with variation selector", () => {
    assert.equal(isSingleSimpleEmoji("✍️"), true);
  });

  it("accepts emoji with skin tone modifier", () => {
    assert.equal(isSingleSimpleEmoji("👍🏻"), true);
  });

  it("rejects empty string", () => {
    assert.equal(isSingleSimpleEmoji(""), false);
    assert.equal(isSingleSimpleEmoji("   "), false);
  });

  it("rejects plain text", () => {
    assert.equal(isSingleSimpleEmoji("abc"), false);
  });

  it("rejects text mixed with emoji", () => {
    assert.equal(isSingleSimpleEmoji("a🤖"), false);
  });

  it("rejects multiple emojis", () => {
    assert.equal(isSingleSimpleEmoji("🤖🔍"), false);
  });

  it("rejects ZWJ compound emoji", () => {
    assert.equal(isSingleSimpleEmoji("👨‍👩‍👧"), false);
  });

  it("rejects flag emoji", () => {
    assert.equal(isSingleSimpleEmoji("🇨🇳"), false);
  });
});
