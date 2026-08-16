import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import test from "node:test";

import {
  buildKeytermQuery,
  collectKeyterms,
  loadKeytermConfig,
} from "../src/deepgram-keyterms.mjs";

const execFileAsync = promisify(execFile);

test("the complete vocabulary is unique and remains within Deepgram's limit", async () => {
  const config = await loadKeytermConfig();
  const keyterms = collectKeyterms(config);

  assert.ok(keyterms.length > 0);
  assert.ok(keyterms.length <= config.max_keyterms);
  assert.equal(new Set(keyterms).size, keyterms.length);
});

test("the default vocabulary preserves high-value financial and scam terms", async () => {
  const keyterms = collectKeyterms(await loadKeytermConfig());

  for (const expectedTerm of [
    "Chase",
    "PayPal",
    "Zelle",
    "verification code",
    "wire transfer",
    "do not tell anyone",
  ]) {
    assert.ok(keyterms.includes(expectedTerm), `missing ${expectedTerm}`);
  }
});

test("query output repeats keyterm and URL-encodes multi-word values", () => {
  const query = buildKeytermQuery(["Chase", "fraud department", "AT&T"]);
  const params = new URLSearchParams(query);

  assert.deepEqual(params.getAll("keyterm"), [
    "Chase",
    "fraud department",
    "AT&T",
  ]);
});

test("category selection excludes unrelated vocabulary", async () => {
  const config = await loadKeytermConfig();
  const businesses = collectKeyterms(config, ["businesses"]);

  assert.ok(businesses.includes("Chase"));
  assert.ok(!businesses.includes("IRS"));
  assert.ok(!businesses.includes("wire transfer"));
});

test("the CLI emits a parseable business-only JSON list", async () => {
  const { stdout, stderr } = await execFileAsync(
    process.execPath,
    [
      "scripts/deepgram-keyterms.mjs",
      "--category",
      "businesses",
      "--format",
      "json",
    ],
    { cwd: new URL("..", import.meta.url) },
  );
  const keyterms = JSON.parse(stdout);

  assert.equal(stderr, "");
  assert.ok(keyterms.includes("JPMorgan Chase"));
  assert.ok(!keyterms.includes("Federal Trade Commission"));
});
