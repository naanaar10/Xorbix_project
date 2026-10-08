// Diagnoses tab: every clinic the run investigated, side by side, with the agent's root cause,
// its evidence and the fix it recommended, all visible.
import { agentHtml, esc, leverProblem, money, runKind, when } from "./format.js";
import { clinicMath, howWeGot } from "./math.js";

export function renderDiagnoses(view, data, onOpen) {
  const { run, diagnoses } = data;
  const cards = diagnoses.map((d) => `<article class="dx">
      <header>
        <h3>${esc(d.city ?? d.location_id)} <span class="id">${esc(d.location_id)}</span></h3>
        <p class="stake">${money(d.at_stake ?? d.revenue_at_stake)} a year at stake: ${esc(leverProblem(d.problem_type))}</p>
        ${d.math ? howWeGot(`How we got ${money(d.at_stake)}`, clinicMath(d.math)) : ""}
      </header>
      <blockquote class="agent-voice">${agentHtml(d.root_cause)}</blockquote>
      <div class="evidence">
        <p><span class="k">Evidence</span>${esc(d.evidence)}</p>
        <p><span class="k">Recommended fix</span>${esc(d.recommended_fix)}</p>
      </div>
      <p class="handoff">Handed to the ${esc(d.specialist)} specialist</p>
      <p><button type="button" class="link" data-open="${esc(d.location_id)}">Open ${esc(d.city ?? d.location_id)}</button></p>
    </article>`).join("");
  const body = !run
    ? '<p class="notice">No runs yet. Run the Director to see diagnoses here.</p>'
    : diagnoses.length ? `<div class="dx-grid">${cards}</div>` : '<p class="notice">This run recorded no diagnoses.</p>';
  view.innerHTML = `<section class="fade-in">
    <header class="tab-head"><h2>Diagnoses</h2>${run ? `<p class="source">From the ${runKind(run.trigger)} on ${esc(when(run.started_at))}. The agent wrote each diagnosis after checking the clinic's data; its numbers come from that data, never from guesswork.</p>` : ""}</header>
    ${body}
  </section>`;
  view.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => onOpen(b.dataset.open)));
}
