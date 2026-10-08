// Outreach tab: every draft in the run in one table, filterable by clinic, with Approve and Skip on
// each row. Click a message to edit it; the edit is saved when the row is approved.
import { decision, updateApproveAll, wireDecisions } from "./actions.js";
import { esc, plural, runKind, slotLabel, when } from "./format.js";

export function renderOutreach(view, data, handlers) {
  const { run, actions, controls } = data;
  if (!run) {
    view.innerHTML = '<section class="fade-in"><header class="tab-head"><h2>Messages</h2></header><p class="notice">No runs yet. Run the Director to see its messages here.</p></section>';
    return;
  }
  const clinics = [...new Map(actions.map((a) => [a.location_id, a.city ?? a.location_id]))];
  const count = (id) => actions.filter((a) => a.location_id === id).length;
  const chips = [`<button type="button" class="chip" data-clinic="" aria-pressed="true">All ${actions.length}</button>`,
    ...clinics.map(([id, city]) => `<button type="button" class="chip" data-clinic="${esc(id)}" aria-pressed="false">${esc(city)} ${count(id)}</button>`)].join("");
  const controlNotes = Object.entries(controls).map(([id, arms]) =>
    `${esc(clinics.find(([c]) => c === id)?.[1] ?? id)}: ${arms.holdout ?? 0} get no message (the holdout group), ${arms.generic ?? 0} get a plain reminder`).join("; ");
  const rows = actions.map((a) => `<tr class="item" data-id="${esc(a.action_id)}" data-status="${esc(a.status)}" data-clinic="${esc(a.location_id)}">
      <td><b>${esc(a.city ?? a.location_id)}</b><span class="sub">${esc(a.specialist ?? "")}</span></td>
      <td>${esc(a.target_id)}<span class="sub">${a.target_type === "lead" ? "Lead" : "Patient"}</span></td>
      <td>${esc(a.intervention)}<span class="sub">${esc(a.channel ?? "")}</span></td>
      <td>${a.offered_slot ? esc(slotLabel(a.offered_slot)) : '<span class="sub">None</span>'}</td>
      <td class="msg"><p class="message" tabindex="0" title="Click to edit">${esc(a.message ?? "")}</p></td>
      <td class="why">${esc(a.rationale ?? "")}</td>
      <td class="decision"><div class="decide">${decision(a.status)}</div><p class="card-error" role="alert" hidden></p></td>
    </tr>`).join("");
  view.innerHTML = `<section class="fade-in">
    <header class="tab-head"><h2>Messages</h2><p class="source">From the ${runKind(run.trigger)} on ${esc(when(run.started_at))}. Nothing is sent until staff approve it.</p></header>
    <div class="act-head">
      <div class="chips" role="group" aria-label="Show clinic">${chips}</div>
      <button type="button" class="quiet" id="approve-all" hidden></button>
    </div>
    ${controlNotes ? `<p class="note">To check the agent really helps, other patients were picked at random. ${controlNotes}.</p>` : ""}
    ${actions.length ? `<div class="table-scroll"><table class="table outreach">
      <thead><tr><th scope="col">Clinic</th><th scope="col">Patient or lead</th><th scope="col">Message type</th><th scope="col">Time offered</th><th scope="col">Message</th><th scope="col">Why the agent chose it</th><th scope="col">Decision</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : '<p class="notice">No messages were written in this run.</p>'}
    <p class="act-error" role="alert" hidden></p>
    <p class="note">${plural(actions.length, "message")} in this run.</p>
  </section>`;
  let shown = "";
  view.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => {
    shown = chip.dataset.clinic;
    view.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
    view.querySelectorAll("tr.item").forEach((tr) => tr.classList.toggle("filtered-out", Boolean(shown) && tr.dataset.clinic !== shown));
    updateApproveAll(view);
  }));
  wireDecisions(view, () => ({ run_id: run.run_id, location_id: shown || null }), handlers);
}
