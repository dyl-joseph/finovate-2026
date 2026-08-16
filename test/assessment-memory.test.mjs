import test from "node:test";
import assert from "node:assert/strict";
import { buildMemoryHighlights } from "../public/assessment-memory.mjs";

test("builds a repeat-speaker highlight from backend memory findings", () => {
  const highlights = buildMemoryHighlights([
    {
      kind: "repeat_flagged_speaker",
      description: "A similar speaker profile appeared in 2 previously flagged financial interaction(s).",
      match_confidence: 0.93,
      attributes: { prior_institutions: ["chase", "paypal"] },
    },
  ]);

  assert.deepEqual(highlights, [
    {
      kind: "repeat_flagged_speaker",
      title: "Similar speaker pattern detected",
      detail: "A similar speaker profile appeared in 2 previously flagged financial interaction(s).",
      meta: "Match confidence 93% · Previously claimed: Chase, PayPal",
    },
  ]);
});

test("builds an identity-switch highlight without claiming definitive identity", () => {
  const highlights = buildMemoryHighlights([
    {
      kind: "identity_switch",
      description: "The speaker previously claimed a different institutional identity.",
      match_confidence: 0.84,
      attributes: {
        current_institutions: ["paypal"],
        prior_institutions: ["chase"],
      },
    },
  ]);

  assert.deepEqual(highlights, [
    {
      kind: "identity_switch",
      title: "Institution identity changed across interactions",
      detail: "The speaker previously claimed a different institutional identity.",
      meta: "Match confidence 84% · Previously: Chase · Now: PayPal",
    },
  ]);
});

test("ignores unknown memory finding kinds", () => {
  assert.deepEqual(buildMemoryHighlights([{ kind: "unknown" }]), []);
});
