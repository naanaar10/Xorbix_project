// Growth Director page: loads the network, draws the spine, and shows one clinic's story at a
// time. The URL hash holds the selected clinic (#LOC007), so reloads and the back button work.
import { get } from "./api.js";
import { renderEmpty } from "./empty.js";
import { esc, money } from "./format.js";
import { renderSpine } from "./spine.js";
import { renderStory } from "./story.js";

const view = document.getElementById("view");
const panel = document.getElementById("panel");
const SLOW_MS = 4000;
const WAKING = "Waking up the SQL warehouse. The first load can take up to a minute.";

const state = {
  network: null,      // GET /api/network
  spine: null,        // { select(id) }
  clinic: null,       // selected clinic id, or null for the overview
  runId: "",          // run picked in How it works; "" means the latest run for each clinic
  stories: new Map(), // "LOC007|runId" -> promise of GET /api/clinics/LOC007
};

const cityOf = (id) => state.network?.clinics.find((c) => c.id === id)?.city ?? id;

function notice(text, retry) {
  view.classList.remove("loading");
  view.innerHTML = `<p class="notice${retry ? " error" : ""}">${esc(text)}${retry ? ' <button type="button" class="link" id="retry">Try again</button>' : ""}</p>`;
  if (retry) view.querySelector("#retry").addEventListener("click", retry);
}

// ---- clinic stories

function loadStory(id) {
  const key = `${id}|${state.runId}`;
  if (!state.stories.has(key)) {
    const query = state.runId ? `?run_id=${encodeURIComponent(state.runId)}` : "";
    state.stories.set(key, get(`/api/clinics/${encodeURIComponent(id)}${query}`).catch((error) => {
      state.stories.delete(key);
      throw error;
    }));
  }
  return state.stories.get(key);
}

function handlers() {
  return {
    pinnedRun: state.runId,
    onDecided(actionId, status, message) {
      // Keep cached stories in step with what staff decided, so going back shows the same state.
      for (const story of state.stories.values()) {
        story.then((s) => s.actions.forEach((a) => {
          if (a.action_id !== actionId) return;
          a.status = status;
          if (message !== undefined) a.message = message;
        })).catch(() => {});
      }
    },
  };
}

async function show(id) {
  state.clinic = id;
  state.spine?.select(id);
  panel.scrollTo({ top: 0 });
  if (!id) {
    renderEmpty(view, state.network, pick);
    return;
  }
  if (view.querySelector(".notice")) view.innerHTML = `<p class="notice">Loading ${esc(cityOf(id))}…</p>`;
  view.classList.add("loading");
  const slow = setTimeout(() => { if (state.clinic === id) notice(WAKING); }, SLOW_MS);
  try {
    const story = await loadStory(id);
    if (state.clinic === id) renderStory(view, story, handlers());
  } catch (error) {
    if (state.clinic === id) notice(`Couldn't load ${cityOf(id)}: ${error.message}`, () => show(id));
  } finally {
    clearTimeout(slow);
    if (state.clinic === id) view.classList.remove("loading");
  }
}

function route() {
  const id = decodeURIComponent(location.hash.replace(/^#/, ""));
  show(state.network.clinics.some((c) => c.id === id) ? id : null);
}

function pick(id) {
  location.hash = id ? `#${id}` : "";
}

async function prefetch() {
  // Load the flagged clinics' stories in the background, so clicking one is instant.
  const flagged = state.network.clinics.filter((c) => c.flagged).sort((a, b) => b.at_stake - a.at_stake);
  for (const c of flagged) await loadStory(c.id).catch(() => {});
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
  document.getElementById("rail-title").innerHTML = `<b>${n.flagged_count} of ${n.clinic_count}</b> clinics out of alignment`;
  state.spine = renderSpine(document.getElementById("spine"), n.clinics, pick);
  window.addEventListener("hashchange", route);
  route();
  prefetch();
}

boot();
