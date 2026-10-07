"""Synthetic chiropractic network built from simulated patient journeys.

Based on Xorbix's `generate_synthetic_data` notebook: same 8 tables and column names, plus
`care_plans`, `open_slots` and `sim_ground_truth`. Rows come from simulated journeys
(lead -> first visit -> care plan -> visits -> completion or dropout), so columns agree with
each other, and four clinics carry planted problems for the agents to find:

  LOC003  best practice: low dropout, high wellness-plan uptake
  LOC007  retention: one chiropractor works mornings only yet carries a large share of new
          plans; their patients cancel with scheduling conflicts and drop out after visit 3
  LOC012  leads: slow first response (~36h median) and low conversion
  LOC019  capacity: weak afternoon demand and a high no-show rate

No names, contact details, birthdates or clinical fields: people are surrogate IDs only.
Pure Python (no Spark) so it can be tested locally; `jobs/generate_data.py` writes to Delta.
"""
from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

BEST_CLINIC = "LOC003"
RETENTION_CLINIC = "LOC007"
LEADS_CLINIC = "LOC012"
CAPACITY_CLINIC = "LOC019"

COLUMNS = {
    "locations": ["location_id", "location_name", "city", "state", "region",
                  "capacity_patients_per_day", "monthly_lease_cost", "opened_date"],
    "providers": ["provider_id", "location_id", "specialty", "employment_type", "hire_date",
                  "active_flag"],
    "patients": ["patient_id", "home_location_id", "acquisition_source", "first_visit_date",
                 "tenure_months", "status", "age_band", "lifetime_visit_count", "churn_risk_score"],
    "leads": ["lead_id", "source", "assigned_location_id", "created_date", "status",
              "first_response_hours", "num_touchpoints", "converted_flag", "converted_patient_id"],
    "appointments": ["appointment_id", "patient_id", "provider_id", "location_id",
                     "appointment_date", "appointment_type", "booked_channel", "status",
                     "lead_time_days", "appointment_time", "care_plan_id", "cancellation_reason"],
    "visits": ["visit_id", "appointment_id", "patient_id", "provider_id", "location_id",
               "visit_date", "service_type", "revenue", "payment_type"],
    "referrals": ["referral_id", "referring_patient_id", "referred_lead_id", "referral_date",
                  "channel", "outcome"],
    "marketing_campaigns": ["campaign_id", "campaign_name", "channel", "start_date", "end_date",
                            "budget", "impressions", "clicks", "leads_generated", "conversions"],
    "care_plans": ["care_plan_id", "patient_id", "location_id", "provider_id", "plan_type",
                   "start_date", "prescribed_visits", "cadence_days", "visits_completed",
                   "last_visit_date", "status", "payment_type"],
    "open_slots": ["location_id", "provider_id", "slot_date", "slot_time", "daypart"],
    "sim_ground_truth": ["care_plan_id", "patient_id", "location_id", "true_reason",
                         "dropped_after_visit", "last_visit_date"],
}

# Clinic cities: business locations only, not anyone's address.
CITIES = [
    ("Iowa City", "IA"), ("Cedar Rapids", "IA"), ("Des Moines", "IA"), ("Davenport", "IA"),
    ("Ames", "IA"), ("Madison", "WI"), ("Milwaukee", "WI"), ("Green Bay", "WI"),
    ("Minneapolis", "MN"), ("St. Paul", "MN"), ("Rochester", "MN"), ("Chicago", "IL"),
    ("Naperville", "IL"), ("Peoria", "IL"), ("Springfield", "IL"), ("Omaha", "NE"),
    ("Lincoln", "NE"), ("Kansas City", "MO"), ("St. Louis", "MO"), ("Columbia", "MO"),
    ("Indianapolis", "IN"), ("Fort Wayne", "IN"), ("Columbus", "OH"), ("Cincinnati", "OH"),
    ("Cleveland", "OH"), ("Ann Arbor", "MI"), ("Grand Rapids", "MI"), ("Detroit", "MI"),
    ("Louisville", "KY"), ("Nashville", "TN"), ("Denver", "CO"), ("Boulder", "CO"),
    ("Austin", "TX"), ("Dallas", "TX"), ("Houston", "TX"), ("Phoenix", "AZ"),
    ("Scottsdale", "AZ"), ("Salt Lake City", "UT"), ("Boise", "ID"), ("Portland", "OR"),
    ("Seattle", "WA"), ("Spokane", "WA"), ("Sacramento", "CA"), ("San Diego", "CA"),
    ("Raleigh", "NC"), ("Charlotte", "NC"), ("Atlanta", "GA"), ("Tampa", "FL"),
    ("Orlando", "FL"), ("Pittsburgh", "PA"),
]
REGION_BY_STATE = {
    **dict.fromkeys(["IA", "WI", "MN", "IL", "NE", "MO", "IN", "OH", "MI"], "Midwest"),
    **dict.fromkeys(["KY", "TN", "TX", "NC", "GA", "FL"], "South"),
    **dict.fromkeys(["CO", "AZ", "UT", "ID", "OR", "WA", "CA"], "West"),
    "PA": "Northeast",
}

