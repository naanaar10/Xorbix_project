// Formatting helpers for every view. No DOM here, so they're unit-tested with node --test.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

export function money(value) {
  const n = Number(value) || 0;
  const x = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (x >= 1e8) return `${sign}$${Math.round(x / 1e6)}M`;
  if (x >= 999_500) return `${sign}$${(x / 1e6).toFixed(1)}M`;
  if (x >= 1e3) return `${sign}$${Math.round(x / 1e3)}K`;
  return `${sign}$${Math.round(x)}`;
}

export const pct = (value) => `${Math.round((Number(value) || 0) * 100)}%`;

export const plural = (count, word, many = `${word}s`) => `${count} ${count === 1 ? word : many}`;

export function duration(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function kpiValue(value, unit) {
  const x = Number(value) || 0;
  if (unit === "pct") return pct(x);
  if (unit === "hours") return `${x < 10 ? x.toFixed(1) : Math.round(x)} hours`;
  return String(Math.round(x));
}

// Bar length and median tick as percentages of the track: rates on 0-100%, counts and hours
// against a quarter more than the larger of the two.
export function kpiScale(kpi) {
  const value = Number(kpi.value) || 0;
  const median = Number(kpi.median) || 0;
  const top = kpi.unit === "pct" ? 1 : Math.max(value, median) * 1.25 || 1;
  const share = (x) => Math.max(0, Math.min(100, (x / top) * 100));
  return { value: share(value), median: share(median) };
}

export const isWorse = (kpi) => (kpi.better === "lower" ? kpi.value > kpi.median : kpi.value < kpi.median);

const PROBLEMS = {
  retention: "patients stop coming back",
  leads: "leads wait too long for a reply",
  capacity: "chairs sit empty",
  marketing: "marketing money goes where it wins the fewest patients",
  loyalty: "patients who finish care aren't asked to stay or bring a friend",
};
export const leverProblem = (lever) => PROBLEMS[lever] ?? "revenue is leaking";

export const runKind = (trigger) => (trigger === "app" ? "live run" : "nightly run");

const CHICAGO = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
export function when(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : CHICAGO.format(date).replace(/ /g, " ");
}

const DAY = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" });
// What the agent knew about the person it wrote to (worked out from the data on the server).
export function factsHtml(facts) {
  if (!facts?.length) return "";
  return `<ul class="known" aria-label="What we know about them">${facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`;
}

export function slotLabel(slot) {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(.*)$/.exec(slot ?? "");
  if (!m) return slot ?? "";
  const [, y, mo, d, h, mi, rest] = m;
  const day = DAY.format(new Date(Date.UTC(+y, +mo - 1, +d)));
  return `${day}, ${+h % 12 || 12}:${mi} ${+h < 12 ? "AM" : "PM"}${rest}`;
}

// Bold every figure in already-escaped text ("36", "66%", "$645,118", "$3.2 M") so the numbers are
// easy to spot. Digits inside ids (PRV0041) and escapes (&#39;) are left alone.
export const boldNumbers = (html) =>
  String(html ?? "").replace(/(?<![A-Za-z0-9.#&$])\$?\d+(?:[,.]\d+)*(?:%|[ \u202f]?[MK]\b)?/g, "<b>$&</b>");

// The agent writes its evidence as facts separated by semicolons; show up to three.
export const proofItems = (evidence) =>
  String(evidence ?? "").split(";").map((f) => f.trim()).filter(Boolean).slice(0, 3);

// The Manager sometimes writes Markdown. Everything is escaped first; then only **bold**, *italics*
// and "- " bullets become markup. A line that is only bold text is a heading and is dropped.
export function agentHtml(text) {
  const out = [];
  let list = [];
  const flush = () => {
    if (list.length) out.push(`<ul>${list.map((item) => `<li>${item}</li>`).join("")}</ul>`);
    list = [];
  };
  for (const raw of String(text ?? "").split("\n")) {
    const line = esc(raw.trim()).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*\w])\*(\S[^*]*?)\*(?!\*)/g, "$1<i>$2</i>");
    if (!line || /^<b>[^<]*<\/b>:?$/.test(line)) {
      flush();
    } else if (/^[-*•] /.test(line)) {
      list.push(line.slice(2).trim());
    } else {
      flush();
      out.push(`<p>${line}</p>`);
    }
  }
  flush();
  return out.join("");
}
