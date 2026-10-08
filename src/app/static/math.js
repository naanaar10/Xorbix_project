// "How we got this": the math behind a number, as rows of what it is, its value and how it was
// worked out. The server builds the rows (src/app/explain.py) from the same values as the number.
import { esc } from "./format.js";

const ROUNDING = "Numbers are rounded to make them easy to read.";

export function receipt(rows, { result = true } = {}) {
  const body = rows.map((r, i) => `<tr${result && i === rows.length - 1 ? ' class="result"' : ""}><th scope="row">${esc(r.label)}</th><td class="num">${esc(r.value)}</td><td class="how">${esc(r.how)}</td></tr>`).join("");
  return `<table class="receipt"><tbody>${body}</tbody></table>`;
}

export const howWeGot = (summary, body) =>
  `<details class="math"><summary>${esc(summary)}</summary><div class="math-body">${body}</div></details>`;

const block = (title, rows, options) => `<h4>${esc(title)}</h4>${receipt(rows, options)}`;
const note = (text) => (text ? `<p class="note">${esc(text)}</p>` : "");

// One clinic's revenue at stake: each problem with money at stake, step by step; then the
// problems inside normal variation, which count as $0; then the total.
export function clinicMath(math, units) {
  const atStake = math.levers.filter((l) => l.value > 0);
  const normal = math.levers.filter((l) => !(l.value > 0));
  return [
    ...atStake.map((l) => block(`${l.title}: ${l.rows.at(-1).value}`, l.rows) + note(l.note)),
    normal.length ? block("Small differences we ignore: $0", normal.flatMap((l) => l.rows.slice(0, -1)), { result: false }) : "",
    receipt([math.total]),
    `<p class="note">We only count money where a clinic does worse than the typical clinic by more than a little: 3 points for plan completion, 2 for lead conversion and no-shows, 10 for how full the schedule is. Small differences like that happen everywhere, so we ignore them. ${ROUNDING}</p>`,
    units ? unitMath(units) : "",
  ].join("");
}

export const unitMath = (units) => block("Where the dollar amounts come from", units, { result: false });

export function bridgeMath(network) {
  return [
    ...network.bridge.map((b) => block(`${b.label}: +${b.rows.at(-1).value}`, b.rows)),
    unitMath(network.units),
    `<p class="note">${ROUNDING}</p>`,
  ].join("");
}

const signed = (value) => (value.startsWith("-") ? value : `+${value}`);

// The three Results numbers.
export function outcomeMath(math) {
  return [
    block(`More patients came back: ${signed(math.lift.at(-1).value)}`, math.lift),
    block(`Money won back this run: ${math.recovered.at(-1).value}`, math.recovered),
    block(`A year across the network: ${math.annualized.at(-1).value}`, math.annualized),
    `<p class="note">These results are simulated: the messages aren't really sent in this demo. ${ROUNDING}</p>`,
  ].join("");
}