LEAD_SOURCES = {  # source: (share of leads, conversion multiplier)
    "Website Form": (0.30, 1.0), "Phone Inquiry": (0.15, 1.2), "Social Media Ad": (0.20, 0.8),
    "Referral": (0.12, 1.4), "Walk-In": (0.05, 1.5), "Community Event": (0.08, 0.9),
    "Insurance Directory": (0.10, 1.1),
}
SOURCE_TO_CHANNEL = {
    "Website Form": "Paid Search", "Social Media Ad": "Social Media", "Referral": "Referral Program",
    "Community Event": "Local Event", "Phone Inquiry": "Direct Mail", "Insurance Directory": "SEO",
}
CHANNEL_COST_PER_LEAD = {"Paid Search": 85.0, "Social Media": 60.0, "Referral Program": 25.0,
                         "Local Event": 70.0, "Direct Mail": 95.0, "SEO": 40.0}
AGE_BANDS = (["18-24", "25-34", "35-44", "45-54", "55-64", "65+"],
             [0.07, 0.20, 0.24, 0.21, 0.16, 0.12])
PAYMENT_TYPES = (["Insurance", "Self-Pay", "Package Plan", "HSA/FSA"], [0.45, 0.25, 0.20, 0.10])
BOOKED_CHANNELS = ["Online", "Phone", "In-Person", "Mobile App"]
SERVICE_PRICE = {
    "Initial Consultation": (140, 220), "Spinal Adjustment": (85, 130),
    "Follow-Up Adjustment": (70, 110), "Therapeutic Massage": (95, 160),
    "Re-Evaluation": (95, 150), "Physical Therapy": (110, 180),
}
PLAN_TYPES = {  # plan_type: (share of new patients, prescribed visits, cadence days)
    "Acute Relief": (0.55, 12, 4), "Corrective": (0.35, 24, 5), "Wellness": (0.10, 12, 28),
}
WELLNESS_PLAN = ("Wellness", 12, 28)
TRUE_REASONS = ["Feeling better", "Scheduling conflict", "Cost/insurance", "Transportation",
                "Dissatisfied"]
ROUTINE_CANCEL_REASONS = (["Scheduling conflict", "Illness", "Transportation", "Feeling better",
                           "Cost/insurance", "No reason given"],
                          [0.35, 0.25, 0.10, 0.05, 0.05, 0.20])
MORNING_TIMES = [f"{h:02d}:{m:02d}" for h in range(8, 13) for m in (0, 30)]     # 10 slots
AFTERNOON_TIMES = [f"{h:02d}:{m:02d}" for h in range(13, 18) for m in (0, 30)]  # 10 slots
SLOTS_PER_DAYPART = 10
DROPPED_AFTER_DAYS = 60  # plans silent this long are Dropped; shorter gaps stay Active (at risk)


@dataclass(frozen=True)
class SimConfig:
    as_of: date
    seed: int = 42
    num_clinics: int = 50
    history_days: int = 548          # ~18 months; KPIs use the trailing 12
    base_leads_per_day: float = 15.0
    slot_days_ahead: int = 14
    target_utilization: float = 0.80


