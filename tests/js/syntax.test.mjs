import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

// The page has no build step, so a typo in any script breaks it in the browser. Parse them all
// as ES modules (a plain `node --check file.js` lets some errors through).
const dir = new URL("../../src/app/static/", import.meta.url);

test("every page script parses", () => {
  const scripts = readdirSync(dir).filter((f) => f.endsWith(".js"));
  assert.ok(scripts.length > 5);
  for (const file of scripts) {
    const input = readFileSync(new URL(file, dir));
    assert.doesNotThrow(() => execFileSync(process.execPath, ["--input-type=module", "--check"], { input, stdio: "pipe" }), file);
  }
});
