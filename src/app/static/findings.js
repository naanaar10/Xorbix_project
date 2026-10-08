// What the Manager found, on the Overview: one card per finding from the run's saved findings (not
// from the Manager's free text, so the layout never depends on how it wrote tonight), with the
// money, the cause, up to three facts and the fix. Its own summary is one click away.
import { agentHtml, boldNumbers, esc, leverProblem, money, proofItems, runKind, when } from "./format.js";
import { howWeGot } from "./math.js";

const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);

function card(d) {
  const network = d.location_id === "NETWORK";
  const place = d.city ?? d.location_id;
  const facts = proofItems(d.evidence).map((f) => `<li>${boldNumbers(esc(capital(f)))}</li>`).join("");
  return `<article class="finding${network ? " network" : ""}">
    <header>
      <div><h4>${esc(place)}</h4><p class="problem">${esc(capital(leverProblem(d.problem_type)))}</p></div>
      <p class="worth"><b>${money(d.at_stake ?? d.revenue_at_stake)}</b> ${network ? "more" : "lost"} a year</p>
    </header>
    <p class="cause">${esc(d.root_cause ?? "")}</p>
    ${facts ? `<ul class="proof">${facts}</ul>` : ""}
    ${d.recommended_fix ? `<p class="fix"><span>Fix</span>${esc(d.recommended_fix)}</p>` : ""}
    <p class="go">${network ? '<a class="link" href="#outreach">See its moves in Outreach</a>'
      : `<button type="button" class="link" data-open="${esc(d.location_id)}">Open ${esc(place)}</button>`}</p>
  </article>`;
}

export function findingsHtml({ run, diagnoses }) {
  if (!run) return "";
  const voice = run.summary ? `<div class="agent-voice">${agentHtml(run.summary)}</div>` : "";
  if (!diagnoses?.length) {
    return voice ? `<figure class="summary">${voice}</figure>` : "";
  }
  return `<section class="findings fade-in" aria-label="What the Manager found">
    <h3>What the Manager found</h3>
    <p class="source">From the ${runKind(run.trigger)} on ${esc(when(run.started_at))}</p>
    <div class="finding-list">${diagnoses.map(card).join("")}</div>
    ${voice ? howWeGot("Read the Manager's own summary", voice) : ""}
  </section>`;
}