@dataclass
class ClinicProfile:
    location_id: str
    leads_per_day: float
    response_median_hours: float
    no_show_p: float
    cancel_p: float
    dropout_mult: float
    wellness_uptake: float
    morning_share: float
    problem_provider_share: float = 0.0   # share of new plans going to the mornings-only chiro


def clinic_profiles(cfg: SimConfig) -> list[ClinicProfile]:
    rng = random.Random(cfg.seed)
    profiles = []
    for i in range(1, cfg.num_clinics + 1):
        p = ClinicProfile(
            location_id=f"LOC{i:03d}",
            leads_per_day=cfg.base_leads_per_day * math.exp(rng.gauss(0, 0.18)),
            response_median_hours=rng.uniform(2.5, 4.0),
            no_show_p=rng.uniform(0.07, 0.09),
            cancel_p=rng.uniform(0.07, 0.09),
            dropout_mult=rng.uniform(0.88, 1.12),
            wellness_uptake=rng.uniform(0.30, 0.40),
            morning_share=rng.uniform(0.48, 0.55),
        )
        if p.location_id == BEST_CLINIC:
            p.dropout_mult, p.wellness_uptake = 0.6, 0.6
        elif p.location_id == RETENTION_CLINIC:
            p.problem_provider_share = 0.55
        elif p.location_id == LEADS_CLINIC:
            p.response_median_hours = 36.0
        elif p.location_id == CAPACITY_CLINIC:
            p.leads_per_day *= 0.85
            p.no_show_p, p.morning_share = 0.18, 0.66
        profiles.append(p)
    return profiles


def _conversion_p(hours: float) -> float:
    if hours < 1:
        return 0.36
    if hours < 4:
        return 0.31
    if hours < 24:
        return 0.22
    return 0.10


def _dropout_hazard(visit_number: int, mult: float) -> float:
    """Chance a patient quits after completing this visit; peaks when pain eases (visits 2-5)."""
    base = 0.03 + (0.06 if 2 <= visit_number <= 5 else 0.0)
    return min(0.9, base * mult)


def _weekday(ordinal: int) -> int:
    return (ordinal - 1) % 7  # date.fromordinal(1) is a Monday


def _next_weekday(ordinal: int) -> int:
    wd = _weekday(ordinal)
    return ordinal + (7 - wd if wd >= 5 else 0)


class _Ids:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def next(self, prefix: str, width: int) -> str:
        n = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = n
        return f"{prefix}{n:0{width}d}"


