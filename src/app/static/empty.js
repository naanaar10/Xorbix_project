// The overview when no clinic is picked: the headline, the path to $250M, and where to start.
import { agentHtml, esc, leverProblem, money, runKind, when } from "./format.js";
import { countAll, growBars } from "./motion.js";

export function renderEmpty(view, network, onPick) {
  const flagged = network.clinics.filter((c) => c.flagged).sort((a, b) => b.at_stake - a.at_stake);
  const parts = [{ key: "today", label: "Revenue today", value: network.revenue }, ...network.bridge];
  const scale = Math.max(network.goal, parts.reduce((sum, p) => sum + p.value, 0));
  const segments = parts.map((p, k) => `<span class="seg k-${esc(p.key)}" style="--k:${k}" data-w="${(p.value / scale) * 100}%" title="${esc(p.label)}: ${money(p.value)}"></span>`).join("");
  const legend = parts.map((p, k) => `<li><span class="swatch k-${esc(p.key)}"></span><span>${esc(p.label)}</span><span class="amount">${k ? "+" : ""}${money(p.value)}</span></li>`).join("");
  view.innerHTML = `<section class="fade-in">
    <h2 class="headline">${network.flagged_count} of ${network.clinic_count} clinics are out of alignment</h2>
    <p class="sub">Together they leave <b data-count="${network.at_stake_total}">${money(0)}</b> a year on the table.</p>
    <div id="summary"></div>
    <div class="bridge">
      <h3>The path from ${money(network.revenue)} to ${money(network.goal)}</h3>
      <div class="bridge-bar" role="img" aria-label="${esc(parts.map((p) => `${p.label} ${money(p.value)}`).join(", "))}">${segments}</div>
      <div class="bridge-scale"><span>$0</span><span>Goal ${money(network.goal)}</span></div>
      <ul class="bridge-legend">${legend}</ul>
      <p class="note">Each fix is priced across all ${network.clinic_count} clinics from the network's own data. New clinics cover the rest.</p>
    </div>
    <p class="hint">Pick a red vertebra to see what the agent found, or start here:</p>
    <div class="picks">${flagged.map((c) => `<button type="button" class="pick" data-id="${esc(c.id)}"><b>${esc(c.city)}</b><span>${money(c.at_stake)} a year at stake: ${esc(leverProblem(c.lever))}</span></button>`).join("")}</div>
  </section>`;
  view.querySelectorAll(".pick").forEach((b) => b.addEventListener("click", () => onPick(b.dataset.id)));
  growBars(view);
  countAll(view, money);
}

// The Director's own summary of a run, filled in when the run has loaded.
export function renderSummary(el, run) {
  if (!el || !run?.summary) return;
  el.innerHTML = `<figure class="summary fade-in">
    <div class="agent-voice">${agentHtml(run.summary)}</div>
    <figcaption>The Director's summary of the ${runKind(run.trigger)} on ${esc(when(run.started_at))}</figcaption>
  </figure>`;
}
