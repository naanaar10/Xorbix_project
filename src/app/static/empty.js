// The overview when no clinic is picked: the headline, the path to $250M, and where to start.
import { findingsHtml } from "./findings.js";
import { esc, leverProblem, money } from "./format.js";
import { bridgeMath, howWeGot, receipt } from "./math.js";
import { countAll, growBars } from "./motion.js";
import { defaults, levers, plan } from "./whatif.js";

export function renderEmpty(view, network, onPick) {
  const flagged = network.clinics.filter((c) => c.flagged).sort((a, b) => b.at_stake - a.at_stake);
  const parts = [{ key: "today", label: "Revenue today", value: network.revenue }, ...network.bridge];
  const scale = Math.max(network.goal, parts.reduce((sum, p) => sum + p.value, 0));
  const segments = parts.map((p, k) => `<span class="seg k-${esc(p.key)}" data-key="${esc(p.key)}" style="--k:${k}" data-w="${(p.value / scale) * 100}%" title="${esc(p.label)}: ${money(p.value)}"></span>`).join("");
  const legend = parts.map((p, k) => `<li data-key="${esc(p.key)}"><span class="swatch k-${esc(p.key)}"></span><span class="what">${esc(p.label)}</span><span class="amount">${k ? "+" : ""}${money(p.value)}</span></li>`).join("");
  view.innerHTML = `<section class="fade-in">
    <h2 class="headline">${network.flagged_count} of ${network.clinic_count} clinics are losing money</h2>
    <p class="sub">Together they lose <b data-count="${network.at_stake_total}">${money(0)}</b> a year.</p>
    ${network.at_stake_math ? howWeGot(`How we got ${network.at_stake_math.rows.at(-1).value}`, `${receipt(network.at_stake_math.rows)}<p class="note">${esc(network.at_stake_math.note)}</p>`) : ""}
    <div id="summary"></div>
    <div class="bridge">
      <h3>The path from ${money(network.revenue)} to ${money(network.goal)}</h3>
      <div class="bridge-bar" role="img" aria-label="${esc(parts.map((p) => `${p.label} ${money(p.value)}`).join(", "))}">${segments}</div>
      <div class="bridge-scale"><span>$0</span><span>Goal ${money(network.goal)}</span></div>
      <ul class="bridge-legend">${legend}</ul>
      <p class="note">We worked out what each fix is worth across all ${network.clinic_count} clinics, using their own numbers. New clinics make up the rest.</p>
      ${network.bridge[0]?.rows ? howWeGot("How we worked out each step", bridgeMath(network)) : ""}
      ${network.inputs ? plannerHtml(network) : ""}
    </div>
    <p class="hint">Click a red bar to see what the agent found, or start here:</p>
    <div class="picks">${flagged.map((c) => `<button type="button" class="pick" data-id="${esc(c.id)}"><b>${esc(c.city)}</b><span>${money(c.at_stake)} lost each year: ${esc(leverProblem(c.lever))}</span></button>`).join("")}</div>
  </section>`;
  view.querySelectorAll(".pick").forEach((b) => b.addEventListener("click", () => onPick(b.dataset.id)));
  if (network.inputs) wirePlanner(view, network, scale);
  growBars(view);
  countAll(view, money);
}

// What the Manager found in the run, filled in when the run has loaded.
export function renderSummary(el, data, onPick) {
  if (!el) return;
  el.innerHTML = findingsHtml(data);
  el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => onPick(b.dataset.open)));
}

// Try your own plan: one slider per step; the path bar, its amounts and the new clinics needed
// redraw as a slider moves.
function plannerHtml(network) {
  const start = defaults(network.inputs);
  const rows = levers(network.inputs).map((l) => `<label class="slider">
      <span class="name">${esc(l.label)}</span>
      <input type="range" data-key="${l.key}" min="${l.min}" max="${l.max}" step="${l.step}" value="${start[l.key]}">
      <span class="setting" data-setting="${l.key}">${esc(l.show(start[l.key]))}</span>
      <span class="worth" data-worth="${l.key}"></span>
    </label>`).join("");
  return `<details class="math planner"><summary>Try your own plan</summary><div class="math-body">
    <p class="note">Move a slider to see how the path to ${money(network.goal)} changes. The bar above redraws as you go.</p>
    <div class="sliders">${rows}</div>
    <p class="planner-total" aria-live="polite"></p>
    <p><button type="button" class="link" id="reset-plan">Back to our plan</button></p>
  </div></details>`;
}

function wirePlanner(view, network, scale) {
  const list = levers(network.inputs);
  const settings = defaults(network.inputs);
  // The first draw leaves the bar alone, so its opening animation still plays.
  const draw = (first = false) => {
    const p = plan(network.inputs, settings, network.revenue, network.clinic_count, network.goal);
    const amounts = { ...p.values, new_clinics: p.remainder };
    for (const [key, value] of Object.entries(amounts)) {
      const seg = view.querySelector(`.seg[data-key="${key}"]`);
      if (seg && !first) { seg.dataset.w = `${(value / scale) * 100}%`; seg.style.width = seg.dataset.w; }
      const item = view.querySelector(`.bridge-legend li[data-key="${key}"] .amount`);
      if (item) item.textContent = `+${money(value)}`;
    }
    const label = view.querySelector('.bridge-legend li[data-key="new_clinics"] .what');
    if (label) label.textContent = p.newClinics ? `Open about ${p.newClinics} new clinics` : "No new clinics needed";
    for (const l of list) {
      view.querySelector(`[data-setting="${l.key}"]`).textContent = l.show(settings[l.key]);
      view.querySelector(`[data-worth="${l.key}"]`).textContent = `+${money(p.values[l.key])} a year`;
    }
    view.querySelector(".planner-total").innerHTML = p.newClinics
      ? `These fixes add <b>${money(p.fixes)}</b> a year. The other <b>${money(p.remainder)}</b> needs about <b>${p.newClinics} new clinics</b>.`
      : `These fixes add <b>${money(p.fixes)}</b> a year: enough to reach ${money(network.goal)} with no new clinics.`;
  };
  view.querySelectorAll(".planner input[type=range]").forEach((input) => input.addEventListener("input", () => {
    settings[input.dataset.key] = Number(input.value);
    view.querySelector(".bridge-bar").classList.add("live");  // follow the slider, no opening delay
    draw();
  }));
  view.querySelector("#reset-plan").addEventListener("click", () => {
    Object.assign(settings, defaults(network.inputs));
    view.querySelectorAll(".planner input[type=range]").forEach((input) => { input.value = settings[input.dataset.key]; });
    draw();
  });
  draw(true);
}