class NetworkSimulator:
    """Simulates the network clinic by clinic; call `simulate_clinic` for each profile in order."""

    def __init__(self, cfg: SimConfig):
        self.cfg = cfg
        self.ids = _Ids()
        self.as_of_ord = cfg.as_of.toordinal()
        self.start_ord = self.as_of_ord - cfg.history_days
        self.network_rows: dict[str, list] = {"locations": [], "providers": []}

    # ---------------------------------------------------------------- per clinic
    def simulate_clinic(self, profile: ClinicProfile, index: int) -> dict[str, list[tuple]]:
        rng = random.Random(self.cfg.seed * 1000 + index)
        rows: dict[str, list[tuple]] = {t: [] for t in COLUMNS}
        loc = profile.location_id
        self._clinic_staff(profile, index, rng, rows)
        chiros, others = self._chiros, self._others

        for day in range(self.start_ord, self.as_of_ord + 1):
            for _ in range(self._poisson(rng, profile.leads_per_day)):
                self._simulate_lead(profile, day, rng, rows, chiros, others)

        self._open_slots(loc, chiros, rows)
        return rows

    def _clinic_staff(self, profile: ClinicProfile, index: int, rng: random.Random, rows):
        # Size chiropractor headcount to expected demand so normal clinics run ~80% utilized.
        # LOC012 staffs for the patients it actually converts; LOC019 is still staffed for the
        # demand it used to have, which is what leaves its afternoons empty.
        conversion = 0.15 if profile.location_id == LEADS_CLINIC else 0.28
        expected_daily = profile.leads_per_day * conversion * 16.0 * 7 / 5 * 0.8
        # Staff for each clinic's real demand: LOC003 keeps more patients, LOC007 loses more.
        expected_daily *= {BEST_CLINIC: 1.3, RETENTION_CLINIC: 0.85}.get(profile.location_id, 1.0)
        if profile.location_id == CAPACITY_CLINIC:
            expected_daily /= 0.68
        n_chiros = max(2, round(expected_daily / (2 * SLOTS_PER_DAYPART * self.cfg.target_utilization)))
        loc = profile.location_id
        self._chiros = []
        self._others = []
        for j in range(n_chiros + 2):
            pid = self.ids.next("PRV", 4)
            specialty = "Chiropractor" if j < n_chiros else ["Massage Therapist", "Physical Therapy Assistant"][j - n_chiros]
            (self._chiros if specialty == "Chiropractor" else self._others).append(pid)
            hire = date.fromordinal(self.start_ord - rng.randint(30, 1500))
            self.network_rows["providers"].append(
                (pid, loc, specialty, rng.choices(["Full-Time", "Part-Time", "Contract"], [0.7, 0.2, 0.1])[0], hire, True))
        city, state = CITIES[(index - 1) % len(CITIES)]
        self.network_rows["locations"].append((
            loc, f"{city} Spine & Wellness", city, state, REGION_BY_STATE[state],
            n_chiros * 2 * SLOTS_PER_DAYPART + 2 * 14, round(rng.uniform(6000, 18000), 2),
            date.fromordinal(self.start_ord - rng.randint(200, 2500)),
        ))
        self._problem_chiro = self._chiros[0] if profile.problem_provider_share > 0 else None

    @staticmethod
    def _poisson(rng: random.Random, lam: float) -> int:
        threshold, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= threshold:
                return k
            k += 1

    # ---------------------------------------------------------------- leads
    def _simulate_lead(self, profile, day, rng, rows, chiros, others):
        sources = list(LEAD_SOURCES)
        source = rng.choices(sources, [LEAD_SOURCES[s][0] for s in sources])[0]
        hours = round(min(240.0, math.exp(math.log(profile.response_median_hours) + rng.gauss(0, 1.0))), 1)
        converts = rng.random() < min(0.9, _conversion_p(hours) * LEAD_SOURCES[source][1])
        lead_id = self.ids.next("LD", 7)
        age = self.as_of_ord - day
        first_visit = _next_weekday(day + max(1, int(hours // 24)) + rng.randint(1, 5))
        patient_id = None
        if converts and first_visit <= self.as_of_ord:
            status = "Converted"
            patient_id = self._simulate_patient(profile, source, first_visit, rng, rows, chiros, others)
        elif converts:
            status = "Qualified"  # first visit booked but not yet happened
        elif age > 30:
            status = "Lost"
        else:
            status = "New" if age <= 2 else ("Contacted" if age <= 10 else "Qualified")
        touch = rng.randint(1, 4) if converts else rng.randint(0 if status == "New" else 1, 8)
        rows["leads"].append((lead_id, source, profile.location_id, date.fromordinal(day), status,
                              hours, touch, status == "Converted", patient_id))

    # ---------------------------------------------------------------- patients
    def _simulate_patient(self, profile, source, first_visit, rng, rows, chiros, others) -> str:
        pid = self.ids.next("PT", 7)
        age_band = rng.choices(*AGE_BANDS)[0]
        payment = rng.choices(*PAYMENT_TYPES)[0]
        plan_names = list(PLAN_TYPES)
        plan_type = rng.choices(plan_names, [PLAN_TYPES[n][0] for n in plan_names])[0]
        _, prescribed, cadence = PLAN_TYPES[plan_type]
        problem = self._problem_chiro is not None and rng.random() < profile.problem_provider_share
        chiro = self._problem_chiro if problem else rng.choice(
            [c for c in chiros if c != self._problem_chiro] or chiros)

        visits_total, last_visit, ongoing = 0, first_visit, False
        start, first_plan = first_visit, True
        plan = (plan_type, prescribed, cadence)
        while plan is not None:
            done, last_visit, outcome = self._simulate_plan(
                profile, pid, chiro, problem, plan, start, first_plan, payment, age_band, rng, rows, others)
            visits_total += done
            first_plan = False
            plan = None
            if outcome == "completed" and plan_type != "Wellness" and rng.random() < profile.wellness_uptake:
                start = _next_weekday(last_visit + rng.randint(14, 35))
                if start <= self.as_of_ord:
                    plan, plan_type = WELLNESS_PLAN, "Wellness"
            elif outcome == "ongoing":
                ongoing = True

        days_since = self.as_of_ord - last_visit
        if ongoing or days_since <= 45:
            status = "Active"
        elif days_since <= 180:
            status = "Lapsed"
        else:
            status = "Churned"
        risk = 0.1 if status == "Churned" else round(min(0.99, 1 - math.exp(-days_since / 45)), 3)
        rows["patients"].append((
            pid, profile.location_id, source, date.fromordinal(first_visit),
            max(0, (self.as_of_ord - first_visit) // 30), status, age_band, visits_total, risk))
        return pid

    def _true_reason(self, problem, visit_number, payment, age_band, rng) -> str:
        if problem and visit_number >= 3:
            weights = [0.15, 0.60, 0.10, 0.05, 0.10]
        else:
            weights = [0.36, 0.20, 0.24, 0.10, 0.10]
            if 2 <= visit_number <= 5:
                weights[0] *= 1.5
            if payment == "Self-Pay":
                weights[2] *= 2.0
            if age_band == "65+":
                weights[3] *= 2.5
        return rng.choices(TRUE_REASONS, weights)[0]

    def _simulate_plan(self, profile, pid, chiro, problem, plan, start, first_plan, payment,
                       age_band, rng, rows, others):
        """Returns (visits completed, last visit ordinal, outcome: completed|dropped|ongoing)."""
        plan_type, prescribed, cadence = plan
        plan_id = self.ids.next("CP", 7)
        loc = profile.location_id
        appt_day, booked_day, completed, last_visit = start, start - rng.randint(1, 5), 0, start
        outcome, true_reason = "ongoing", None

        while completed < prescribed:
            if appt_day > self.as_of_ord:
                if appt_day <= self.as_of_ord + self.cfg.slot_days_ahead:
                    self._appointment(rows, pid, chiro, loc, appt_day, "Follow-Up Adjustment",
                                      "Scheduled", appt_day - booked_day, self._pick_time(profile, chiro, rng),
                                      plan_id, None, rng)
                break
            visit_number = completed + 1
            service = self._service(plan_type, visit_number, first_plan, rng)
            provider = chiro if service not in ("Therapeutic Massage", "Physical Therapy") else (
                others[0] if service == "Therapeutic Massage" else others[1])
            time = self._pick_time(profile, chiro if provider == chiro else None, rng)
            status = self._appointment_status(profile, visit_number, rng)
            if status != "Completed":
                reason = self._routine_reason(problem, rng) if status != "Rescheduled" else None
                self._appointment(rows, pid, provider, loc, appt_day, service, status,
                                  appt_day - booked_day, time, plan_id, reason, rng)
                booked_day, appt_day = appt_day, _next_weekday(appt_day + rng.randint(1, 4))
                continue
            appt_id = self._appointment(rows, pid, provider, loc, appt_day, service, "Completed",
                                        appt_day - booked_day, time, plan_id, None, rng)
            low, high = SERVICE_PRICE[service]
            revenue = rng.uniform(low, high) * (0.85 if payment == "Package Plan" else 1.0)
            rows["visits"].append((self.ids.next("VS", 8), appt_id, pid, provider, loc,
                                   date.fromordinal(appt_day), service, round(revenue, 2), payment))
            completed, last_visit = completed + 1, appt_day
            if completed >= prescribed:
                outcome = "completed"
                break
            hazard = _dropout_hazard(visit_number, profile.dropout_mult * (3.5 if problem and visit_number >= 3 else 1.0))
            booked_day = appt_day
            next_day = _next_weekday(appt_day + cadence + rng.randint(-1, 2))
            if rng.random() < hazard:
                true_reason = self._true_reason(problem, visit_number, payment, age_band, rng)
                if rng.random() < 0.6 and next_day <= self.as_of_ord:  # a final cancel before going silent
                    shown = true_reason if rng.random() < 0.65 else "No reason given"
                    self._appointment(rows, pid, chiro, loc, next_day, "Follow-Up Adjustment",
                                      rng.choice(["Cancelled", "No-Show"]), next_day - booked_day,
                                      self._pick_time(profile, chiro, rng), plan_id, shown, rng)
                outcome = "dropped"
                break
            appt_day = next_day

        silent_days = self.as_of_ord - last_visit
        if outcome == "completed":
            plan_status = "Completed"
        elif outcome == "dropped" and silent_days > DROPPED_AFTER_DAYS:
            plan_status = "Dropped"
        else:
            plan_status = "Active"  # includes recent silent dropouts: the at-risk population
        if outcome == "dropped":
            rows["sim_ground_truth"].append((plan_id, pid, loc, true_reason, completed,
                                             date.fromordinal(last_visit)))
        rows["care_plans"].append((plan_id, pid, loc, chiro, plan_type, date.fromordinal(start),
                                   prescribed, cadence, completed, date.fromordinal(last_visit),
                                   plan_status, payment))
        return completed, last_visit, outcome

    def _appointment(self, rows, pid, provider, loc, day, appt_type, status, lead_time, time,
                     plan_id, reason, rng) -> str:
        appt_id = self.ids.next("AP", 8)
        rows["appointments"].append((appt_id, pid, provider, loc, date.fromordinal(day), appt_type,
                                     rng.choice(BOOKED_CHANNELS), status, max(0, lead_time), time,
                                     plan_id, reason))
        return appt_id

    @staticmethod
    def _service(plan_type, visit_number, first_plan, rng) -> str:
        if visit_number == 1 and first_plan:
            return "Initial Consultation"
        if visit_number % 6 == 0:
            return "Re-Evaluation"
        if plan_type == "Wellness":
            return rng.choices(["Spinal Adjustment", "Therapeutic Massage", "Follow-Up Adjustment"], [0.6, 0.3, 0.1])[0]
        return rng.choices(["Follow-Up Adjustment", "Spinal Adjustment", "Therapeutic Massage", "Physical Therapy"],
                           [0.55, 0.25, 0.12, 0.08])[0]

    @staticmethod
    def _appointment_status(profile, visit_number, rng) -> str:
        if visit_number == 1:
            return "Completed"  # a lead only becomes a patient by showing up
        r = rng.random()
        if r < profile.no_show_p:
            return "No-Show"
        if r < profile.no_show_p + profile.cancel_p:
            return "Cancelled"
        if r < profile.no_show_p + profile.cancel_p + 0.04:
            return "Rescheduled"
        return "Completed"

    @staticmethod
    def _routine_reason(problem, rng) -> str:
        if problem and rng.random() < 0.5:
            return "Scheduling conflict"
        return rng.choices(*ROUTINE_CANCEL_REASONS)[0]

    def _pick_time(self, profile, chiro, rng) -> str:
        if chiro is not None and chiro == self._problem_chiro:
            return rng.choice(MORNING_TIMES)  # this chiropractor only works mornings
        return rng.choice(MORNING_TIMES if rng.random() < profile.morning_share else AFTERNOON_TIMES)

    # ---------------------------------------------------------------- open slots
    def _open_slots(self, loc, chiros, rows):
        booked = {(r[2], r[4], r[9]) for r in rows["appointments"] if r[7] == "Scheduled"}
        for day in range(self.as_of_ord + 1, self.as_of_ord + self.cfg.slot_days_ahead + 1):
            if _weekday(day) >= 5:
                continue
            d = date.fromordinal(day)
            for chiro in chiros:
                times = MORNING_TIMES if chiro == self._problem_chiro else MORNING_TIMES + AFTERNOON_TIMES
                for t in times:
                    if (chiro, d, t) not in booked:
                        rows["open_slots"].append((loc, chiro, d, t, "Morning" if t < "13:00" else "Afternoon"))

    # ---------------------------------------------------------------- network-level tables
    def referrals(self, patients: list[tuple], leads: list[tuple], care_plans: list[tuple]) -> list[tuple]:
        """Link referral leads to referring patients; plan completers refer far more often."""
        rng = random.Random(self.cfg.seed + 7)
        completed = {r[1] for r in care_plans if r[10] == "Completed"}
        by_clinic: dict[str, list[tuple[int, str, float]]] = {}
        for p in patients:
            weight = 5.0 if p[0] in completed else (2.0 if p[5] == "Active" else 1.0)
            by_clinic.setdefault(p[1], []).append((p[3].toordinal(), p[0], weight))
        index = {}
        for loc, items in by_clinic.items():
            items.sort()
            cum, total = [], 0.0
            for item in items:
                total += item[2]
                cum.append(total)
            index[loc] = ([i[0] for i in items], [i[1] for i in items], cum)
        out = []
        for lead in leads:
            if lead[1] != "Referral" or lead[2] not in index:
                continue
            created = lead[3].toordinal()
            ordinals, ids, cum = index[lead[2]]
            eligible = bisect.bisect_left(ordinals, created - 7)
            if eligible == 0:
                continue
            referrer = ids[bisect.bisect_left(cum, rng.random() * cum[eligible - 1])]
            if lead[4] == "Converted":
                outcome = "Converted"
            elif lead[4] == "Lost":
                outcome = rng.choice(["Declined", "Expired"])
            else:
                outcome = "Pending"
            out.append((self.ids.next("RF", 7), referrer, lead[0],
                        date.fromordinal(created - rng.randint(0, 5)),
                        rng.choice(["Verbal Referral", "Referral Card", "Digital Share", "Family Referral Program"]),
                        outcome))
        return out

    def marketing_campaigns(self, leads: list[tuple]) -> list[tuple]:
        """One campaign per paid channel per quarter, with totals taken from the actual leads."""
        rng = random.Random(self.cfg.seed + 11)
        quarter = 91
        totals: dict[tuple[str, int], list[int]] = {}
        for ld in leads:
            channel = SOURCE_TO_CHANNEL.get(ld[1])
            if channel:
                key = (channel, (ld[3].toordinal() - self.start_ord) // quarter)
                agg = totals.setdefault(key, [0, 0])
                agg[0] += 1
                agg[1] += 1 if ld[7] else 0
        out = []
        n_quarters = (self.as_of_ord - self.start_ord) // quarter + 1
        for q in range(n_quarters):
            start = self.start_ord + q * quarter
            end = min(start + quarter - 1, self.as_of_ord)
            for channel, cpl in CHANNEL_COST_PER_LEAD.items():
                n_leads, conversions = totals.get((channel, q), [0, 0])
                clicks = int(n_leads / rng.uniform(0.06, 0.14))
                impressions = int(clicks / rng.uniform(0.02, 0.08))
                out.append((self.ids.next("MKT", 4), f"{channel} Q{q + 1}", channel,
                            date.fromordinal(start), date.fromordinal(end),
                            round(n_leads * cpl * rng.uniform(0.9, 1.1), 2), impressions, clicks,
                            n_leads, conversions))
        return out


STREAMED_TABLES = ("appointments", "visits", "open_slots", "sim_ground_truth")


def simulate_network(cfg: SimConfig, on_chunk=None, clinics_per_chunk: int = 10) -> dict[str, list[tuple]]:
    """Simulate every clinic. Large tables are passed to `on_chunk(table, rows)` in batches when a
    callback is given (keeps memory flat on small drivers); everything else is returned."""
    sim = NetworkSimulator(cfg)
    kept: dict[str, list[tuple]] = {t: [] for t in COLUMNS}
    pending: dict[str, list[tuple]] = {t: [] for t in STREAMED_TABLES}
    profiles = clinic_profiles(cfg)
    for i, profile in enumerate(profiles, start=1):
        rows = sim.simulate_clinic(profile, i)
        for table, table_rows in rows.items():
            (pending if table in STREAMED_TABLES and on_chunk else kept)[table].extend(table_rows)
        if on_chunk and (i % clinics_per_chunk == 0 or i == len(profiles)):
            for table in STREAMED_TABLES:
                on_chunk(table, pending[table])
                pending[table] = []
    kept["locations"] = sim.network_rows["locations"]
    kept["providers"] = sim.network_rows["providers"]
    kept["referrals"] = sim.referrals(kept["patients"], kept["leads"], kept["care_plans"])
    kept["marketing_campaigns"] = sim.marketing_campaigns(kept["leads"])
    return kept
