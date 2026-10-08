import assert from "node:assert/strict";
import { test } from "node:test";
import { findingsHtml } from "../../src/app/static/findings.js";
import { agentHtml, boldNumbers, proofItems } from "../../src/app/static/format.js";

test("boldNumbers makes figures stand out but leaves ids and escapes alone", () => {
  assert.equal(boldNumbers("36 hours vs typical 3"), "<b>36</b> hours vs typical <b>3</b>");
  assert.equal(boldNumbers("66% vs 4%; costs $329 and $645,118"), "<b>66%</b> vs <b>4%</b>; costs <b>$329</b> and <b>$645,118</b>");
  assert.equal(boldNumbers("uptake 27.8% adds $3.2 M"), "uptake <b>27.8%</b> adds <b>$3.2 M</b>");
  assert.equal(boldNumbers("One chiropractor (PRV0041) doesn&#39;t"), "One chiropractor (PRV0041) doesn&#39;t");
});

test("proofItems splits the evidence into at most three facts", () => {
  assert.deepEqual(proofItems("a; b ;c; d"), ["a", "b", "c"]);
  assert.deepEqual(proofItems("only one"), ["only one"]);
  assert.deepEqual(proofItems(""), []);
  assert.deepEqual(proofItems(null), []);
});

test("agentHtml turns *word* into italics and keeps bullets working", () => {
  assert.equal(agentHtml("*Fix:* Set up a first-hour inbox."), "<p><i>Fix:</i> Set up a first-hour inbox.</p>");
  assert.equal(agentHtml("* one\n* two"), "<ul><li>one</li><li>two</li></ul>");
});

const RUN = { run_id: "r1", trigger: "scheduled", started_at: "2026-10-08T18:26:54Z",
  summary: "**Chicago** – Leads wait.\n*Fix:* Reply in an hour." };
const CHICAGO = { location_id: "LOC012", city: "Chicago", problem_type: "leads", at_stake: 1135880,
  root_cause: "Leads wait far too long for a reply.", evidence: "36 hours vs typical 3; afternoon no-show 17% vs typical 9%",
  recommended_fix: "Call every new lead within an hour." };
const MARKETING = { location_id: "NETWORK", city: "Whole network", problem_type: "marketing", at_stake: 3167737,
  root_cause: "Too much money sits in Paid Search.", evidence: "Paid Search costs $329 per new patient",
  recommended_fix: "Move money to referrals." };

test("findingsHtml shows one card per finding with its money, cause, facts and fix", () => {
  const html = findingsHtml({ run: RUN, diagnoses: [CHICAGO, MARKETING] });
  assert.equal((html.match(/<article class="finding/g) || []).length, 2);
  assert.match(html, /<h4>Chicago<\/h4><p class="problem">Leads wait too long for a reply<\/p>/);
  assert.match(html, /<b>\$1\.1M<\/b> lost a year/);
  assert.match(html, /<b>\$3\.2M<\/b> more a year/);
  assert.match(html, /<li><b>36<\/b> hours vs typical <b>3<\/b><\/li>/);
  assert.match(html, /<li>Afternoon no-show <b>17%<\/b> vs typical <b>9%<\/b><\/li>/);
  assert.match(html, /Call every new lead within an hour\./);
  assert.match(html, /data-open="LOC012">Open Chicago</);
  assert.match(html, /href="#outreach"/);
  assert.match(html, /finding network/);
  // The Manager's own words are one click away.
  assert.match(html, /Read the Manager&#39;s own summary/);
  assert.match(html, /<i>Fix:<\/i>/);
});

test("findingsHtml is empty without a run and falls back to the summary without findings", () => {
  assert.equal(findingsHtml({ run: null, diagnoses: [] }), "");
  const html = findingsHtml({ run: RUN, diagnoses: [] });
  assert.doesNotMatch(html, /<article/);
  assert.match(html, /Leads wait\./);
});
