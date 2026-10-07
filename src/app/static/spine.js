// The network as a spine: one vertebra per clinic, top to bottom. Clinics with revenue at stake
// slide out of line by the square root of their dollars, so the problems show before any number.
import { esc, money } from "./format.js";
import { reducedMotion } from "./motion.js";

const MAX_SHIFT = 56; // px, for the clinic with the most at stake
const STAGGER = 15;   // ms between vertebrae on load

export function renderSpine(root, clinics, onSelect) {
  const top = Math.max(1, ...clinics.filter((c) => c.flagged).map((c) => c.at_stake));
  root.innerHTML = clinics.map((c, i) => {
    const shift = c.flagged ? Math.round(MAX_SHIFT * Math.sqrt(c.at_stake / top)) : 0;
    const tip = `${c.id} ${c.city}, ${money(c.at_stake)} a year at stake`;
    const tag = c.flagged ? `<span class="tag"><b>${esc(c.id)}</b> ${esc(c.city)}</span>` : "";
    return `<button type="button" class="vertebra${c.flagged ? " flagged" : ""}" data-id="${esc(c.id)}" data-tip="${esc(tip)}" aria-label="${esc(tip)}" tabindex="-1" style="--i:${i};--shift:${shift}px"><span class="body"></span>${tag}</button>`;
  }).join("");
  const buttons = [...root.querySelectorAll(".vertebra")];

  root.addEventListener("click", (e) => {
    const button = e.target.closest(".vertebra");
    if (button) onSelect(button.dataset.id);
  });
  root.addEventListener("keydown", (e) => {
    const i = buttons.indexOf(document.activeElement);
    const next = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: buttons.length - 1 }[e.key];
    if (i < 0 || next === undefined) return;
    e.preventDefault();
    const j = Math.max(0, Math.min(buttons.length - 1, next));
    buttons.forEach((b, k) => { b.tabIndex = k === j ? 0 : -1; });
    buttons[j].focus();
  });

  const tip = tooltip(root);
  root.addEventListener("pointerover", (e) => tip.show(e.target.closest(".vertebra")));
  root.addEventListener("pointerleave", tip.hide);
  root.addEventListener("focusin", (e) => tip.show(e.target.closest(".vertebra")));
  root.addEventListener("focusout", tip.hide);

  // Load: vertebrae fade in top to bottom, then the flagged ones slide out of line together.
  const settle = () => root.classList.add("settled");
  if (reducedMotion()) settle();
  else setTimeout(settle, clinics.length * STAGGER + 350);

  function select(id) {
    buttons.forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));
    const current = buttons.find((b) => b.dataset.id === id)
      ?? buttons.find((b) => b.classList.contains("flagged")) ?? buttons[0];
    buttons.forEach((b) => { b.tabIndex = b === current ? 0 : -1; });
  }
  select(null);
  return { select };
}

function tooltip(root) {
  const el = document.createElement("div");
  el.className = "tip";
  el.setAttribute("role", "tooltip");
  el.hidden = true;
  document.body.append(el);
  const rail = root.closest(".rail") ?? root;
  return {
    show(button) {
      if (!button) return;
      const r = button.getBoundingClientRect();
      el.textContent = button.dataset.tip;
      el.style.top = `${r.top + r.height / 2}px`;
      el.style.left = `${window.innerWidth > 900 ? rail.getBoundingClientRect().right + 10 : 150}px`;
      el.hidden = false;
    },
    hide() {
      el.hidden = true;
    },
  };
}
