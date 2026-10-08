// Backbone page: the spine on the left, five tabs on the right (Overview, Clinics, Diagnoses,
// Outreach, Results). The URL hash holds the tab and clinic (#outreach, #clinics/LOC007), so reloads
// and the back button work. Diagnoses, Outreach and Results show one whole run: the latest nightly
// run, or the run picked in How it works. A clinic's story shows the latest run for that clinic.
import { get } from "./api.js";
import { renderClinics } from "./clinics.js";
import { renderDiagnoses } from "./diagnoses.js";
import { openDrawer } from "./drawer.js";
import { renderEmpty, renderSummary } from "./empty.js";
import { esc, money } from "./format.js";
import { follow, startRun } from "./live.js";
import { reducedMotion } from "./motion.js";
import { renderOutreach } from "./outreach.js";
import { renderResults } from "./results.js";
import { renderSpine } from "./spine.js";
import { renderStory } from "./story.js";

const view = document.getElementById("view");
const panel = document.getElementById("panel");
const live = document.getElementById("live");
const drawer = document.getElementById("drawer");
const TABS = ["overview", "clinics", "diagnoses", "outreach", "results"];
const SLOW_MS = 4000;
const WAKING = "Waking up the database. The first load can take up to a minute.";

const state = {
  network: null,      // GET /api/network
  meta: null,         // GET /api/meta
  spine: null,        // { select(id) }
  tab: "overview",
  clinic: null,       // clinic whose story is open, or null
  runId: "",          // run picked in How it works; "" means the defaults above
  stories: new Map(), // "LOC007|runId" -> promise of GET /api/clinics/LOC007
  runs: new Map(),    // runId -> promise of GET /api/run
  showing: 0,         // increases with every view, so late answers for an old view are dropped
  liveRunId: null,    // the live run being followed, if any
};

const cityOf = (id) => state.network?.clinics.find((c) => c.id === id)?.city ?? id;
const go = (hash) => { location.hash = hash; };
const openClinic = (id) => go(`#clinics/${id}`);

function notice(text, retry) {
  view.classList.remove("loading");
  view.innerHTML = `<p class="notice${retry ? " error" : ""}">${esc(text)}${retry ? ' <button type="button" class="link" id="retry">Try again</button>' : ""}</p>`;
  if (retry) view.querySelector("#retry").addEventListener("click", retry);
}

// ---- data

function cached(map, key, url) {
  if (!map.has(key)) {
    map.set(key, get(url).catch((error) => {
      map.delete(key);
      throw error;
    }));
  }
  return map.get(key);
}

const runQuery = () => (state.runId ? `?run_id=${encodeURIComponent(state.runId)}` : "");
const loadStory = (id) => cached(state.stories, `${id}|${state.runId}`, `/api/clinics/${encodeURIComponent(id)}${runQuery()}`);
const loadRun = () => cached(state.runs, state.runId, `/api/run${runQuery()}`);
const loadMeta = () => (state.meta ? Promise.resolve(state.meta) : refreshMeta());

function handlers() {
  return {
    pinnedRun: state.runId,
    running: Boolean(state.liveRunId),
    onRun: run,
    onDecided(actionId, status, message) {
      // Keep cached stories and runs in step with what staff decided, so every tab agrees.
      for (const promise of [...state.stories.values(), ...state.runs.values()]) {
        promise.then((data) => data.actions.forEach((a) => {
          if (a.action_id !== actionId) return;
          a.status = status;
          if (message !== undefined) a.message = message;
        })).catch(() => {});
      }
    },
  };
}

// ---- views

async function display(what, load, draw) {
  const token = ++state.showing;
  if (view.querySelector(".notice")) view.innerHTML = `<p class="notice">Loading ${esc(what)}…</p>`;
  view.classList.add("loading");
  const slow = setTimeout(() => { if (token === state.showing) notice(WAKING); }, SLOW_MS);
  try {
    const data = await load();
    if (token === state.showing) draw(data);
  } catch (error) {
    if (token === state.showing) notice(`Couldn't load ${what}: ${error.message}`, route);
  } finally {
    clearTimeout(slow);
    if (token === state.showing) view.classList.remove("loading");
  }
}

