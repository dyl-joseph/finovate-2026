import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const publicUrl = new URL("../public/", import.meta.url);

test("the ready screen is a single-action experience", async () => {
  const html = await readFile(new URL("index.html", publicUrl), "utf8");

  assert.match(html, /<button id="start"[^>]*>[\s\S]*?Start listening[\s\S]*?<\/button>/);
  assert.doesNotMatch(html, /class="steps"|3 easy steps|Analyze risk/i);
  assert.doesNotMatch(html, /id="live-assessment"/);
});

test("the interface contains no CSS gradients", async () => {
  const css = await readFile(new URL("styles.css", publicUrl), "utf8");

  assert.doesNotMatch(css, /gradient\s*\(/i);
});

test("live checks run every five seconds on one persistent conversation", async () => {
  const javascript = await readFile(new URL("app.js", publicUrl), "utf8");

  assert.match(javascript, /LIVE_ASSESSMENT_INTERVAL_MS\s*=\s*5_000/);
  assert.match(javascript, /liveConversationId\s*=\s*`\$\{assembler\.conversationId\}-live`/);
  assert.match(javascript, /conversation_id:\s*liveConversationId/);
});
