// Run: npm test  (node --test, Node ≥ 22.18 strips the types)
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { pendingAlreadySaved } from "./pending.ts";

describe("chat pending slot", () => {
  it("hides the bubble once the server kept the failed message", () => {
    const history = [
      { role: "assistant", client_request_id: null },
      { role: "user", client_request_id: "k1" },
    ];
    assert.equal(pendingAlreadySaved(history, "k1"), true);
  });

  it("shows the bubble while the message is not in history yet", () => {
    assert.equal(pendingAlreadySaved([{ role: "user", client_request_id: "other" }], "k1"), false);
    assert.equal(pendingAlreadySaved([], "k1"), false);
  });
});