function show(tab, clinic) {
  state.tab = tab;
  state.clinic = clinic;
  state.spine?.select(clinic);
  document.querySelectorAll("#tabs a").forEach((a) => a.setAttribute("aria-current", a.dataset.tab === tab ? "page" : "false"));
  view.classList.toggle("wide", (tab === "clinics" && !clinic) || tab === "outreach" || tab === "diagnoses");
  panel.scrollTo({ top: 0 });
  if (tab === "clinics" && clinic) {
    display(cityOf(clinic), () => loadStory(clinic), (story) => renderStory(view, story, handlers()));
  } else if (tab === "clinics") {
    state.showing++;
    view.classList.remove("loading");
    renderClinics(view, state.network, openClinic);
  } else if (tab === "diagnoses") {
    display("the problems", loadRun, (data) => renderDiagnoses(view, data, openClinic));
  } else if (tab === "outreach") {
    display("the messages", loadRun, (data) => renderOutreach(view, data, handlers()));
  } else if (tab === "results") {
    display("the results", () => Promise.all([loadRun(), loadMeta()]),
      ([data, meta]) => renderResults(view, data, meta.assumptions));
  } else {
    const token = ++state.showing;
    view.classList.remove("loading");
    renderEmpty(view, state.network, openClinic);
    loadRun().then((data) => { if (token === state.showing) renderSummary(view.querySelector("#summary"), data.run); })
      .catch(() => {});
  }
}

function route() {
  const [first, second] = decodeURIComponent(location.hash.replace(/^#\/?/, "")).split("/");
  const known = (id) => state.network.clinics.some((c) => c.id === id);
  if (known(first)) return show("clinics", first); // older links like #LOC007
  const tab = TABS.includes(first) ? first : "overview";
  return show(tab, tab === "clinics" && known(second) ? second : null);
}

async function prefetch() {
  // Load the nightly run and the flagged clinics' stories in the background, so tabs open at once.
  await loadRun().catch(() => {});
  const flagged = state.network.clinics.filter((c) => c.flagged).sort((a, b) => b.at_stake - a.at_stake);
  for (const c of flagged) await loadStory(c.id).catch(() => {});
}

// ---- live runs

function setRunButtons() {
  const button = view.querySelector("#run");
  if (!button) return;
  button.disabled = Boolean(state.liveRunId);
  button.textContent = state.liveRunId ? "Running…" : button.dataset.label;
}

function liveOptions(clinic, patients) {
  return {
    cityOf,
    onStart(runId) {
      state.liveRunId = runId;
    },
    onDone(event) {
      state.liveRunId = null;
      state.stories.clear(); // the clinic's story now comes from the new run
      state.runs.clear();
      state.runId = "";
      refreshMeta().catch(() => {});
      if (state.tab === "clinics" && state.clinic === event.clinic) route();
      else setRunButtons();
    },
    onFail() {
      state.liveRunId = null;
      setRunButtons();
    },
    retry: () => run(clinic, patients),
  };
}

function run(clinic, patients) {
  if (state.liveRunId) return;
  state.liveRunId = "starting";
  setRunButtons();
  panel.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
  startRun(live, clinic, patients, liveOptions(clinic, patients));
}

async function refreshMeta() {
  state.meta = await get("/api/meta");
  const active = state.meta.active_run;
  if (active && !state.liveRunId) { // the page was reloaded during a run: pick it back up
    state.liveRunId = active.run_id;
    setRunButtons();
    follow(live, active.run_id, active.clinic, liveOptions(active.clinic, active.patients));
  }
  return state.meta;
}

// ---- how it works

async function openHowItWorks() {
  try {
    const meta = await refreshMeta();
    const shown = state.clinic
      ? (await loadStory(state.clinic).catch(() => null))?.run
      : (await loadRun().catch(() => null))?.run;
    openDrawer(drawer, { meta, runId: state.runId, shownRunId: shown?.run_id ?? (state.runId || null), onPickRun: pickRun });
  } catch (error) {
    openDrawer(drawer, { error: error.message });
  }
}

function pickRun(runId) {
  state.runId = runId;
  route();
}

// ---- start

async function boot() {
  const slow = setTimeout(() => notice(WAKING), SLOW_MS);
  try {
    state.network = await get("/api/network");
  } catch (error) {
    notice(`Couldn't load the clinic network: ${error.message}`, () => location.reload());
    return;
  } finally {
    clearTimeout(slow);
  }
  const n = state.network;
  document.getElementById("goal").innerHTML = `<b>${money(n.revenue)}</b> today, goal <b>${money(n.goal)}</b>`;
  document.getElementById("rail-title").innerHTML = `<b>${n.flagged_count} of ${n.clinic_count}</b> clinics losing money`;
  state.spine = renderSpine(document.getElementById("spine"), n.clinics, openClinic);
  window.addEventListener("hashchange", route);
  route();
  prefetch();
  refreshMeta().catch(() => {});
}

document.getElementById("open-drawer").addEventListener("click", openHowItWorks);
document.getElementById("close-drawer").addEventListener("click", () => drawer.close());
boot();
