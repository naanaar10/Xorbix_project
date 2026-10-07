-- Agent output tables. Created once; each agent run appends. Statements are separated by the @@ marker line.

CREATE TABLE IF NOT EXISTS {fq}.agent_runs (
  run_id STRING, started_at TIMESTAMP, finished_at TIMESTAMP, model STRING, trigger STRING,
  clinics_investigated INT, actions_queued INT, mlflow_experiment_id STRING, mlflow_trace_id STRING,
  status STRING, summary STRING)
COMMENT 'One row per Growth Director run.';

-- @@
CREATE TABLE IF NOT EXISTS {fq}.clinic_diagnoses (
  run_id STRING, location_id STRING, problem_type STRING, root_cause STRING, evidence STRING,
  revenue_at_stake DOUBLE, specialist STRING, recommended_fix STRING, created_at TIMESTAMP)
COMMENT 'Reason + Decide: the Director''s root-cause diagnosis per clinic and the specialist it assigned.';

-- @@
CREATE TABLE IF NOT EXISTS {fq}.action_queue (
  action_id STRING, run_id STRING, location_id STRING, specialist STRING, target_type STRING,
  target_id STRING, care_plan_id STRING, arm STRING, signal STRING, intervention STRING,
  channel STRING, message STRING, offered_slot STRING, rationale STRING, expected_value DOUBLE,
  status STRING, created_at TIMESTAMP, reviewed_at TIMESTAMP, reviewer_note STRING)
COMMENT 'Act: actions drafted by specialist agents, plus holdout and generic-reminder control arms. Staff approve or reject in the app.';

-- @@
CREATE TABLE IF NOT EXISTS {fq}.action_outcomes (
  action_id STRING, run_id STRING, location_id STRING, target_id STRING, arm STRING,
  intervention STRING, signal STRING, returned BOOLEAN, recovered_revenue DOUBLE,
  simulated_at TIMESTAMP)
COMMENT 'Measure: simulated outcome of every action and control-arm patient (did they come back?).';

-- @@
CREATE TABLE IF NOT EXISTS {fq}.impact_summary (
  run_id STRING, arm STRING, patients BIGINT, patients_returned BIGINT, return_rate DOUBLE,
  recovered_revenue DOUBLE, lift_vs_holdout DOUBLE, annualized_network_revenue DOUBLE,
  simulated_at TIMESTAMP)
COMMENT 'Measure: return rate per arm (agent vs generic reminder vs holdout) and projected annual revenue.';

-- @@
CREATE TABLE IF NOT EXISTS {fq}.agent_steps (
  run_id STRING, agent STRING, step INT, kind STRING, name STRING, arguments STRING,
  result_preview STRING, created_at TIMESTAMP)
COMMENT 'Every tool call and final answer from every agent, for the app''s reasoning view (full traces are in MLflow).';
