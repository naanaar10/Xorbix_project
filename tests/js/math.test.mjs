import assert from "node:assert/strict";
import { test } from "node:test";
import { clinicMath, howWeGot, receipt } from "../../src/app/static/math.js";

const row = (label, value, how = "") => ({ label, value, how });

test("receipt lists each step and marks the last one as the result", () => {
  const html = receipt([row("Gap", "11.9 pts", "29.0% − 15.1% − 2 pts"), row("A year at stake", "$1.14M", "1,007 × $1,128")]);
  assert.match(html, /<table class="receipt">/);
  assert.match(html, /<tr><th scope="row">Gap<\/th><td class="num">11.9 pts<\/td><td class="how">29.0% − 15.1% − 2 pts<\/td><\/tr>/);
  assert.match(html, /<tr class="result"><th scope="row">A year at stake<\/th>/);
  assert.doesNotMatch(receipt([row("Per visit", "$110.87")], { result: false }), /result/);
  assert.match(receipt([row("<b>", "$1")]), /&lt;b&gt;/);
});

test("howWeGot wraps the math in a closed disclosure", () => {
  assert.equal(howWeGot("How we got $1.1M", "<p>x</p>"),
    '<details class="math"><summary>How we got $1.1M</summary><div class="math-body"><p>x</p></div></details>');
});

test("clinic math shows problems with money at stake in full and the rest in one list", () => {
  const math = {
    levers: [
      { key: "leads", title: "Slow lead replies", value: 1135880, rows: [row("Gap", "11.9 pts"), row("A year at stake", "$1.14M")] },
      { key: "capacity", title: "Empty chairs", value: 0, rows: [row("Mornings booked gap", "0 pts", "better"), row("A year at stake", "$0")], note: null },
    ],
    total: row("Total a year at stake", "$1.14M", "$1.14M + $0"),
  };
  const html = clinicMath(math);
  assert.match(html, /<h4>Slow lead replies: \$1.14M<\/h4>/);
  assert.match(html, /<h4>Within normal range: \$0<\/h4>.*Mornings booked gap/s);
  assert.doesNotMatch(html.split("Within normal range")[1], /A year at stake/);
  assert.match(html, /Total a year at stake/);
});
