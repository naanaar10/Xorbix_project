// How it works: the agent's loop in five lines, the model, the MLflow traces, which run the
// story shows, and every step of that run.
import { get } from "./api.js";
import { esc, plural, runKind, when } from "./format.js";

const LOOP = [
  ["Observe", "Looks at every clinic: bookings, lead replies, finished care plans. Works out how much money each problem costs a year."],
  ["Reason", "The Director agent picks the clinics losing the most and digs into their data with its tools (17 in all) until it finds the cause."],
  ["Decide", "It writes down what's wrong and passes the clinic to the right specialist agent: retention, leads or capacity. Then the marketing and loyalty specialists look at the whole network."],
  ["Act", "Each specialist looks at each patient, lead or marketing channel and writes a message or a budget move for staff to approve."],
  ["Measure", "Patients are split into groups at random first, so we can compare the agent's messages with a plain reminder and with no message."],
];

export function openDrawer(dialog, options) {
  const body = dialog.querySelector("#drawer-body");
  if (options.error) {
    body.innerHTML = `<p class="notice error">Couldn't load the run details: ${esc(options.error)}</p>`;
    dialog.showModal();
    return;
  }
  const { meta, runId, shownRunId, onPickRun } = options;
  const runs = [`<option value="">Latest run for each clinic</option>`,
    ...meta.runs.map((r) => `<option value="${esc(r.run_id)}"${r.run_id === runId ? " selected" : ""}>${esc(runLabel(r))}</option>`)].join("");
  const traces = meta.mlflow_url
    ? `<a href="${esc(meta.mlflow_url)}" target="_blank" rel="noopener">Every step the AI took, in MLflow</a>`
    : "Not set up in this workspace";
  body.innerHTML = `<ol class="loop">${LOOP.map(([name, text]) => `<li><b>${name}.</b> ${esc(text)}</li>`).join("")}</ol>
    <dl class="facts">
      <dt>Model</dt><dd>${esc(meta.model)}, served by Databricks</dd>
      <dt>Traces</dt><dd>${traces}</dd>
      <dt><label for="run-picker">Run shown</label></dt><dd><select id="run-picker">${runs}</select></dd>
    </dl>
    <h3>Every step of ${shownRunId ? "the run shown" : "the latest run"}</h3>
    <ol class="log" id="log"><li class="note">Loading steps…</li></ol>`;
  body.querySelector("#run-picker").addEventListener("change", (e) => {
    dialog.close();
    onPickRun(e.target.value);
  });
  dialog.showModal();
  const logRun = shownRunId || meta.runs[0]?.run_id;
  const log = body.querySelector("#log");
  if (logRun) loadLog(log, logRun);
  else log.innerHTML = '<li class="note">No runs yet.</li>';
}

function runLabel(r) {
  const status = r.status === "SUCCEEDED" ? "" : `, ${String(r.status).toLowerCase().replaceAll("_", " ")}`;
  return `${when(r.started_at)}, ${runKind(r.trigger)}, ${plural(r.clinics_investigated ?? 0, "clinic")}${status}`;
}

async function loadLog(list, runId) {
  try {
    const { steps } = await get(`/api/runs/${encodeURIComponent(runId)}/steps`);
    list.innerHTML = steps.map((s) => `<li class="${s.write ? "write" : ""}"><span class="who">${esc(s.agent)}</span><span class="what">${esc(s.text)}</span></li>`).join("")
      || '<li class="note">This run recorded no steps.</li>';
  } catch (error) {
    list.innerHTML = `<li class="note">Couldn't load the steps: ${esc(error.message)}</li>`;
  }
}
