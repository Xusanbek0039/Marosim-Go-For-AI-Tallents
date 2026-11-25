// Run: npm test  (node --test, Node ≥ 22.18 strips the types)
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BUDGET_STATE,
  chatBlockFor,
  formatRange,
  formatSum,
  ITEM_CATEGORIES,
  parseMoney,
  previewLine,
  toDecimalString,
  validatePlanForm,
} from "./budget.ts";

describe("money", () => {
  it("parses exact amounts without floating point", () => {
    assert.equal(parseMoney("1 500 000,50"), BigInt(150000050));
    assert.equal(parseMoney("0.1"), BigInt(10));
    assert.equal(parseMoney("-5"), null);
    assert.equal(parseMoney("1e3"), null);
    assert.equal(parseMoney("12.345"), null);
    assert.equal(toDecimalString(BigInt(150000050)), "1500000.50");
  });

  it("formats sums and ranges in so'm", () => {
    assert.equal(formatSum("45000000.00"), "45 000 000 so'm");
    assert.equal(formatSum("1500.50"), "1 500,50 so'm");
    assert.equal(formatSum("-250000.00"), "−250 000 so'm");
    assert.equal(formatSum(null), "—");
    assert.equal(formatRange("100.00", "100.00"), "100 so'm");
    assert.equal(formatRange("100.00", "200.00"), "100 so'm – 200 so'm");
  });
});

describe("live line preview (mirrors the server calculator)", () => {
  const base = { unitPrice: "150000", quantity: "1", perGuest: true, guests: 300, included: false, active: true };

  it("multiplies a per-person menu by the guest count", () => {
    assert.deepEqual(previewLine(base), { min: "45000000.00", max: "45000000.00" });
  });

  it("keeps a range as min and max", () => {
    assert.deepEqual(previewLine({ ...base, perGuest: false, quantity: "2", unitPriceMax: "200000" }), {
      min: "300000.00",
      max: "400000.00",
    });
  });

  it("rounds half-up to the tiyin and never drifts", () => {
    assert.deepEqual(previewLine({ ...base, perGuest: false, unitPrice: "0.10", quantity: "3" }), { min: "0.30", max: "0.30" });
    assert.deepEqual(previewLine({ ...base, perGuest: false, unitPrice: "0.05", quantity: "0.5" }), { min: "0.03", max: "0.03" });
  });

  it("counts package / inactive lines as zero and rejects illogical input", () => {
    assert.deepEqual(previewLine({ ...base, included: true }), { min: "0.00", max: "0.00" });
    assert.deepEqual(previewLine({ ...base, active: false }), { min: "0.00", max: "0.00" });
    assert.equal(previewLine({ ...base, unitPrice: "-1" }), null);
    assert.equal(previewLine({ ...base, perGuest: false, unitPriceMax: "100" }), null);
    assert.equal(previewLine({ ...base, guests: null }), null);
    assert.equal(previewLine({ ...base, perGuest: false, quantity: "0" }), null);
  });
});

describe("plan form validation", () => {
  const ok = { title: "To'y", guest_count: "300", total_budget: "150000000", event_date: "2027-05-01", reserve_percent: "7" };

  it("accepts a valid plan", () => {
    assert.deepEqual(validatePlanForm(ok, "2026-11-25"), {});
  });

  it("rejects empty title, bad numbers and past dates", () => {
    const errors = validatePlanForm(
      { title: " ", guest_count: "0", total_budget: "-1", event_date: "2026-01-01", reserve_percent: "40" },
      "2026-11-25",
    );
    assert.deepEqual(Object.keys(errors).sort(), ["event_date", "guest_count", "reserve_percent", "title", "total_budget"]);
  });
});

describe("chat states", () => {
  it("maps every server code to a distinct UI state", () => {
    assert.equal(chatBlockFor(null).kind, "ready");
    assert.equal(chatBlockFor("ai_disabled").kind, "disabled");
    assert.equal(chatBlockFor("ai_maintenance", "14:00 gacha").kind, "maintenance");
    assert.equal(chatBlockFor("ai_not_configured").kind, "unconfigured");
    assert.equal(chatBlockFor("ai_daily_limit").kind, "limit");
    assert.equal(chatBlockFor("network_error").kind, "offline");
    const provider = chatBlockFor("provider_timeout");
    assert.equal(provider.kind, "provider");
    assert.ok("retry" in provider && provider.retry);
  });

  it("has a label for every budget state and no contingency item category", () => {
    assert.deepEqual(Object.keys(BUDGET_STATE).sort(), ["AT_RISK", "NO_BUDGET", "NO_ITEMS", "OVER", "WITHIN"]);
    assert.ok(!ITEM_CATEGORIES.includes("CONTINGENCY" as never));
  });
});
