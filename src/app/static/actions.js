// Outreach drafts: approve or skip each one; click a message to edit it (the edit is saved when the
// draft is approved). Used by the clinic story's cards and by the Outreach tab's table: any element
// with class "item", data-id and data-status, holding a .message, a .decide and a .card-error.
import { post } from "./api.js";
import { esc, plural, slotLabel } from "./format.js";

const FIRST_CARDS = 6;

export function renderActions(step, story, handlers) {
  const { actions, controls } = story;
  const held = controls.holdout ?? 0;
  const generic = controls.generic ?? 0;
  step.innerHTML = `<h3><span class="n">3</span>What we're doing</h3>
    <div class="act-head">
      <p>${plural(actions.length, "outreach draft")} <span>for staff to approve</span></p>
      <button type="button" class="quiet" id="approve-all" hidden></button>
    </div>
    ${held || generic ? `<p class="note">${held} kept as a holdout, ${generic} got a generic reminder, picked at random so the agent's impact can be measured.</p>` : ""}
    <div class="cards">${actions.map((a, i) => card(a, i >= FIRST_CARDS)).join("")}</div>
    ${actions.length > FIRST_CARDS ? `<p class="more"><button type="button" class="link" id="show-all">Show all ${actions.length}</button></p>` : ""}
    ${actions.length ? "" : `<p class="note">The specialist didn't draft any outreach in this run.</p>`}
    <p class="act-error" role="alert" hidden></p>`;
  step.querySelector("#show-all")?.addEventListener("click", (e) => {
    step.querySelectorAll(".card[hidden]").forEach((c) => { c.hidden = false; });
    e.target.closest(".more").remove();
  });
  wireDecisions(step, () => ({ run_id: story.run.run_id, location_id: story.clinic.id }), handlers);
}

function card(a, hidden) {
  const who = `${a.target_type === "lead" ? "Lead" : "Patient"} ${a.target_id}${a.offered_slot ? `, ${slotLabel(a.offered_slot)}` : ""}`;
  return `<article class="card item" data-id="${esc(a.action_id)}" data-status="${esc(a.status)}"${hidden ? " hidden" : ""}>
    <p class="what">${esc(a.intervention)}<span>${esc(a.channel ?? "")}</span></p>
    <p class="who">${esc(who)}</p>
    <p class="message" tabindex="0" title="Click to edit">${esc(a.message ?? "")}</p>
    ${a.rationale ? `<details><summary>Why this outreach</summary><p>${esc(a.rationale)}</p></details>` : ""}
    <div class="decide">${decision(a.status)}</div>
    <p class="card-error" role="alert" hidden></p>
  </article>`;
}

export function decision(status) {
  if (status === "Approved") return '<span class="state approved">Approved</span><button type="button" class="link" data-set="Pending">Undo</button>';
  if (status === "Rejected") return '<span class="state skipped">Skipped</span><button type="button" class="link" data-set="Pending">Undo</button>';
  return '<button type="button" class="approve" data-set="Approved">Approve</button><button type="button" class="link" data-set="Rejected">Skip</button>';
}

// `scope()` names what "Approve all" covers: { run_id, location_id } (location_id null = whole run).
// Items with class "filtered-out" are not shown and are left alone by Approve all.
export function wireDecisions(root, scope, handlers) {
  updateApproveAll(root);
  root.addEventListener("click", (e) => {
    const target = e.target;
    if (target.id === "approve-all") approveAll(root, scope(), handlers);
    else if (target.classList.contains("message")) edit(target.closest(".item"));
    else if (target.dataset.set) decide(target.closest(".item"), target.dataset.set, root, handlers);
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.classList.contains("message")) {
      e.preventDefault();
      edit(e.target.closest(".item"));
    }
  });
}

function edit(item) {
  if (!item || item.dataset.status !== "Pending") return;
  const text = item.querySelector(".message");
  const box = document.createElement("textarea");
  box.value = text.textContent;
  box.dataset.original = text.textContent;
  box.maxLength = 600;
  box.setAttribute("aria-label", "Message to send");
  text.replaceWith(box);
  box.focus();
}

// Each save is an UPDATE on the warehouse that takes a few seconds, so the item changes at once
// and saves happen in the background, one at a time and in order (they all touch one table).
// A failed save puts the item back and says why.
let saving = Promise.resolve();
function enqueue(work) {
  const run = saving.then(work, work);
  saving = run.catch(() => {});
  return run;
}

const send = (item, body) => post(`/api/actions/${encodeURIComponent(item.dataset.id)}`, body);

function paint(item, status, message) {
  item.dataset.status = status;
  const box = item.querySelector("textarea");
  if (box) {
    const text = document.createElement("p");
    text.className = "message";
    text.tabIndex = 0;
    text.title = "Click to edit";
    text.textContent = message ?? box.dataset.original;
    box.replaceWith(text);
  }
  item.querySelector(".decide").innerHTML = decision(status);
}

function decide(item, status, root, handlers) {
  const error = item.querySelector(".card-error");
  const box = item.querySelector("textarea");
  const before = item.dataset.status;
  const original = box ? box.dataset.original : item.querySelector(".message").textContent;
  if (box && status === "Approved" && !box.value.trim()) {
    error.textContent = "Write a message before approving, or skip this one.";
    error.hidden = false;
    return;
  }
  const body = box && status === "Approved" ? { status, message: box.value } : { status };
  paint(item, status, body.message);
  error.hidden = true;
  handlers.onDecided?.(item.dataset.id, status, body.message);
  updateApproveAll(root);
  enqueue(() => send(item, body)).catch((err) => {
    paint(item, before);
    item.querySelector(".message").textContent = original;
    handlers.onDecided?.(item.dataset.id, before, original);
    error.textContent = `Couldn't save: ${err.message}`;
    error.hidden = false;
    updateApproveAll(root);
  });
}

const pendingItems = (root) => [...root.querySelectorAll('.item[data-status="Pending"]:not(.filtered-out)')];

function approveAll(root, scope, handlers) {
  const error = root.querySelector(".act-error");
  const items = pendingItems(root);
  const original = new Map(items.map((i) => [i, i.querySelector("textarea")?.dataset.original ?? i.querySelector(".message").textContent]));
  // Edited messages are saved one by one first, so no edit is lost; then the rest in one call.
  // A message emptied in the text box counts as not edited.
  const edited = new Map(items.filter((i) => i.querySelector("textarea")?.value.trim())
    .map((i) => [i, i.querySelector("textarea").value]));
  for (const item of items) {
    paint(item, "Approved", edited.get(item));
    handlers.onDecided?.(item.dataset.id, "Approved", edited.get(item));
  }
  error.hidden = true;
  updateApproveAll(root);
  const saved = new Set();
  enqueue(async () => {
    for (const [item, message] of edited) {
      await send(item, { status: "Approved", message });
      saved.add(item);
    }
    await post("/api/actions/approve-all", scope);
  }).catch((err) => {
    for (const item of items) {
      if (saved.has(item)) continue; // its own save went through: approved, with its edit
      paint(item, "Pending");
      item.querySelector(".message").textContent = original.get(item);
      handlers.onDecided?.(item.dataset.id, "Pending", original.get(item));
    }
    error.textContent = `Couldn't approve them all: ${err.message}`;
    error.hidden = false;
    updateApproveAll(root);
  });
}

export function updateApproveAll(root) {
  const button = root.querySelector("#approve-all");
  if (!button) return;
  const pending = pendingItems(root).length;
  button.hidden = pending < 2;
  button.textContent = `Approve all ${pending}`;
}
