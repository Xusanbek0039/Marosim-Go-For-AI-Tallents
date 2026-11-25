// Run: npm test  (node --test, Node ≥ 22.18 strips the types)
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { criticalChanges, visibleAiTabs } from "./access.ts";

describe("AI planner panel menu", () => {
  it("shows a super admin every tab", () => {
    const tabs = visibleAiTabs({ role: "SUPER_ADMIN", permissions: ["ai.view", "ai.reports", "ai.conversations", "ai.disable"] });
    assert.deepEqual(tabs, ["dashboard", "usage", "reports", "conversations", "control", "settings", "prompts", "audit"]);
  });

  it("gives an admin only the tabs of the granted codes", () => {
    assert.deepEqual(visibleAiTabs({ role: "ADMIN", permissions: ["ai.reports"] }), ["reports"]);
    assert.deepEqual(visibleAiTabs({ role: "ADMIN", permissions: ["ai.view", "ai.disable"] }), ["dashboard", "usage", "control"]);
    assert.deepEqual(visibleAiTabs({ role: "ADMIN", permissions: [] }), []);
  });

  it("never shows super-admin tabs to an admin, even with every code", () => {
    const tabs = visibleAiTabs({ role: "ADMIN", permissions: ["ai.view", "ai.reports", "ai.conversations", "ai.disable"] });
    assert.ok(!tabs.includes("settings") && !tabs.includes("prompts") && !tabs.includes("audit"));
  });

  it("hides everything from non-panel roles", () => {
    assert.deepEqual(visibleAiTabs({ role: "USER", permissions: [] }), []);
    assert.deepEqual(visibleAiTabs(undefined), []);
  });
});

describe("critical config changes need confirmation", () => {
  it("detects only the critical fields that really changed", () => {
    const before = { enabled: true, model_name: "claude-opus-5-5", max_tokens: 4000, feature_flags: { chat: true } };
    assert.deepEqual(criticalChanges(before, { max_tokens: 3000 }), []);
    assert.deepEqual(criticalChanges(before, { enabled: true, max_tokens: 3000 }), []);
    assert.deepEqual(criticalChanges(before, { enabled: false, feature_flags: { chat: false } }), ["enabled", "feature_flags"]);
  });
});
