// What-if planner: the path to the goal, recomputed in the browser as sliders move. Same formulas
// as BRIDGE_SQL and explain.py on the server; at the default settings it lands on exactly the
// server's numbers (tests/js/whatif.test.mjs). No DOM here; renderWhatIf in empty.js draws it.
import { money, pct } from "./format.js";

const n = (x) => Number(x) || 0;
const share = (x) => `${Math.round(x * 100)}%`;

// One slider per step on the path: key, plain label, range, default, how to show a value, and
// what that setting is worth a year.
export function levers(i) {
  const bookedNow = n(i.pm_capacity) ? n(i.pm_booked) / n(i.pm_capacity) : 0;
  const costlyCpp = n(i.costly_new_patients) ? n(i.costly_spend) / n(i.costly_new_patients) : 0;
  const cheapCpp = n(i.cheap_new_patients) ? n(i.cheap_spend) / n(i.cheap_new_patients) : 0;
  return [
    { key: "leads", label: "Leads that hear back within an hour", min: 0, max: 1, step: 0.05, start: 1, show: share,
      worth: (s) => s * n(i.leads_per_year) * Math.max(0, n(i.conversion_within_hour) - n(i.conversion)) * n(i.revenue_per_patient) },
    { key: "capacity", label: "Afternoons booked", min: Math.floor(bookedNow * 100) / 100, max: 0.95, step: 0.01, start: 0.85, show: share,
      worth: (s) => Math.max(0, s * n(i.pm_capacity) - n(i.pm_booked)) * n(i.visit_revenue) },
    { key: "retention", label: "Plan completion at every clinic", min: Math.floor(n(i.median_completion) * 100) / 100, max: 0.7,
      step: 0.005, start: n(i.top_decile_completion), show: pct,
      worth: (s) => n(i.closed_plans) * Math.max(0, s - n(i.median_completion)) * n(i.completion_value) },
    { key: "marketing", label: "Marketing money moved to the cheapest channel", min: 0,
      max: Math.min(0.25 * n(i.costly_spend), n(i.cheap_spend)), step: 5000, start: n(i.marketing_moved), show: money,
      worth: (m) => (costlyCpp && cheapCpp ? Math.max(0, m / (2 * cheapCpp) - m / costlyCpp) * n(i.revenue_per_patient) : 0) },
    { key: "membership", label: "How close clinics get to the best 10% on Wellness plans", min: 0, max: 1, step: 0.05, start: 1, show: share,
      worth: (s) => s * n(i.extra_wellness_plans) * n(i.wellness_visits) * n(i.visit_revenue) },
    { key: "referrals", label: "How close clinics get to the best 10% on referrals", min: 0, max: 1, step: 0.05, start: 1, show: share,
      worth: (s) => s * n(i.extra_referrers) * n(i.referrals_per_referrer) * n(i.referral_conversion) * n(i.revenue_per_patient) },
  ];
}

export const defaults = (inputs) => Object.fromEntries(levers(inputs).map((l) => [l.key, l.start]));

export function plan(inputs, settings, revenue, clinicCount, goal) {
  const values = Object.fromEntries(levers(inputs).map((l) => [l.key, l.worth(settings[l.key] ?? l.start)]));
  const fixes = Object.values(values).reduce((a, b) => a + b, 0);
  const remainder = Math.max(0, goal - revenue - fixes);
  const perClinic = clinicCount ? revenue / clinicCount : 0;
  return { values, fixes, remainder, newClinics: perClinic ? Math.ceil(remainder / perClinic) : 0 };
}
