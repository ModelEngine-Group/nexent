import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getSessionRenewalAction } from "./sessionRenewal.ts";

const baseDecision = {
  isVisible: true,
  remainingLifetimeMs: 60 * 60 * 1000,
  localRefreshThresholdMs: 30 * 60 * 1000,
  currentTimeMs: 10 * 60 * 1000,
  lastCasRenewAttemptAtMs: 5 * 60 * 1000,
  casRenewIntervalMs: 5 * 60 * 1000,
  casRenewSafetyWindowMs: 5 * 60 * 1000,
  isCasRenewing: false,
  hasCasRenewAttempted: false,
};

describe("session renewal decisions", () => {
  it("refreshes a local session only inside the refresh window", () => {
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "local",
        remainingLifetimeMs: 20 * 60 * 1000,
      }),
      "refresh-local"
    );
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "local",
      }),
      "none"
    );
  });

  it("renews a CAS session after the active renewal interval", () => {
    assert.equal(
      getSessionRenewalAction({ ...baseDecision, authProvider: "cas" }),
      "renew-cas"
    );
  });

  it("throttles CAS renewal before the interval elapses", () => {
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "cas",
        lastCasRenewAttemptAtMs: 9 * 60 * 1000,
      }),
      "none"
    );
  });

  it("renews a CAS session inside the expiry safety window", () => {
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "cas",
        lastCasRenewAttemptAtMs: 9 * 60 * 1000,
        remainingLifetimeMs: 4 * 60 * 1000,
      }),
      "renew-cas"
    );
  });

  it("does not repeatedly bypass throttling inside the safety window", () => {
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "cas",
        lastCasRenewAttemptAtMs: 9 * 60 * 1000,
        remainingLifetimeMs: 4 * 60 * 1000,
        hasCasRenewAttempted: true,
      }),
      "none"
    );
  });

  it("does not renew while hidden, expired, or already renewing", () => {
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "cas",
        isVisible: false,
      }),
      "none"
    );
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "cas",
        remainingLifetimeMs: 0,
      }),
      "none"
    );
    assert.equal(
      getSessionRenewalAction({
        ...baseDecision,
        authProvider: "cas",
        isCasRenewing: true,
      }),
      "none"
    );
  });
});
