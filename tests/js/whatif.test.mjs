import assert from "node:assert/strict";
import { test } from "node:test";
import { defaults, levers, plan } from "../../src/app/static/whatif.js";

// The bridge row the server returns (dev data), with the values it computed.
const INPUTS = {
  leads_per_year: 282195.1194029851, conversion: 0.28789850232238484, conversion_within_hour: 0.38118321420989315,
  completion_value: 1911.5365056926555, revenue_per_patient: 1128.13060220889, visit_revenue: 110.87444698630249,
  closed_plans: 78052, median_completion: 0.5089903181189488, top_decile_completion: 0.5520594965675057,
  pm_capacity: 626400, pm_booked: 462728, costly_spend: 5544594.22, costly_new_patients: 16846,
  cheap_spend: 645118.22, cheap_new_patients: 9536, marketing_moved: 645118.22,
  extra_wellness_plans: 1598.5440613026822, wellness_visits: 12, extra_referrers: 917.9799732977301,
  referrals_per_referrer: 1.5865735597524202, referral_conversion: 0.37349751955920707,
  leads_value: 29697463.218588624, capacity_value: 7729279.448309119, retention_value: 6425889.008176902,
  marketing_value: 3167738.3567364146, membership_value: 2126852.265362075, referrals_value: 613677.9534702854,
};

test("the default plan is exactly the path to the goal the server worked out", () => {
  const p = plan(INPUTS, defaults(INPUTS), 102.4e6, 50, 250e6);
  for (const key of ["leads", "capacity", "retention", "marketing", "membership", "referrals"]) {
    assert.ok(Math.abs(p.values[key] - INPUTS[`${key}_value`]) < 1, `${key}: ${p.values[key]}`);
  }
  assert.equal(p.newClinics, 48);
});

test("moving a slider changes only its own step, and fewer fixes need more clinics", () => {
  const settings = { ...defaults(INPUTS), leads: 0.5, capacity: 0.7387 };
  const p = plan(INPUTS, settings, 102.4e6, 50, 250e6);
  assert.ok(Math.abs(p.values.leads - INPUTS.leads_value / 2) < 1);
  assert.equal(p.values.capacity, 0); // 73.87% is what is booked today: no extra visits
  assert.ok(Math.abs(p.values.retention - INPUTS.retention_value) < 1);
  assert.ok(p.newClinics > 48);
});

test("every slider has plain words and a sensible range", () => {
  for (const l of levers(INPUTS)) {
    assert.ok(l.label && l.min < l.max && l.step > 0, l.key);
    assert.ok(defaults(INPUTS)[l.key] >= l.min && defaults(INPUTS)[l.key] <= l.max, l.key);
    assert.equal(typeof l.show(defaults(INPUTS)[l.key]), "string");
  }
});

test("a plan that already reaches the goal needs no new clinics", () => {
  const p = plan(INPUTS, defaults(INPUTS), 240e6, 50, 250e6);
  assert.equal(p.newClinics, 0);
  assert.equal(p.remainder, 0);
});
