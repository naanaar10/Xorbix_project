// Clinics tab: all 50 clinics in one sortable table, with the network median as the first row.
// The clinics out of alignment are marked; clicking a row opens that clinic's story.
import { esc, money, pct } from "./format.js";

const PROBLEM = { retention: "Patients quit their care plan", leads: "Slow lead replies", capacity: "Empty chairs" };

const hours = (x) => (x == null ? "" : Number(x).toFixed(1));
const count = (x) => (x == null ? "" : String(Math.round(x)));
const rate = (x) => (x == null ? "" : pct(x));

// key, header, format, which way is better (sets the first sort direction)
const COLUMNS = [
  ["at_stake", "Lost / yr", money, "lower"],
  ["revenue", "Revenue / yr", money, "higher"],
  ["completion", "Plan completion", rate, "higher"],
  ["conversion", "Lead conversion", rate, "higher"],
  ["reply_hours", "Hours to reply", hours, "lower"],
  ["no_shows", "No-shows", rate, "lower"],
  ["afternoons", "Afternoons booked", rate, "higher"],
  ["quiet", "Going quiet", count, "lower"],
];

const sort = { key: "at_stake", descending: true };

export function renderClinics(view, network, onOpen) {
  const header = COLUMNS.map(([key, label]) => {
    const sorted = sort.key === key ? (sort.descending ? "descending" : "ascending") : "none";
    return `<th scope="col" class="num" aria-sort="${sorted}"><button type="button" class="sort" data-key="${key}">${esc(label)}</button></th>`;
  }).join("");
  const clinics = [...network.clinics].sort((a, b) => {
    const diff = (a[sort.key] ?? 0) - (b[sort.key] ?? 0);
    return sort.descending ? -diff : diff;
  });
  const median = `<tr class="median-row"><th scope="row">Typical clinic <span class="id">median</span></th><td></td>${COLUMNS.map(([key, , format]) =>
    `<td class="num">${network.medians[key] == null ? "" : format(network.medians[key])}</td>`).join("")}</tr>`;
  const rows = clinics.map((c) => `<tr class="row${c.flagged ? " flagged" : ""}" data-id="${esc(c.id)}" tabindex="0">
      <th scope="row"><b>${esc(c.city)}</b> <span class="id">${esc(c.id)}</span></th>
      <td class="lever">${c.flagged ? esc(PROBLEM[c.lever] ?? c.lever) : ""}</td>
      ${COLUMNS.map(([key, , format]) => `<td class="num${key === "at_stake" && c.flagged ? " at-stake" : ""}">${format(c[key])}</td>`).join("")}
    </tr>`).join("");
  view.innerHTML = `<section class="fade-in">
    <header class="tab-head"><h2>Clinics</h2><p class="source">${network.clinic_count} clinics. ${network.flagged_count} lose more than ${money(network.flag_above)} a year. Click a column to sort, or a clinic to see its story.</p></header>
    <div class="table-scroll"><table class="table clinics">
      <thead><tr><th scope="col">Clinic</th><th scope="col">Problem</th>${header}</tr></thead>
      <tbody>${median}${rows}</tbody>
    </table></div>
    <p class="note">Lost / yr: money a clinic loses each year where it does worse than the typical clinic (small differences are ignored). Open a clinic to see the math.</p>
  </section>`;
  view.querySelectorAll(".sort").forEach((button) => button.addEventListener("click", () => {
    const [key, , , better] = COLUMNS.find(([k]) => k === button.dataset.key);
    sort.descending = sort.key === key ? !sort.descending : better === "lower";
    sort.key = key;
    renderClinics(view, network, onOpen);
  }));
  view.querySelectorAll("tr.row").forEach((tr) => {
    tr.addEventListener("click", () => onOpen(tr.dataset.id));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onOpen(tr.dataset.id); });
  });
}
