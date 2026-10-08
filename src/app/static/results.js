// Results tab: did the agent's outreach bring more patients back than a generic reminder or nothing?
// Also exports the arm bars, which the clinic story's "Did it work" step reuses.
import { esc, money, pct, runKind, when } from "./format.js";
import { countAll, growBars } from "./motion.js";

const ARMS = { agent: "Agent outreach", generic: "Generic reminder", holdout: "Nothing" };

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
    body = '<p class="notice">No runs yet. Run the Director to see results here.</p>';
  } else if (!agent) {
    body = '<p class="notice">This run had no retention outreach to measure. Pick another run in How it works.</p>';
  } else {
    body = `<div class="metrics">
        <div class="metric"><p class="value">${agent.lift_vs_holdout >= 0 ? "+" : ""}${Math.round(agent.lift_vs_holdout * 100)} pts</p><p class="label">more patients came back than with no outreach</p></div>
        <div class="metric"><p class="value" data-count="${agent.recovered_revenue ?? 0}">${money(0)}</p><p class="label">recovered by agent outreach in this run</p></div>
        <div class="metric"><p class="value" data-count="${agent.annualized_network_revenue}">${money(0)}</p><p class="label">a year if used across the network</p></div>
      </div>
      ${armBars(impact)}
      <p class="projection">Patients were split at random before any agent saw them, so the three groups are comparable. Outcomes are simulated: outreach isn't really sent in this prototype.</p>
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
    <summary>See the assumptions</summary>
    <p class="note">Chance a patient comes back, by their hidden reason for stopping (rows) and the outreach they get (columns). No agent can see the reason; the best match for each reason is in bold.</p>
    <div class="table-scroll"><table class="table small"><thead><tr><th scope="col">Hidden reason</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
  </details>`;
}
