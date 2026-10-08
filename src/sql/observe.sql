-- Observe: one row per clinic with KPIs, network medians and revenue at stake per lever.
-- Rebuilt at the start of every agent run. {fq} is replaced with catalog.schema.
CREATE OR REPLACE TABLE {fq}.clinic_kpis
COMMENT 'Observe step: per-clinic KPIs, network medians and annual revenue at stake by lever. Rebuilt each agent run.'
AS
WITH ref AS (SELECT as_of FROM {fq}.network_metadata),
rev AS (
  SELECT v.location_id, SUM(v.revenue) AS annual_revenue, COUNT(*) AS annual_visits
  FROM {fq}.visits v CROSS JOIN ref
  WHERE v.visit_date > date_sub(ref.as_of, 365)
  GROUP BY v.location_id),
plans AS (
  SELECT cp.location_id,
         AVG(CASE WHEN cp.status = 'Completed' THEN 1D ELSE 0D END) AS plan_completion_rate,
         COUNT(*) AS closed_plans_per_year
  FROM {fq}.care_plans cp CROSS JOIN ref
  WHERE cp.status IN ('Completed', 'Dropped') AND cp.last_visit_date > date_sub(ref.as_of, 365)
  GROUP BY cp.location_id),
future AS (SELECT DISTINCT patient_id FROM {fq}.appointments WHERE status = 'Scheduled'),
at_risk AS (
  SELECT cp.location_id, COUNT(*) AS at_risk_patients
  FROM {fq}.care_plans cp
  LEFT ANTI JOIN future f ON cp.patient_id = f.patient_id
  CROSS JOIN ref
  WHERE cp.status = 'Active' AND datediff(ref.as_of, cp.last_visit_date) > 1.5 * cp.cadence_days
  GROUP BY cp.location_id),
lead_stats AS (
  SELECT l.assigned_location_id AS location_id,
         AVG(CAST(l.converted_flag AS DOUBLE)) AS lead_conversion_rate,
         percentile_approx(l.first_response_hours, 0.5) AS median_response_hours,
         COUNT(*) * 365D / 335 AS leads_per_year
  FROM {fq}.leads l CROSS JOIN ref
  WHERE l.created_date BETWEEN date_sub(ref.as_of, 365) AND date_sub(ref.as_of, 30)
  GROUP BY l.assigned_location_id),
appt_stats AS (
  SELECT a.location_id,
         AVG(CASE WHEN a.status = 'No-Show' THEN 1D ELSE 0D END) AS no_show_rate,
         COUNT(*) AS appointments_per_year
  FROM {fq}.appointments a CROSS JOIN ref
  WHERE a.status <> 'Scheduled' AND a.appointment_date > date_sub(ref.as_of, 365)
  GROUP BY a.location_id),
chiro_appts AS (
  SELECT a.location_id, a.provider_id,
         CASE WHEN a.appointment_time < '13:00' THEN 'AM' ELSE 'PM' END AS daypart
  FROM {fq}.appointments a
  JOIN {fq}.providers p ON a.provider_id = p.provider_id AND p.specialty = 'Chiropractor'
  CROSS JOIN ref
  WHERE a.status <> 'Scheduled' AND a.appointment_date > date_sub(ref.as_of, 365)),
util AS (
  -- Capacity: 10 half-hour slots per daypart per working chiropractor, 261 weekdays a year.
  SELECT location_id,
         SUM(CASE WHEN daypart = 'AM' THEN 1 ELSE 0 END)
           / (COUNT(DISTINCT provider_id) * 10D * 261) AS am_utilization,
         SUM(CASE WHEN daypart = 'PM' THEN 1 ELSE 0 END)
           / (COUNT(DISTINCT CASE WHEN daypart = 'PM' THEN provider_id END) * 10D * 261) AS pm_utilization,
         COUNT(DISTINCT provider_id) * 10D * 261 AS am_capacity,
         COUNT(DISTINCT CASE WHEN daypart = 'PM' THEN provider_id END) * 10D * 261 AS pm_capacity
  FROM chiro_appts GROUP BY location_id),
