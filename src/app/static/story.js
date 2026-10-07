// One clinic's story in four steps: what's wrong, why, what we're doing, did it work.
import { renderActions } from "./actions.js";
import { esc, isWorse, kpiScale, kpiValue, leverProblem, money, pct, plural, runKind, when } from "./format.js";
import { countAll, growBars } from "./motion.js";

const ARMS = { agent: "Agent outreach", generic: "Generic reminder", holdout: "Nothing" };
const PATIENT_CHOICES = [2, 3, 4, 6, 8];

export function renderStory(view, story, handlers) {
  view.innerHTML = `<article class="fade-in">
    ${head(story)}
    <ol class="steps">
      ${whatsWrong(story)}
      ${story.diagnosis ? `${why(story)}<li class="step" id="act-step"></li>${didItWork(story)}` : notInvestigated(story, handlers.pinnedRun)}
    </ol>
    ${handlers.onRun ? runRow(story, handlers.running) : ""}
  </article>`;
  if (story.diagnosis) renderActions(view.querySelector("#act-step"), story, handlers);
  wireEvidence(view);
  view.querySelector("#run")?.addEventListener("click", () => {
    const patients = view.querySelector("#patients");
    handlers.onRun(story.clinic.id, patients ? Number(patients.value) : 4);
  });
  growBars(view);
  countAll(view, money);
}

function head({ clinic, lever, run }) {
  const stake = clinic.flagged
    ? `<p class="stake"><b data-count="${clinic.at_stake}">${money(0)}</b> a year at stake: ${esc(leverProblem(lever))}</p>`
    : `<p class="stake ok">In line with the network${clinic.at_stake >= 1000 ? `: ${money(clinic.at_stake)} a year at stake` : ""}</p>`;
  const source = run ? `<p class="source">From the ${runKind(run.trigger)} on ${esc(when(run.started_at))}</p>` : "";
  return `<header class="story-head"><h2>${esc(clinic.city)}<span class="id">${esc(clinic.id)}</span></h2>${stake}${source}</header>`;
}

function whatsWrong({ kpis }) {
  const rows = kpis.map((k) => {
    const s = kpiScale(k);
    return `<span class="label">${esc(k.label)}</span>
      <span class="track"><span class="fill${isWorse(k) ? " worse" : ""}" data-w="${s.value}%"></span><span class="median" style="left:${s.median}%"></span></span>
      <span class="value">${kpiValue(k.value, k.unit)} <span>vs ${kpiValue(k.median, k.unit)}</span></span>`;
  }).join("");
  return `<li class="step"><h3><span class="n">1</span>What's wrong</h3><div class="kpis">${rows}</div><p class="note">The dark tick is the network median.</p></li>`;
}

function why({ diagnosis }) {
  return `<li class="step"><h3><span class="n">2</span>Why, in the agent's words</h3>
    <blockquote class="agent-voice">${esc(diagnosis.root_cause)}</blockquote>
    <p class="toggle-row"><button type="button" class="link" aria-expanded="false" aria-controls="evidence">Show evidence</button></p>
    <div class="evidence" id="evidence" hidden>
      <p><span class="k">Evidence</span>${esc(diagnosis.evidence)}</p>
      <p><span class="k">Recommended fix</span>${esc(diagnosis.recommended_fix)}</p>
    </div>
    <p class="handoff">Handed to the ${esc(diagnosis.specialist)} specialist</p></li>`;
}

function wireEvidence(view) {
  const button = view.querySelector('[aria-controls="evidence"]');
  button?.addEventListener("click", () => {
    const panel = view.querySelector("#evidence");
    const open = panel.hidden;
    panel.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    button.textContent = open ? "Hide evidence" : "Show evidence";
  });
}

function didItWork({ lever, actions, impact, impact_run: measured }) {
  let body;
  if (lever !== "retention") {
    body = `<p>${plural(actions.length, "outreach draft")} ${actions.length === 1 ? "is" : "are"} waiting for staff. Results are measured once outreach is sent.</p>`;
  } else if (!impact.length) {
    body = "<p>Not measured yet. Results appear after the measure step runs.</p>";
  } else {
    const top = Math.max(0.5, ...impact.map((a) => a.return_rate * 1.25));
    const rows = impact.map((a) => `<span class="arm">${esc(ARMS[a.arm] ?? a.arm)}</span>
      <span class="arm-bar"><span class="bar ${esc(a.arm)}" data-w="${(a.return_rate / top) * 100}%"></span><span class="text"><b>${pct(a.return_rate)}</b> (${a.patients_returned} of ${a.patients})</span></span>`).join("");
    const agent = impact.find((a) => a.arm === "agent");
    const source = measured && !measured.same_as_story
      ? `<p class="note">Measured on the ${runKind(measured.trigger)} of ${esc(when(measured.started_at))}, where ${measured.agent_patients} patients got agent outreach. This run's sample is too small to measure on its own.</p>`
      : "";
    const projection = agent
      ? `<p class="projection">About <b data-count="${agent.annualized_network_revenue}">${money(0)}</b> a year if used across the network. Simulated outcomes: outreach isn't really sent in this prototype.</p>`
      : "";
    body = `${source}<p class="note">Share of patients who came back</p><div class="arms">${rows}</div>${projection}`;
  }
  return `<li class="step"><h3><span class="n">4</span>Did it work</h3>${body}</li>`;
}

function notInvestigated({ clinic }, pinnedRun) {
  const text = pinnedRun
    ? `The run you picked didn't investigate ${clinic.city}. Pick another run in How it works, or run the Director now.`
    : `The Director hasn't investigated ${clinic.city} yet. Run it to find out what's behind these numbers.`;
  return `<li class="step"><h3><span class="n">2</span>Why</h3><p>${esc(text)}</p></li>`;
}

function runRow({ clinic, lever }, running) {
  const label = `Run the Director on ${clinic.city}`;
  const patients = lever === "retention"
    ? `<label>Patients to review <select id="patients">${PATIENT_CHOICES.map((n) => `<option${n === 4 ? " selected" : ""}>${n}</option>`).join("")}</select></label>`
    : "";
  return `<div class="run-row">
    <button type="button" class="primary" id="run" data-label="${esc(label)}"${running ? " disabled" : ""}>${running ? "Running…" : esc(label)}</button>
    ${patients}<span class="note">Takes a minute or two. Each step shows above as it happens.</span>
  </div>`;
}
