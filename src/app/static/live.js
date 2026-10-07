// The live run panel: a five-step strip that lights up as the Director works, and each step in
// plain English as it happens. It long-polls the server, which works behind the Apps proxy.
import { get, post } from "./api.js";
import { duration, esc, plural } from "./format.js";

const PHASES = [["observe", "Observe"], ["reason", "Reason"], ["decide", "Decide"], ["act", "Act"], ["measure", "Measure"]];
const RETRY_MS = 2000;

export async function startRun(panel, clinic, patients, options) {
  open(panel, `Starting the Director on ${options.cityOf(clinic)}`);
  try {
    const { run_id: runId } = await post("/api/runs", { clinic, patients });
    follow(panel, runId, clinic, options);
  } catch (error) {
    if (error.status === 409 && error.body?.run_id) follow(panel, error.body.run_id, error.body.clinic, options);
    else fail(panel, error.message, options);
  }
}

export function follow(panel, runId, clinic, options) {
  open(panel, `The Director is investigating ${options.cityOf(clinic)}`);
  options.onStart?.(runId);
  const started = Date.now();
  const elapsed = panel.querySelector(".elapsed");
  const feed = panel.querySelector(".feed");
  const tick = () => { elapsed.textContent = duration((Date.now() - started) / 1000); };
  tick();
  const timer = setInterval(tick, 1000);

  const setPhase = (phase) => {
    const current = PHASES.findIndex(([key]) => key === phase);
    panel.querySelectorAll(".segment").forEach((segment, i) => {
      segment.classList.toggle("done", i < current);
      segment.classList.toggle("active", i === current);
    });
  };
  const addStep = (event) => {
    const item = document.createElement("li");
    item.className = event.write ? "feed-item write" : "feed-item";
    item.innerHTML = `<span class="who">${esc(event.agent)}</span><span class="what">${esc(event.text)}</span>`;
    feed.append(item);
    feed.scrollTop = feed.scrollHeight;
    if (event.progress) panel.querySelector('[data-phase="act"] .detail').textContent = event.progress;
  };
  const done = (event) => {
    clearInterval(timer);
    panel.querySelectorAll(".segment").forEach((s) => { s.classList.remove("active"); s.classList.add("done"); });
    const limit = event.status === "SUCCEEDED" ? "" : " The Director stopped at its step limit.";
    const summary = `Done in ${duration(event.seconds)}. ${plural(event.drafts, "outreach draft")} queued for ${options.cityOf(event.clinic)}.${limit}`;
    setTimeout(() => collapse(panel, summary), 1200); // let the last segment be seen filling
    options.onDone(event);
  };

  (async () => {
    let after = 0;
    for (;;) {
      let body;
      try {
        body = await get(`/api/runs/${encodeURIComponent(runId)}/events?after=${after}`);
      } catch (error) {
        if (error.status === 404) {
          clearInterval(timer);
          fail(panel, error.message, options);
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, RETRY_MS)); // a network blip: keep following
        continue;
      }
      for (const event of body.events) {
        after = event.seq + 1;
        if (event.type === "phase") setPhase(event.phase);
        else if (event.type === "step") addStep(event);
        else if (event.type === "done") return done(event);
        else if (event.type === "error") {
          clearInterval(timer);
          return fail(panel, event.message, options);
        }
      }
    }
  })();
}

function open(panel, title) {
  panel.hidden = false;
  panel.className = "live";
  panel.innerHTML = `<div class="live-head"><h2>${esc(title)}</h2><span class="elapsed"></span></div>
    <ol class="strip">${PHASES.map(([key, label]) => `<li class="segment" data-phase="${key}"><span class="name">${label}</span><span class="detail"></span></li>`).join("")}</ol>
    <ol class="feed" aria-live="polite"></ol>`;
}

function collapse(panel, summary) {
  panel.classList.add("collapsed");
  const head = panel.querySelector(".live-head");
  head.innerHTML = `<p class="live-summary">${esc(summary)}</p><button type="button" class="link">Show steps</button>`;
  const toggle = head.querySelector("button");
  toggle.addEventListener("click", () => {
    const expanded = panel.classList.toggle("expanded");
    toggle.textContent = expanded ? "Hide steps" : "Show steps";
  });
}

function fail(panel, message, options) {
  options.onFail?.();
  panel.hidden = false;
  panel.classList.add("failed");
  panel.querySelector(".live-error")?.remove();
  const box = document.createElement("div");
  box.className = "live-error";
  box.innerHTML = `<p>The run stopped: ${esc(message)}</p>
    <p><button type="button" class="link" data-retry>Try again</button> <button type="button" class="link" data-close>Close</button></p>`;
  panel.append(box);
  box.querySelector("[data-retry]").addEventListener("click", () => options.retry());
  box.querySelector("[data-close]").addEventListener("click", () => { panel.hidden = true; });
}
