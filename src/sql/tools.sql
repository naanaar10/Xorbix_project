-- Agent tools: read-only Unity Catalog table functions. Statements are separated by the @@ marker line.
-- The agents discover these from Unity Catalog, so the COMMENTs below are what the LLM reads.
-- {fq} is replaced with catalog.schema at setup time.

CREATE OR REPLACE FUNCTION {fq}.get_network_kpis(
  top_n INT DEFAULT 10 COMMENT 'How many clinics to return, ranked by revenue at stake')
RETURNS TABLE (location_id STRING, location_name STRING, annual_revenue DOUBLE,
  plan_completion_rate DOUBLE, lead_conversion_rate DOUBLE, median_response_hours DOUBLE,
  no_show_rate DOUBLE, am_utilization DOUBLE, pm_utilization DOUBLE, at_risk_patients BIGINT,
  retention_revenue_at_stake DOUBLE, leads_revenue_at_stake DOUBLE, capacity_revenue_at_stake DOUBLE,
  total_revenue_at_stake DOUBLE, largest_lever STRING, stake_rank INT)
COMMENT 'Network overview. First row is the network median; then the clinics with the most annual revenue at stake, with KPIs and dollars at stake per lever (retention, leads, capacity). Start every investigation here.'
RETURN
  SELECT 'NETWORK_MEDIAN', 'Network median', ROUND(percentile_approx(annual_revenue, 0.5)),
    ROUND(MAX(med_completion), 3), ROUND(MAX(med_conversion), 3), ROUND(MAX(med_response_hours), 1),
    ROUND(MAX(med_no_show), 3), ROUND(MAX(med_am_util), 2), ROUND(MAX(med_pm_util), 2),
    CAST(percentile_approx(at_risk_patients, 0.5) AS BIGINT), 0D, 0D, 0D, 0D, NULL, 0
  FROM {fq}.clinic_kpis
  UNION ALL
  SELECT location_id, location_name, ROUND(annual_revenue), ROUND(plan_completion_rate, 3),
    ROUND(lead_conversion_rate, 3), ROUND(median_response_hours, 1), ROUND(no_show_rate, 3),
    ROUND(am_utilization, 2), ROUND(pm_utilization, 2), at_risk_patients,
    ROUND(retention_revenue_at_stake), ROUND(leads_revenue_at_stake), ROUND(capacity_revenue_at_stake),
    ROUND(total_revenue_at_stake), largest_lever, stake_rank
  FROM {fq}.clinic_kpis
  WHERE stake_rank <= top_n;

