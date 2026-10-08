// One clinic's story in four steps: what's wrong, why, what we're doing, did it work.
import { renderActions } from "./actions.js";
import { agentHtml, esc, isWorse, kpiScale, kpiValue, leverProblem, money, plural, runKind, when } from "./format.js";
import { clinicMath, howWeGot, outcomeMath } from "./math.js";
import { countAll, growBars } from "./motion.js";
import { armBars } from "./results.js";
const PATIENT_CHOICES = [2, 3, 4, 6, 8];

export function renderStory(view, story, handlers) {
  view.innerHTML = `<article class="fade-in">
    <p class="back"><a href="#clinics">All clinics</a></p>
    ${head(story)}
    <ol class="steps">
      ${whatsWrong(story)}
      ${story.diagnosis ? `${why(story)}<li class="step" id="act-step"></li>${didItWork(story)}` : notInvestigated(story, handlers.pinnedRun)}
    </ol>
    ${handlers.onRun ? runRow(story, handlers.running) : ""}
  </article>`;
  if (story.diagnosis) renderActions(view.querySelector("#act-step"), story, handlers);
  view.querySelector("#run")?.addEventListener("click", () => {
    const patients = view.querySelector("#patients");
    handlers.onRun(story.clinic.id, patients ? Number(patients.value) : 4);
  });
  growBars(view);
  countAll(view, money);
}

function head({ clinic, lever, run, math }) {
  const stake = clinic.flagged
    ? `<p class="stake"><b data-count="${clinic.at_stake}">${money(0)}</b> lost each year: ${esc(leverProblem(lever))}</p>`
    : `<p class="stake ok">Doing about as well as the other clinics${clinic.at_stake >= 1000 ? `: ${money(clinic.at_stake)} lost each year` : ""}</p>`;
  const source = run ? `<p class="source">From the ${runKind(run.trigger)} on ${esc(when(run.started_at))}</p>` : "";
  const how = math ? howWeGot(`How we got ${math.total.value}`, clinicMath(math, math.units)) : "";
  return `<header class="story-head"><h2>${esc(clinic.city)}<span class="id">${esc(clinic.id)}</span></h2>${stake}${how}${source}</header>`;
}

function whatsWrong({ kpis }) {
  const rows = kpis.map((k) => {
    const s = kpiScale(k);
    return `<span class="label">${esc(k.label)}</span>
      <span class="track"><span class="fill${isWorse(k) ? " worse" : ""}" data-w="${s.value}%"></span><span class="median" style="left:${s.median}%"></span></span>
      <span class="value">${kpiValue(k.value, k.unit)} <span>vs ${kpiValue(k.median, k.unit)}</span></span>`;
  }).join("");
  const meanings = kpis.filter((k) => k.meaning).map((k) => `<dt>${esc(k.label)}</dt><dd>${esc(k.meaning)}</dd>`).join("");
  return `<li class="step"><h3><span class="n">1</span>What's wrong</h3><div class="kpis">${rows}</div>
    <p class="note">First this clinic's number, then the typical clinic's. The dark line on each bar is the typical clinic.</p>
    ${meanings ? howWeGot("What these measure", `<dl class="meanings">${meanings}</dl>`) : ""}</li>`;
}

function why({ diagnosis }) {
  return `<li class="step"><h3><span class="n">2</span>Why, in the agent's words</h3>
    <blockquote class="agent-voice">${agentHtml(diagnosis.root_cause)}</blockquote>
    <div class="evidence">
      <p><span class="k">What the numbers show</span>${esc(diagnosis.evidence)}</p>
      <p><span class="k">What to do</span>${esc(diagnosis.recommended_fix)}</p>
    </div>
    <p class="handoff">Passed to the ${esc(diagnosis.specialist)} specialist agent</p></li>`;
}

function didItWork({ lever, actions, impact, impact_run: measured, impact_math: math }) {
  let body;
  if (lever !== "retention") {
    body = `<p>${plural(actions.length, "message")} ${actions.length === 1 ? "is" : "are"} waiting for staff. We can measure results once they're sent.</p>`;
  } else if (!impact.length) {
    body = "<p>Not measured yet. Results appear after the measure step runs.</p>";
  } else {
    const agent = impact.find((a) => a.arm === "agent");
    const source = measured && !measured.same_as_story
      ? `<p class="note">These results come from the ${runKind(measured.trigger)} of ${esc(when(measured.started_at))}, where ${measured.agent_patients} patients got the agent's message. This run had too few patients to measure on its own.</p>`
      : "";
    const projection = agent
      ? `<p class="projection">About <b data-count="${agent.annualized_network_revenue}">${money(0)}</b> a year if every clinic did this. These results are simulated: the messages aren't really sent in this demo.</p>`
      : "";
    const how = agent && math ? howWeGot(`How we got ${math.annualized.at(-1).value}`, outcomeMath(math)) : "";
    body = `${source}${armBars(impact)}${projection}${how}`;
  }
  return `<li class="step"><h3><span class="n">4</span>Did it work</h3>${body}</li>`;
}

function notInvestigated({ clinic }, pinnedRun) {
  const text = pinnedRun
    ? `The run you picked didn't investigate ${clinic.city}. Pick another run in How it works, or run the Manager now.`
    : `The Manager hasn't investigated ${clinic.city} yet. Run it to find out what's behind these numbers.`;
  return `<li class="step"><h3><span class="n">2</span>Why</h3><p>${esc(text)}</p></li>`;
}

function runRow({ clinic, lever }, running) {
  const label = `Run the Manager on ${clinic.city}`;
  const patients = lever === "retention"
    ? `<label>Patients to review <select id="patients">${PATIENT_CHOICES.map((n) => `<option${n === 4 ? " selected" : ""}>${n}</option>`).join("")}</select></label>`
    : "";
  return `<div class="run-row">
    <button type="button" class="primary" id="run" data-label="${esc(label)}"${running ? " disabled" : ""}>${running ? "Running…" : esc(label)}</button>
    ${patients}<span class="note">Takes a minute or two. Each step shows above as it happens.</span>
  </div>`;
}
