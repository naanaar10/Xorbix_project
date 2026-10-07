// Step 3: the specialist's outreach drafts. Approve or skip each one; click a message to edit it
// (the edit is saved when the card is approved). Control groups are summed up in one line.
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
  updateApproveAll(step);
  step.addEventListener("click", (e) => onClick(e, step, story, handlers));
  step.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.classList.contains("message")) {
      e.preventDefault();
      edit(e.target.closest(".card"));
    }
  });
}

function card(a, hidden) {
  const who = `${a.target_type === "lead" ? "Lead" : "Patient"} ${a.target_id}${a.offered_slot ? `, ${slotLabel(a.offered_slot)}` : ""}`;
  return `<article class="card" data-id="${esc(a.action_id)}" data-status="${esc(a.status)}"${hidden ? " hidden" : ""}>
    <p class="what">${esc(a.intervention)}<span>${esc(a.channel ?? "")}</span></p>
    <p class="who">${esc(who)}</p>
    <p class="message" tabindex="0" title="Click to edit">${esc(a.message ?? "")}</p>
    ${a.rationale ? `<details><summary>Why this outreach</summary><p>${esc(a.rationale)}</p></details>` : ""}
    <div class="decide">${decision(a.status)}</div>
    <p class="card-error" role="alert" hidden></p>
  </article>`;
}

function decision(status) {
  if (status === "Approved") return '<span class="state approved">Approved</span><button type="button" class="link" data-set="Pending">Undo</button>';
  if (status === "Rejected") return '<span class="state skipped">Skipped</span><button type="button" class="link" data-set="Pending">Undo</button>';
  return '<button type="button" class="approve" data-set="Approved">Approve</button><button type="button" class="link" data-set="Rejected">Skip</button>';
}

function onClick(e, step, story, handlers) {
  const target = e.target;
  if (target.id === "show-all") {
    step.querySelectorAll(".card[hidden]").forEach((c) => { c.hidden = false; });
    target.closest(".more").remove();
  } else if (target.id === "approve-all") {
    approveAll(step, story, handlers);
  } else if (target.classList.contains("message")) {
    edit(target.closest(".card"));
  } else if (target.dataset.set) {
    decide(target.closest(".card"), target.dataset.set, step, handlers);
  }
}

function edit(card) {
  if (!card || card.dataset.status !== "Pending") return;
  const text = card.querySelector(".message");
  const box = document.createElement("textarea");
  box.value = text.textContent;
  box.dataset.original = text.textContent;
  box.maxLength = 600;
  box.setAttribute("aria-label", "Message to send");
  text.replaceWith(box);
  box.focus();
}

// Each save is an UPDATE on the warehouse that takes a few seconds, so the card changes at once
// and saves happen in the background, one at a time and in order (they all touch one table).
// A failed save puts the card back and says why.
let saving = Promise.resolve();
function enqueue(work) {
  const run = saving.then(work, work);
  saving = run.catch(() => {});
  return run;
}

const send = (card, body) => post(`/api/actions/${encodeURIComponent(card.dataset.id)}`, body);

function paint(card, status, message) {
  card.dataset.status = status;
  const box = card.querySelector("textarea");
  if (box) {
    const text = document.createElement("p");
    text.className = "message";
    text.tabIndex = 0;
    text.title = "Click to edit";
    text.textContent = message ?? box.dataset.original;
    box.replaceWith(text);
  }
  card.querySelector(".decide").innerHTML = decision(status);
}

function decide(card, status, step, handlers) {
  const error = card.querySelector(".card-error");
  const box = card.querySelector("textarea");
  const before = card.dataset.status;
  const original = box ? box.dataset.original : card.querySelector(".message").textContent;
  if (box && status === "Approved" && !box.value.trim()) {
    error.textContent = "Write a message before approving, or skip this one.";
    error.hidden = false;
    return;
  }
  const body = box && status === "Approved" ? { status, message: box.value } : { status };
  paint(card, status, body.message);
  error.hidden = true;
  handlers.onDecided?.(card.dataset.id, status, body.message);
  updateApproveAll(step);
  enqueue(() => send(card, body)).catch((err) => {
    paint(card, before);
    card.querySelector(".message").textContent = original;
    handlers.onDecided?.(card.dataset.id, before, original);
    error.textContent = `Couldn't save: ${err.message}`;
    error.hidden = false;
    updateApproveAll(step);
  });
}

function approveAll(step, story, handlers) {
  const error = step.querySelector(".act-error");
  const cards = [...step.querySelectorAll('.card[data-status="Pending"]')];
  const original = new Map(cards.map((c) => [c, c.querySelector("textarea")?.dataset.original ?? c.querySelector(".message").textContent]));
  // Edited messages are saved one by one first, so no edit is lost; then the rest in one call.
  // A message emptied in the text box counts as not edited.
  const edited = new Map(cards.filter((c) => c.querySelector("textarea")?.value.trim())
    .map((c) => [c, c.querySelector("textarea").value]));
  for (const card of cards) {
    paint(card, "Approved", edited.get(card));
    handlers.onDecided?.(card.dataset.id, "Approved", edited.get(card));
  }
  error.hidden = true;
  updateApproveAll(step);
  const saved = new Set();
  enqueue(async () => {
    for (const [card, message] of edited) {
      await send(card, { status: "Approved", message });
      saved.add(card);
    }
    await post("/api/actions/approve-all", { run_id: story.run.run_id, location_id: story.clinic.id });
  }).catch((err) => {
    for (const card of cards) {
      if (saved.has(card)) continue; // its own save went through: approved, with its edit
      paint(card, "Pending");
      card.querySelector(".message").textContent = original.get(card);
      handlers.onDecided?.(card.dataset.id, "Pending", original.get(card));
    }
    error.textContent = `Couldn't approve them all: ${err.message}`;
    error.hidden = false;
    updateApproveAll(step);
  });
}

function updateApproveAll(step) {
  const button = step.querySelector("#approve-all");
  const pending = step.querySelectorAll('.card[data-status="Pending"]').length;
  button.hidden = pending < 2;
  button.textContent = `Approve all ${pending}`;
}