-- @@
CREATE OR REPLACE FUNCTION {fq}.compare_clinic_to_network(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007')
RETURNS TABLE (metric STRING, clinic_value DOUBLE, network_median DOUBLE, network_best DOUBLE,
  rank_worst_first INT)
COMMENT 'Every KPI for one clinic next to the network median and best clinic, with its rank among all clinics (1 = worst). Use to confirm which lever is really broken.'
RETURN
  WITH ranked AS (
    SELECT location_id, plan_completion_rate, lead_conversion_rate, median_response_hours,
      no_show_rate, am_utilization, pm_utilization, annual_revenue,
      RANK() OVER (ORDER BY plan_completion_rate) AS r_completion,
      RANK() OVER (ORDER BY lead_conversion_rate) AS r_conversion,
      RANK() OVER (ORDER BY median_response_hours DESC) AS r_response,
      RANK() OVER (ORDER BY no_show_rate DESC) AS r_no_show,
      RANK() OVER (ORDER BY am_utilization) AS r_am,
      RANK() OVER (ORDER BY pm_utilization) AS r_pm,
      RANK() OVER (ORDER BY annual_revenue) AS r_revenue,
      MAX(plan_completion_rate) OVER () AS b_completion, MAX(lead_conversion_rate) OVER () AS b_conversion,
      MIN(median_response_hours) OVER () AS b_response, MIN(no_show_rate) OVER () AS b_no_show,
      MAX(am_utilization) OVER () AS b_am, MAX(pm_utilization) OVER () AS b_pm,
      MAX(annual_revenue) OVER () AS b_revenue,
      med_completion, med_conversion, med_response_hours, med_no_show, med_am_util, med_pm_util
    FROM {fq}.clinic_kpis),
  rev_med AS (SELECT percentile_approx(annual_revenue, 0.5) AS med_revenue FROM {fq}.clinic_kpis)
  SELECT stack(7,
    'plan_completion_rate', ROUND(plan_completion_rate, 3), ROUND(med_completion, 3), ROUND(b_completion, 3), r_completion,
    'lead_conversion_rate', ROUND(lead_conversion_rate, 3), ROUND(med_conversion, 3), ROUND(b_conversion, 3), r_conversion,
    'median_response_hours', ROUND(median_response_hours, 1), ROUND(med_response_hours, 1), ROUND(b_response, 1), r_response,
    'no_show_rate', ROUND(no_show_rate, 3), ROUND(med_no_show, 3), ROUND(b_no_show, 3), r_no_show,
    'am_utilization', ROUND(am_utilization, 2), ROUND(med_am_util, 2), ROUND(b_am, 2), r_am,
    'pm_utilization', ROUND(pm_utilization, 2), ROUND(med_pm_util, 2), ROUND(b_pm, 2), r_pm,
    'annual_revenue', ROUND(annual_revenue), ROUND(med_revenue), ROUND(b_revenue), r_revenue)
  FROM ranked CROSS JOIN rev_med
  WHERE location_id = clinic_id;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_dropoff_by_visit_number(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007')
RETURNS TABLE (visit_number INT, clinic_dropout_rate DOUBLE, network_dropout_rate DOUBLE,
  clinic_plans_reaching_visit BIGINT)
COMMENT 'For care plans, the share of patients who quit right after each visit number (1-12), for this clinic and the whole network. Shows where in the plan patients drop out.'
RETURN
  WITH target AS (SELECT clinic_id AS cid),
  plans AS (
    SELECT cp.visits_completed, cp.status, cp.location_id = t.cid AS here
    FROM {fq}.care_plans cp CROSS JOIN target t
    WHERE cp.plan_type <> 'Wellness' AND cp.status IN ('Completed', 'Dropped')),
  visits AS (SELECT explode(sequence(1, 12)) AS k),
  rates AS (
    SELECT v.k,
      SUM(CASE WHEN p.here AND p.status = 'Dropped' AND p.visits_completed = v.k THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN p.here AND p.visits_completed >= v.k THEN 1 ELSE 0 END), 0) AS clinic_rate,
      SUM(CASE WHEN p.status = 'Dropped' AND p.visits_completed = v.k THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN p.visits_completed >= v.k THEN 1 ELSE 0 END), 0) AS network_rate,
      SUM(CASE WHEN p.here AND p.visits_completed >= v.k THEN 1 ELSE 0 END) AS reaching
    FROM visits v CROSS JOIN plans p
    GROUP BY v.k)
  SELECT k, ROUND(clinic_rate, 3), ROUND(network_rate, 3), reaching FROM rates ORDER BY k;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_cancellation_reasons(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007')
RETURNS TABLE (reason STRING, clinic_share DOUBLE, network_share DOUBLE, clinic_count BIGINT)
COMMENT 'Why appointments were cancelled or missed in the last 12 months: share of each reason at this clinic vs the network.'
RETURN
  WITH c AS (
    SELECT a.location_id, COALESCE(a.cancellation_reason, 'No reason given') AS reason
    FROM {fq}.appointments a CROSS JOIN {fq}.network_metadata m
    WHERE a.status IN ('Cancelled', 'No-Show') AND a.appointment_date > date_sub(m.as_of, 365)),
  clinic AS (SELECT reason, COUNT(*) AS n FROM c WHERE location_id = clinic_id GROUP BY reason),
  network AS (SELECT reason, COUNT(*) AS n FROM c GROUP BY reason)
  SELECT n.reason, ROUND(COALESCE(cl.n, 0) / SUM(cl.n) OVER (), 3), ROUND(n.n / SUM(n.n) OVER (), 3),
    COALESCE(cl.n, 0)
  FROM network n LEFT JOIN clinic cl ON n.reason = cl.reason
  ORDER BY COALESCE(cl.n, 0) DESC;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_provider_breakdown(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007')
RETURNS TABLE (provider_id STRING, closed_plans BIGINT, plan_completion_rate DOUBLE,
  active_plans BIGINT, share_of_new_plans DOUBLE, pct_appointments_before_1pm DOUBLE,
  works_afternoons BOOLEAN, scheduling_conflict_share_of_cancellations DOUBLE)
COMMENT 'Each chiropractor at a clinic: plan completion, workload, whether they work afternoons, and how often their cancellations cite scheduling conflicts. Use to find provider-level causes.'
RETURN
  WITH chiro AS (
    SELECT provider_id FROM {fq}.providers WHERE location_id = clinic_id AND specialty = 'Chiropractor'),
  plans AS (
    SELECT cp.provider_id,
      SUM(CASE WHEN cp.status IN ('Completed', 'Dropped') THEN 1 ELSE 0 END) AS closed,
      AVG(CASE WHEN cp.status = 'Completed' THEN 1D WHEN cp.status = 'Dropped' THEN 0D END) AS completion,
      SUM(CASE WHEN cp.status = 'Active' THEN 1 ELSE 0 END) AS active,
      COUNT(*) AS total
    FROM {fq}.care_plans cp JOIN chiro c ON cp.provider_id = c.provider_id
    WHERE cp.plan_type <> 'Wellness'
    GROUP BY cp.provider_id),
  appts AS (
    SELECT a.provider_id,
      AVG(CASE WHEN a.appointment_time < '13:00' THEN 1D ELSE 0D END) AS am_share,
      MAX(CASE WHEN a.appointment_time >= '13:00' THEN 1 ELSE 0 END) = 1 AS works_pm,
      SUM(CASE WHEN a.cancellation_reason = 'Scheduling conflict' THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN a.status IN ('Cancelled', 'No-Show') THEN 1 ELSE 0 END), 0) AS sched_share
    FROM {fq}.appointments a JOIN chiro c ON a.provider_id = c.provider_id
    GROUP BY a.provider_id)
  SELECT p.provider_id, p.closed, ROUND(p.completion, 3), p.active,
    ROUND(p.total / SUM(p.total) OVER (), 3), ROUND(a.am_share, 3), a.works_pm, ROUND(a.sched_share, 3)
  FROM plans p JOIN appts a ON p.provider_id = a.provider_id
  ORDER BY p.completion;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_lead_response_stats(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC012')
RETURNS TABLE (response_time STRING, clinic_share_of_leads DOUBLE, clinic_conversion_rate DOUBLE,
  network_share_of_leads DOUBLE, network_conversion_rate DOUBLE)
COMMENT 'How fast leads get a first response (buckets) and how well each bucket converts, at this clinic vs the network. Shows whether slow follow-up is costing patients.'
RETURN
  WITH target AS (SELECT clinic_id AS cid),
  l AS (
    SELECT CAST(converted_flag AS DOUBLE) AS converted, assigned_location_id = t.cid AS here,
      CASE WHEN first_response_hours < 1 THEN '1: under 1h' WHEN first_response_hours < 4 THEN '2: 1-4h'
           WHEN first_response_hours < 24 THEN '3: 4-24h' ELSE '4: over 24h' END AS bucket
    FROM {fq}.leads CROSS JOIN {fq}.network_metadata m CROSS JOIN target t
    WHERE created_date BETWEEN date_sub(m.as_of, 365) AND date_sub(m.as_of, 30))
  SELECT bucket,
    ROUND(SUM(CASE WHEN here THEN 1 ELSE 0 END)
      / SUM(SUM(CASE WHEN here THEN 1 ELSE 0 END)) OVER (), 3),
    ROUND(AVG(CASE WHEN here THEN converted END), 3),
    ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 3),
    ROUND(AVG(converted), 3)
  FROM l GROUP BY bucket
  UNION ALL
  SELECT '0: all leads', 1D, ROUND(AVG(CASE WHEN here THEN converted END), 3), 1D, ROUND(AVG(converted), 3)
  FROM l
  ORDER BY 1;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_capacity_by_daypart(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC019')
RETURNS TABLE (daypart STRING, clinic_utilization DOUBLE, network_median_utilization DOUBLE,
  clinic_no_show_rate DOUBLE, network_no_show_rate DOUBLE, open_slots_next_14_days BIGINT)
COMMENT 'Morning vs afternoon chiropractor utilization and no-show rates for a clinic vs the network, plus open slots in the next 14 days. Use to find empty capacity.'
RETURN
  WITH target AS (SELECT clinic_id AS cid),
  k AS (SELECT * FROM {fq}.clinic_kpis WHERE location_id = clinic_id),
  ns AS (
    SELECT CASE WHEN a.appointment_time < '13:00' THEN 'Morning' ELSE 'Afternoon' END AS daypart,
      AVG(CASE WHEN a.location_id = t.cid THEN CASE WHEN a.status = 'No-Show' THEN 1D ELSE 0D END END) AS clinic_ns,
      AVG(CASE WHEN a.status = 'No-Show' THEN 1D ELSE 0D END) AS network_ns
    FROM {fq}.appointments a CROSS JOIN {fq}.network_metadata m CROSS JOIN target t
    WHERE a.status <> 'Scheduled' AND a.appointment_date > date_sub(m.as_of, 365)
    GROUP BY 1),
  slots AS (SELECT daypart, COUNT(*) AS n FROM {fq}.open_slots WHERE location_id = clinic_id GROUP BY daypart)
  SELECT ns.daypart,
    ROUND(CASE WHEN ns.daypart = 'Morning' THEN k.am_utilization ELSE k.pm_utilization END, 2),
    ROUND(CASE WHEN ns.daypart = 'Morning' THEN k.med_am_util ELSE k.med_pm_util END, 2),
    ROUND(ns.clinic_ns, 3), ROUND(ns.network_ns, 3), COALESCE(s.n, 0)
  FROM ns CROSS JOIN k LEFT JOIN slots s ON ns.daypart = s.daypart
  ORDER BY ns.daypart DESC;

-- @@
CREATE OR REPLACE FUNCTION {fq}.find_at_risk_patients(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007',
  max_patients INT DEFAULT 25 COMMENT 'Maximum patients to return')
RETURNS TABLE (patient_id STRING, care_plan_id STRING, plan_type STRING, visits_completed INT,
  prescribed_visits INT, days_since_last_visit INT, cadence_days INT, provider_id STRING,
  provider_works_afternoons BOOLEAN, payment_type STRING, age_band STRING,
  last_cancellation_reason STRING, remaining_plan_value DOUBLE)
COMMENT 'Patients on an active care plan who are overdue (more than 1.5x their visit cadence) with nothing booked: the ones silently dropping out. Includes the signals that hint at why.'
RETURN
  WITH future AS (SELECT DISTINCT patient_id FROM {fq}.appointments WHERE status = 'Scheduled'),
  pm AS (SELECT provider_id, MAX(CASE WHEN appointment_time >= '13:00' THEN 1 ELSE 0 END) = 1 AS works_pm
         FROM {fq}.appointments WHERE location_id = clinic_id GROUP BY provider_id),
  last_cancel AS (
    SELECT patient_id, max_by(cancellation_reason, appointment_date) AS reason
    FROM {fq}.appointments
    WHERE location_id = clinic_id AND status IN ('Cancelled', 'No-Show')
    GROUP BY patient_id),
  risk AS (
    SELECT cp.patient_id, cp.care_plan_id, cp.plan_type, cp.visits_completed, cp.prescribed_visits,
      datediff(m.as_of, cp.last_visit_date) AS days_since, cp.cadence_days, cp.provider_id,
      pm.works_pm, cp.payment_type, p.age_band, lc.reason,
      ROUND((cp.prescribed_visits - cp.visits_completed) * k.avg_visit_revenue) AS remaining_value
    FROM {fq}.care_plans cp
    LEFT ANTI JOIN future f ON cp.patient_id = f.patient_id
    JOIN {fq}.patients p ON cp.patient_id = p.patient_id
    LEFT JOIN pm ON cp.provider_id = pm.provider_id
    LEFT JOIN last_cancel lc ON cp.patient_id = lc.patient_id
    CROSS JOIN {fq}.network_metadata m
    JOIN {fq}.clinic_kpis k ON k.location_id = cp.location_id
    WHERE cp.location_id = clinic_id AND cp.status = 'Active'
      AND datediff(m.as_of, cp.last_visit_date) > 1.5 * cp.cadence_days)
  SELECT patient_id, care_plan_id, plan_type, visits_completed, prescribed_visits, days_since,
    cadence_days, provider_id, works_pm, payment_type, age_band, reason, remaining_value
  FROM (SELECT *, ROW_NUMBER() OVER (ORDER BY remaining_value DESC, days_since) AS rn FROM risk)
  WHERE rn <= max_patients;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_patient_history(
  patient_id_in STRING COMMENT 'Patient id, e.g. PT0001234')
RETURNS TABLE (appointment_date DATE, appointment_time STRING, provider_id STRING,
  appointment_type STRING, status STRING, cancellation_reason STRING, lead_time_days INT)
COMMENT 'The last 12 appointments for one patient (newest first), including cancellations and their reasons.'
RETURN
  SELECT appointment_date, appointment_time, provider_id, appointment_type, status,
    cancellation_reason, lead_time_days
  FROM (SELECT *, ROW_NUMBER() OVER (ORDER BY appointment_date DESC, appointment_time DESC) AS rn
        FROM {fq}.appointments WHERE patient_id = patient_id_in)
  WHERE rn <= 12;

-- @@
CREATE OR REPLACE FUNCTION {fq}.find_open_slots(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007',
  daypart_in STRING DEFAULT 'Any' COMMENT 'Morning, Afternoon or Any',
  max_slots INT DEFAULT 8 COMMENT 'Maximum slots to return')
RETURNS TABLE (slot_date DATE, slot_time STRING, provider_id STRING, daypart STRING)
COMMENT 'Bookable chiropractor slots at a clinic in the next 14 days, soonest first. Use to offer a patient a specific time.'
RETURN
  SELECT slot_date, slot_time, provider_id, daypart
  FROM (SELECT *, ROW_NUMBER() OVER (ORDER BY slot_date, slot_time, provider_id) AS rn
        FROM {fq}.open_slots
        WHERE location_id = clinic_id AND (daypart_in = 'Any' OR daypart = daypart_in))
  WHERE rn <= max_slots;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_stale_leads(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC012',
  max_leads INT DEFAULT 20 COMMENT 'Maximum leads to return')
RETURNS TABLE (lead_id STRING, source STRING, created_date DATE, age_days INT, status STRING,
  first_response_hours DOUBLE, num_touchpoints INT)
COMMENT 'Open leads from the last 30 days that have not converted yet, newest and least-contacted first. These are the leads still worth calling.'
RETURN
  SELECT lead_id, source, created_date, age_days, status, first_response_hours, num_touchpoints
  FROM (
    SELECT l.*, datediff(m.as_of, l.created_date) AS age_days,
      ROW_NUMBER() OVER (ORDER BY CASE l.status WHEN 'New' THEN 0 WHEN 'Contacted' THEN 1 ELSE 2 END,
                                  l.created_date DESC) AS rn
    FROM {fq}.leads l CROSS JOIN {fq}.network_metadata m
    WHERE l.assigned_location_id = clinic_id AND NOT l.converted_flag
      AND l.status IN ('New', 'Contacted', 'Qualified')
      AND l.created_date > date_sub(m.as_of, 30))
  WHERE rn <= max_leads;

-- @@
CREATE OR REPLACE FUNCTION {fq}.find_reactivation_candidates(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC019',
  max_patients INT DEFAULT 20 COMMENT 'Maximum patients to return')
RETURNS TABLE (patient_id STRING, days_since_last_visit INT, lifetime_visit_count INT,
  payment_type STRING, age_band STRING, usual_daypart STRING)
COMMENT 'Lapsed patients (last visit 45-180 days ago, nothing booked) who were loyal before. Good candidates to fill empty slots with a wellness or off-peak offer.'
RETURN
  WITH future AS (SELECT DISTINCT patient_id FROM {fq}.appointments WHERE status = 'Scheduled'),
  pay AS (SELECT patient_id, max_by(payment_type, visit_date) AS payment_type
          FROM {fq}.visits WHERE location_id = clinic_id GROUP BY patient_id),
  daypart AS (
    SELECT patient_id, CASE WHEN AVG(CASE WHEN appointment_time < '13:00' THEN 1D ELSE 0D END) >= 0.5
                            THEN 'Morning' ELSE 'Afternoon' END AS usual
    FROM {fq}.appointments WHERE location_id = clinic_id AND status = 'Completed' GROUP BY patient_id),
  cand AS (
    SELECT p.patient_id, p.lifetime_visit_count, p.age_band, pay.payment_type, d.usual,
      datediff(m.as_of, max(v.visit_date)) AS days_since
    FROM {fq}.patients p
    LEFT ANTI JOIN future f ON p.patient_id = f.patient_id
    JOIN {fq}.visits v ON p.patient_id = v.patient_id
    JOIN pay ON p.patient_id = pay.patient_id
    JOIN daypart d ON p.patient_id = d.patient_id
    CROSS JOIN {fq}.network_metadata m
    WHERE p.home_location_id = clinic_id AND p.status = 'Lapsed'
    GROUP BY p.patient_id, p.lifetime_visit_count, p.age_band, pay.payment_type, d.usual, m.as_of)
  SELECT patient_id, days_since, lifetime_visit_count, payment_type, age_band, usual
  FROM (SELECT *, ROW_NUMBER() OVER (ORDER BY lifetime_visit_count DESC) AS rn FROM cand)
  WHERE rn <= max_patients;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_intervention_performance()
RETURNS TABLE (intervention STRING, signal STRING, actions BIGINT, patients_returned BIGINT,
  return_rate DOUBLE)
COMMENT 'What worked in past runs: for each intervention and the patient signal it was used on (last cancellation reason), how many patients came back. Use it to pick interventions that have worked before.'
RETURN
  SELECT o.intervention, COALESCE(o.signal, 'none') AS signal, COUNT(*) AS actions,
    SUM(CASE WHEN o.returned THEN 1 ELSE 0 END) AS patients_returned,
    ROUND(AVG(CASE WHEN o.returned THEN 1D ELSE 0D END), 3) AS return_rate
  FROM {fq}.action_outcomes o
  WHERE o.arm = 'agent'
  GROUP BY o.intervention, COALESCE(o.signal, 'none')
  HAVING COUNT(*) >= 3
  ORDER BY return_rate DESC;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_marketing_channels()
RETURNS TABLE (channel STRING, yearly_spend DOUBLE, leads BIGINT, new_patients BIGINT,
  cost_per_new_patient DOUBLE, share_of_budget DOUBLE)
COMMENT 'Marketing for the whole network over the last 12 months, one row per channel: money spent, leads, new patients, cost per new patient (cheapest first) and share of the budget. Use it to find money that would win more new patients in another channel.'
RETURN
  WITH ref AS (SELECT as_of FROM {fq}.network_metadata),
  ch AS (
    SELECT c.channel, SUM(c.budget) AS spend, SUM(c.leads_generated) AS leads, SUM(c.conversions) AS conv
    FROM {fq}.marketing_campaigns c CROSS JOIN ref
    WHERE c.start_date > date_sub(ref.as_of, 365) AND c.start_date <= ref.as_of
    GROUP BY c.channel)
  SELECT channel, ROUND(spend), leads, conv, ROUND(spend / conv, 2), ROUND(spend / SUM(spend) OVER (), 3)
  FROM ch
  ORDER BY spend / conv;

-- @@
CREATE OR REPLACE FUNCTION {fq}.price_budget_shift(
  from_channel STRING COMMENT 'Channel to take money from, e.g. Paid Search',
  to_channel STRING COMMENT 'Channel to give the money to, e.g. Referral Program',
  amount DOUBLE COMMENT 'Dollars a year to move')
RETURNS TABLE (from_spend DOUBLE, to_spend DOUBLE, patients_lost DOUBLE, patients_gained DOUBLE,
  extra_patients DOUBLE, revenue_per_patient DOUBLE, yearly_revenue DOUBLE)
COMMENT 'Prices moving marketing money from one channel to another, using the last 12 months. Moved money is assumed to win new patients at half the rate the receiving channel does today (each extra dollar in one channel works less well). Returns new patients lost and won, and the extra yearly revenue. A channel can lose at most a quarter of its budget and can at most double.'
RETURN
  WITH ref AS (SELECT as_of FROM {fq}.network_metadata),
  ch AS (
    SELECT c.channel, SUM(c.budget) AS spend, SUM(c.conversions) AS conv
    FROM {fq}.marketing_campaigns c CROSS JOIN ref
    WHERE c.start_date > date_sub(ref.as_of, 365) AND c.start_date <= ref.as_of
    GROUP BY c.channel),
  f AS (SELECT spend, conv FROM ch WHERE channel = from_channel),
  t AS (SELECT spend, conv FROM ch WHERE channel = to_channel),
  k AS (SELECT MAX(revenue_per_patient) AS rpp FROM {fq}.clinic_kpis)
  SELECT f.spend, t.spend, amount / (f.spend / f.conv), amount / (2 * t.spend / t.conv),
    amount / (2 * t.spend / t.conv) - amount / (f.spend / f.conv), k.rpp,
    (amount / (2 * t.spend / t.conv) - amount / (f.spend / f.conv)) * k.rpp
  FROM f CROSS JOIN t CROSS JOIN k;

-- @@
CREATE OR REPLACE FUNCTION {fq}.get_loyalty_stats()
RETURNS TABLE (location_id STRING, city STRING, finishers_last_year BIGINT, wellness_uptake DOUBLE,
  referral_rate DOUBLE, extra_wellness_plans DOUBLE, extra_referrers DOUBLE, yearly_value DOUBLE)
COMMENT 'Patients who finished a care plan in the last year, by clinic: the share who then started a Wellness plan, the share who referred someone, how many more would do each if the clinic matched the best 10% of clinics, and what that is worth a year. The first rows are the typical clinic (TYPICAL) and the best 10% (TOP_10_PERCENT); then clinics, furthest behind first.'
RETURN
  WITH ref AS (SELECT as_of FROM {fq}.network_metadata),
  finishers AS (
    SELECT cp.location_id, cp.patient_id, cp.last_visit_date
    FROM {fq}.care_plans cp CROSS JOIN ref
    WHERE cp.status = 'Completed' AND cp.plan_type <> 'Wellness' AND cp.last_visit_date > date_sub(ref.as_of, 365)),
  wellness AS (SELECT patient_id, MIN(start_date) AS started FROM {fq}.care_plans WHERE plan_type = 'Wellness'
               GROUP BY patient_id),
  referrers AS (SELECT referring_patient_id AS patient_id, COUNT(*) AS n FROM {fq}.referrals GROUP BY referring_patient_id),
  per AS (
    SELECT f.location_id, COUNT(*) AS finishers,
           AVG(CASE WHEN w.started >= date_sub(f.last_visit_date, 30) THEN 1D ELSE 0D END) AS uptake,
           AVG(CASE WHEN r.n > 0 THEN 1D ELSE 0D END) AS referral_rate
    FROM finishers f LEFT JOIN wellness w ON f.patient_id = w.patient_id
    LEFT JOIN referrers r ON f.patient_id = r.patient_id
    GROUP BY f.location_id),
  top AS (SELECT percentile_approx(uptake, 0.5) AS med_uptake, percentile_approx(referral_rate, 0.5) AS med_referral,
                 percentile_approx(uptake, 0.9) AS top_uptake, percentile_approx(referral_rate, 0.9) AS top_referral,
                 CAST(percentile_approx(finishers, 0.5) AS BIGINT) AS med_finishers FROM per),
  v AS (SELECT (SELECT AVG(visits_completed) FROM {fq}.care_plans WHERE plan_type = 'Wellness' AND status = 'Completed')
                 * (SELECT MAX(avg_visit_revenue) FROM {fq}.clinic_kpis) AS plan_value,
               (SELECT COUNT(*) / COUNT(DISTINCT referring_patient_id) FROM {fq}.referrals)
                 * (SELECT AVG(CAST(converted_flag AS DOUBLE)) FROM {fq}.leads WHERE source = 'Referral')
                 * (SELECT MAX(revenue_per_patient) FROM {fq}.clinic_kpis) AS referrer_value),
  clinics AS (
    SELECT p.location_id, l.city, p.finishers, ROUND(p.uptake, 3) AS uptake, ROUND(p.referral_rate, 3) AS referral_rate,
           ROUND(GREATEST(0, t.top_uptake - p.uptake) * p.finishers, 1) AS extra_plans,
           ROUND(GREATEST(0, t.top_referral - p.referral_rate) * p.finishers, 1) AS extra_referrers,
           ROUND(GREATEST(0, t.top_uptake - p.uptake) * p.finishers * v.plan_value
                 + GREATEST(0, t.top_referral - p.referral_rate) * p.finishers * v.referrer_value) AS yearly_value
    FROM per p JOIN {fq}.locations l ON p.location_id = l.location_id CROSS JOIN top t CROSS JOIN v)
  SELECT 'TYPICAL', 'Typical clinic', med_finishers, ROUND(med_uptake, 3), ROUND(med_referral, 3), 0D, 0D, 0D FROM top
  UNION ALL
  SELECT 'TOP_10_PERCENT', 'Best 10% of clinics', NULL, ROUND(top_uptake, 3), ROUND(top_referral, 3), 0D, 0D, 0D FROM top
  UNION ALL
  SELECT * FROM (SELECT * FROM clinics ORDER BY yearly_value DESC);

-- @@
CREATE OR REPLACE FUNCTION {fq}.find_recent_finishers(
  clinic_id STRING COMMENT 'Clinic id, e.g. LOC007',
  max_patients INT DEFAULT 6 COMMENT 'How many patients to return')
RETURNS TABLE (patient_id STRING, care_plan_id STRING, plan_type STRING, visits_completed INT,
  days_since_finished INT, payment_type STRING, age_band STRING, referrals_made BIGINT, lifetime_visit_count INT)
COMMENT 'Patients at a clinic who finished a care plan in the last 60 days and have not started a Wellness plan, most recent first: the plan they finished, how they pay, their age band and how many people they have referred so far.'
RETURN
  WITH ref AS (SELECT as_of FROM {fq}.network_metadata),
  wellness AS (SELECT DISTINCT patient_id FROM {fq}.care_plans WHERE plan_type = 'Wellness'),
  referrers AS (SELECT referring_patient_id AS patient_id, COUNT(*) AS n FROM {fq}.referrals GROUP BY referring_patient_id),
  done AS (
    SELECT cp.patient_id, cp.care_plan_id, cp.plan_type, cp.visits_completed,
           datediff(ref.as_of, cp.last_visit_date) AS days_since_finished, cp.payment_type,
           ROW_NUMBER() OVER (PARTITION BY cp.patient_id ORDER BY cp.last_visit_date DESC) AS rn
    FROM {fq}.care_plans cp CROSS JOIN ref
    LEFT ANTI JOIN wellness w ON cp.patient_id = w.patient_id
    WHERE cp.location_id = clinic_id AND cp.status = 'Completed' AND cp.plan_type <> 'Wellness'
      AND cp.last_visit_date > date_sub(ref.as_of, 60))
  SELECT patient_id, care_plan_id, plan_type, visits_completed, days_since_finished, payment_type, age_band,
         referrals_made, lifetime_visit_count
  FROM (
    SELECT d.patient_id, d.care_plan_id, d.plan_type, d.visits_completed, d.days_since_finished, d.payment_type,
           p.age_band, COALESCE(r.n, 0) AS referrals_made, p.lifetime_visit_count,
           ROW_NUMBER() OVER (ORDER BY d.days_since_finished, d.patient_id) AS pick
    FROM done d JOIN {fq}.patients p ON d.patient_id = p.patient_id
    LEFT JOIN referrers r ON d.patient_id = r.patient_id
    WHERE d.rn = 1)
  WHERE pick <= max_patients
  ORDER BY pick;