base AS (
  SELECT l.location_id, l.location_name, l.city, l.state, l.region,
         r.annual_revenue, r.annual_visits, p.plan_completion_rate, p.closed_plans_per_year,
         COALESCE(ar.at_risk_patients, 0) AS at_risk_patients,
         ls.lead_conversion_rate, ls.median_response_hours, ls.leads_per_year,
         s.no_show_rate, s.appointments_per_year,
         u.am_utilization, u.pm_utilization, u.am_capacity, u.pm_capacity
  FROM {fq}.locations l
  LEFT JOIN rev r ON l.location_id = r.location_id
  LEFT JOIN plans p ON l.location_id = p.location_id
  LEFT JOIN at_risk ar ON l.location_id = ar.location_id
  LEFT JOIN lead_stats ls ON l.location_id = ls.location_id
  LEFT JOIN appt_stats s ON l.location_id = s.location_id
  LEFT JOIN util u ON l.location_id = u.location_id),
med AS (
  SELECT percentile_approx(plan_completion_rate, 0.5) AS med_completion,
         percentile_approx(lead_conversion_rate, 0.5) AS med_conversion,
         percentile_approx(median_response_hours, 0.5) AS med_response_hours,
         percentile_approx(no_show_rate, 0.5) AS med_no_show,
         percentile_approx(am_utilization, 0.5) AS med_am_util,
         percentile_approx(pm_utilization, 0.5) AS med_pm_util
  FROM base),
patient_value AS (
  -- Lifetime revenue per patient, split by whether their first plan was completed.
  SELECT p.patient_id, SUM(v.revenue) AS revenue,
         MAX(CASE WHEN cp.status = 'Completed' THEN 1 ELSE 0 END) AS completed_a_plan,
         MAX(CASE WHEN cp.status = 'Dropped' THEN 1 ELSE 0 END) AS dropped_a_plan
  FROM {fq}.patients p
  JOIN {fq}.visits v ON p.patient_id = v.patient_id
  JOIN {fq}.care_plans cp ON p.patient_id = cp.patient_id
  GROUP BY p.patient_id),
unit_value AS (
  -- Network-wide dollar values used to price each gap.
  SELECT (SELECT SUM(revenue) / COUNT(*) FROM {fq}.visits) AS avg_visit_revenue,
         (SELECT AVG(CASE WHEN completed_a_plan = 1 THEN revenue END)
                 - AVG(CASE WHEN dropped_a_plan = 1 AND completed_a_plan = 0 THEN revenue END)
          FROM patient_value) AS value_of_a_completion,
         (SELECT SUM(revenue) / COUNT(DISTINCT patient_id) FROM {fq}.visits) AS revenue_per_patient,
         -- The inputs behind those values, so the app can show its math.
         (SELECT SUM(revenue) FROM {fq}.visits) AS all_visit_revenue,
         (SELECT COUNT(*) FROM {fq}.visits) AS all_visits,
         (SELECT COUNT(DISTINCT patient_id) FROM {fq}.visits) AS all_patients,
         (SELECT AVG(CASE WHEN completed_a_plan = 1 THEN revenue END) FROM patient_value) AS completer_revenue,
         (SELECT AVG(CASE WHEN dropped_a_plan = 1 AND completed_a_plan = 0 THEN revenue END)
          FROM patient_value) AS dropper_revenue),
priced AS (
  SELECT b.*, m.*, v.*,
         -- Gaps inside a tolerance band are normal clinic-to-clinic variation and price at $0.
         GREATEST(0, m.med_completion - b.plan_completion_rate - 0.03) * b.closed_plans_per_year
           * v.value_of_a_completion AS retention_revenue_at_stake,
         GREATEST(0, m.med_conversion - b.lead_conversion_rate - 0.02) * b.leads_per_year
           * v.revenue_per_patient AS leads_revenue_at_stake,
         (GREATEST(0, m.med_am_util - b.am_utilization - 0.10) * b.am_capacity
           + GREATEST(0, m.med_pm_util - b.pm_utilization - 0.10) * b.pm_capacity
           + GREATEST(0, b.no_show_rate - m.med_no_show - 0.02) * b.appointments_per_year)
           * v.avg_visit_revenue AS capacity_revenue_at_stake
  FROM base b CROSS JOIN med m CROSS JOIN unit_value v)
SELECT *,
       retention_revenue_at_stake + leads_revenue_at_stake + capacity_revenue_at_stake AS total_revenue_at_stake,
       CASE GREATEST(retention_revenue_at_stake, leads_revenue_at_stake, capacity_revenue_at_stake)
         WHEN retention_revenue_at_stake THEN 'retention'
         WHEN leads_revenue_at_stake THEN 'leads'
         ELSE 'capacity' END AS largest_lever,
       ROW_NUMBER() OVER (ORDER BY retention_revenue_at_stake + leads_revenue_at_stake
                                   + capacity_revenue_at_stake DESC) AS stake_rank
FROM priced
