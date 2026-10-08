// Results tab: did the agent's outreach bring more patients back than a generic reminder or nothing?
// Also exports the arm bars, which the clinic story's "Did it work" step reuses.
import { esc, money, pct, runKind, when } from "./format.js";
import { howWeGot, outcomeMath } from "./math.js";
import { countAll, growBars } from "./motion.js";

const ARMS = { agent: "Agent's message", generic: "Plain reminder", holdout: "No message" };

export function armBars(impact) {
  const top = Math.max(0.5, ...impact.map((a) => a.return_rate * 1.25));
  const rows = impact.map((a) => `<span class="arm">${esc(ARMS[a.arm] ?? a.arm)}</span>
    <span class="arm-bar"><span class="bar ${esc(a.arm)}" data-w="${(a.return_rate / top) * 100}%"></span><span class="text"><b>${pct(a.return_rate)}</b> (${a.patients_returned} of ${a.patients})</span></span>`).join("");
  return `<p class="note">Share of patients who came back</p><div class="arms">${rows}</div>`;
}

export function renderResults(view, data, assumptions) {
  const { run, impact } = data;
  const agent = impact.find((a) => a.arm === "agent");
  let body;
  if (!run) {
    body = '<p class="notice">No runs yet. Run the Manager to see results here.</p>';
  } else if (!agent) {
    body = '<p class="notice">This run had no patient messages to measure. Pick another run in How it works.</p>';
  } else {
    body = `<div class="metrics">
        <div class="metric"><p class="value">${agent.lift_vs_holdout >= 0 ? "+" : ""}${Math.round(agent.lift_vs_holdout * 100)} pts</p><p class="label">more patients came back than with no message</p></div>
        <div class="metric"><p class="value" data-count="${agent.recovered_revenue ?? 0}">${money(0)}</p><p class="label">won back by the agent's messages this run</p></div>
        <div class="metric"><p class="value" data-count="${agent.annualized_network_revenue}">${money(0)}</p><p class="label">a year if every clinic did this</p></div>
      </div>
      ${data.impact_math ? howWeGot("How we got these three numbers", outcomeMath(data.impact_math)) : ""}
      ${armBars(impact)}
      <p class="projection">Before the agent saw anyone, patients were split into three groups at random, so the comparison is fair. These results are simulated: the messages aren't really sent in this demo.</p>
      ${assumptionsTable(assumptions)}`;
  }
  view.innerHTML = `<section class="fade-in">
    <header class="tab-head"><h2>Results</h2>${run ? `<p class="source">From the ${runKind(run.trigger)} on ${esc(when(run.started_at))}</p>` : ""}</header>
    ${body}
  </section>`;
  growBars(view);
  countAll(view, money);
}

function assumptionsTable(assumptions) {
  if (!assumptions) return "";
  const head = assumptions.interventions.map((i) => `<th scope="col">${esc(i)}</th>`).join("");
  const rows = assumptions.rows.map((row, r) => {
    const best = Math.max(...row);
    return `<tr><th scope="row">${esc(assumptions.reasons[r])}</th>${row.map((p) => `<td class="num${p === best ? " best" : ""}">${pct(p)}</td>`).join("")}</tr>`;
  }).join("");
  return `<details class="assumptions">
    <summary>See what we assumed</summary>
    <p class="note">How likely a patient is to come back, depending on why they really stopped (rows) and which message they get (columns). The agent never sees the real reason. The best message for each reason is in bold.</p>
    <div class="table-scroll"><table class="table small"><thead><tr><th scope="col">Real reason (hidden)</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
  </details>`;
}
