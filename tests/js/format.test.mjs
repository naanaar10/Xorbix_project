import assert from "node:assert/strict";
import { test } from "node:test";
import { agentHtml, duration, esc, isWorse, kpiScale, kpiValue, leverProblem, money, plural, slotLabel, when } from "../../src/app/static/format.js";

test("money uses K below a million and M above", () => {
  assert.equal(money(467808), "$468K");
  assert.equal(money(1135880), "$1.1M");
  assert.equal(money(999600), "$1.0M");
  assert.equal(money(29.7e6), "$29.7M");
  assert.equal(money(102.4e6), "$102M");
  assert.equal(money(0), "$0");
  assert.equal(money(null), "$0");
});

test("esc makes agent text safe to put in HTML", () => {
  assert.equal(esc(`<b>"Hi" & 'bye'</b>`), "&lt;b&gt;&quot;Hi&quot; &amp; &#39;bye&#39;&lt;/b&gt;");
  assert.equal(esc(null), "");
});

test("KPI values, scales and direction", () => {
  assert.equal(kpiValue(0.344, "pct"), "34%");
  assert.equal(kpiValue(36.2, "hours"), "36 hours");
  assert.equal(kpiValue(3.14, "hours"), "3.1 hours");
  assert.equal(kpiValue(120, "count"), "120");
  assert.deepEqual(kpiScale({ value: 0.25, median: 0.5, unit: "pct" }), { value: 25, median: 50 });
  assert.deepEqual(kpiScale({ value: 8, median: 2, unit: "hours" }), { value: 80, median: 20 });
  assert.deepEqual(kpiScale({ value: 0, median: 0, unit: "count" }), { value: 0, median: 0 });
  assert.equal(isWorse({ value: 0.34, median: 0.51, better: "higher" }), true);
  assert.equal(isWorse({ value: 36, median: 3, better: "lower" }), true);
  assert.equal(isWorse({ value: 0.8, median: 0.76, better: "higher" }), false);
});

test("slots and times read like a calendar", () => {
  assert.equal(slotLabel("2026-10-09 13:30 with PRV0043"), "Fri, Oct 9, 1:30 PM with PRV0043");
  assert.equal(slotLabel("2026-10-09 09:00"), "Fri, Oct 9, 9:00 AM");
  assert.equal(slotLabel("next Tuesday"), "next Tuesday");
  assert.equal(when("2026-10-07T15:38:08.593Z"), "Oct 7, 10:38 AM");
  assert.equal(duration(102), "1:42");
  assert.equal(duration(5), "0:05");
  assert.equal(plural(1, "patient"), "1 patient");
  assert.equal(plural(4, "outreach draft"), "4 outreach drafts");
});

test("the agent's Markdown becomes safe HTML: bold and bullets only, headings dropped", () => {
  assert.equal(
    agentHtml("**Executive Summary**\n\n- **Chicago (LOC012)** \u2013 leads wait.  \n- **<b>x</b>** & co"),
    "<ul><li><b>Chicago (LOC012)</b> \u2013 leads wait.</li><li><b>&lt;b&gt;x&lt;/b&gt;</b> &amp; co</li></ul>");
  assert.equal(agentHtml("One line.\nAnother line."), "<p>One line.</p><p>Another line.</p>");
  assert.equal(agentHtml(null), "");
});

test("every problem the agents can find has plain words", () => {
  for (const lever of ["retention", "leads", "capacity", "marketing", "loyalty"]) {
    assert.notEqual(leverProblem(lever), "revenue is leaking", lever);
  }
});
