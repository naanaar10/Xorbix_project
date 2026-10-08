# Backbone

An agentic AI prototype on Databricks for a chiropractic clinic network that does about $100M a
year and wants to reach $250M. Every night Backbone's **Manager** agent works out which clinics
are losing the most revenue, investigates why, and hands each problem to a **specialist agent**
that drafts concrete outreach for staff to approve. Two more specialists then work on the whole
network: **Marketing** moves budget to the channels that win patients cheapest, and **Loyalty**
offers Wellness plans and asks for referrals when a patient finishes care. Results are measured
against randomized control groups.

Built for the Xorbix × University of Iowa Databricks hackathon on Databricks Free Edition.
All data is synthetic.

## What it does

| Step | What happens | Where |
|---|---|---|
| **Observe** | Rebuild a per-clinic KPI snapshot and price each gap in dollars a year (retention, leads, capacity). | `observe` task, `clinic_kpis` table |
| **Reason** | The Manager reads the snapshot, picks the clinics with the most revenue at stake, and drills into each with tools until it can name the root cause (a step, a provider, a time of day). | `reason_decide_act` task |
| **Decide** | It records the diagnosis and assigns a specialist: Retention, Leads or Capacity. Then it hands the whole network to the Marketing and Loyalty specialists. | `clinic_diagnoses` table |
| **Act** | The specialist reviews patients or leads one by one and queues outreach (a specific open slot, a membership offer, a speed-to-lead call, a Wellness plan, a referral ask...) or a marketing budget move priced by a tool. Staff approve, edit or skip each one in the app. | `action_queue` table, app |
| **Measure** | At-risk patients are randomized before any agent sees them: 20% get nothing (holdout), 20% a generic reminder, 60% agent-chosen outreach. Outcomes are simulated and compared. | `measure` task, `impact_summary` table |

What makes it agentic rather than a dashboard:

- The Manager chooses which clinics to investigate and which tools to call, and keeps digging
  until it can prove a root cause. The tools return numbers; the model never does arithmetic.
- Specialists are sub-agents the Manager dispatches through a tool call (`assign_specialist`).
- The retention specialist reasons about each patient individually from their signals (last
  cancellation reason, payment type, provider schedule) and picks a different outreach for each.
- The Marketing specialist proposes budget moves; a UC function (`price_budget_shift`) prices each
  one and the write tool refuses moves that break the caps (a channel loses at most a quarter of
  its budget, and at most doubles).
- The Loyalty specialist decides per patient who just finished a care plan: Wellness plan offer,
  referral ask, or both.
- Past results feed back in through `get_intervention_performance`.
- Every run is traced in MLflow: each model call and tool call, with inputs and outputs.

## Architecture

```
generate_data job ──► 11 Delta tables (Unity Catalog schema)
                         │
growth_director job      ▼
  observe ──────────► clinic_kpis + 17 agent tools as UC table functions
  reason_decide_act ─► Manager ──assign_specialist──► Retention / Leads / Capacity
                         └──── whole network ────────► Marketing / Loyalty
                         │                                   │
                         ▼                                   ▼
                    clinic_diagnoses                    action_queue ◄── staff approve (app)
  measure ──────────► action_outcomes + impact_summary
                         │
Databricks App ◄─────────┘  (also runs the Manager live on one clinic)
```

- **Agent tools** are Unity Catalog table functions (`src/sql/tools.sql`). The agents discover them
  from Unity Catalog at runtime: each function's comment becomes the tool description the model
  reads. Write actions (`record_diagnosis`, `assign_specialist`, `queue_action`, `queue_budget_shift`,
  `record_network_finding`) are Python.
- **Model**: a Databricks Foundation Model endpoint through its OpenAI-compatible API
  (default `databricks-gpt-oss-120b`, set by the `llm_endpoint` variable).
- **Agent loop**: a plain tool-calling loop (`src/chiro_agent/loop.py`), traced with MLflow.
- **App**: a small FastAPI server and one hand-written page (no build step) on Databricks Apps
  (`src/app/`). The 50 clinics are drawn as a spine. Five tabs: Overview (the Manager's summary,
  the path to $250M and a what-if planner whose sliders redraw it live), Clinics (every KPI for
  all 50, sortable; each clinic opens as a four-step story), Problems, Messages (approve, edit or
  skip every draft) and Results (agent vs plain reminder vs no message, with the outcome model's
  assumptions). All wording is written so a 10-year-old can follow it. "Run the Manager" runs the
  agent live on one clinic and shows each step as it happens. Every dollar figure has a "How we
  got this" breakdown: each step of the calculation with the real inputs, built by
  `src/app/explain.py` from the same values as the figure.

## The data

`generate_data` simulates 50 clinics and about 18 months of patient journeys (lead, first visit,
care plan, visits, completion or dropout), about 1.6M appointments and $100M of trailing-12-month
revenue. It keeps the 8 tables and column names of the Xorbix starter generator and adds
`care_plans`, `open_slots`, `network_metadata` and `sim_ground_truth`.

The starter data was drawn independently at random, so it had no patterns to find. This
generator plants four, and the job fails if any of them is missing:

| Clinic | Planted problem |
|---|---|
| LOC007 | A mornings-only chiropractor carries over half of new plans; their patients cancel with scheduling conflicts and drop out after visit 3 |
| LOC012 | Most leads wait over 24 hours for a first reply, so conversion is half the network's |
| LOC019 | Afternoons are less than half booked and no-shows are double the network's |
| LOC003 | Best practice: highest plan completion and wellness uptake |

No names, contact details, birthdates or clinical fields exist anywhere: people are surrogate IDs.

### Measurement assumptions

Outreach isn't really sent, so outcomes are simulated. Each patient who went quiet has a hidden
true reason for stopping (`sim_ground_truth`, which no agent tool reads). The chance they come
back depends on whether the outreach fits that reason; the table is in
`src/chiro_agent/measure.py`. Generic reminders and no outreach get the
same treatment, so the comparison between arms is fair.

## Setup

Requirements: a Databricks workspace (Free Edition works) and the
[Databricks CLI](https://docs.databricks.com/dev-tools/cli/install.html) v1.0 or later.

```bash
databricks auth login --host https://<your-workspace-url> --profile <name>
export DATABRICKS_CONFIG_PROFILE=<name>
```

## Validate, deploy and run

```bash
databricks bundle validate                # check the configuration
databricks bundle deploy                  # create the schema, jobs, app and MLflow experiment
databricks bundle run platform_check      # optional: confirm the workspace supports everything
databricks bundle run generate_data       # about 3 minutes; verifies the planted patterns
databricks bundle run growth_director     # about 5 minutes: observe, agents, measure
databricks bundle run chiro_growth_app    # start the app; the command prints its URL
```

Run `growth_director` after the app has been deployed at least once: its `observe` task grants
the app's service principal access to the schema.

The `dev` target (default) prefixes resource names with your user name and keeps the nightly
schedule paused.

## Deploy to another workspace

Nothing workspace-specific is in the code. Point the CLI at the other workspace and use the
`prod` target:

```bash
databricks auth login --host https://<other-workspace-url> --profile other
databricks bundle deploy -t prod -p other
databricks bundle run generate_data -t prod -p other
databricks bundle run chiro_growth_app -t prod -p other
databricks bundle run growth_director -t prod -p other
```

Override any variable with `--var`, for example a different catalog or model:

```bash
databricks bundle deploy -t prod -p other --var="catalog=main" --var="llm_endpoint=databricks-qwen35-122b-a10b"
```

| Variable | Default | Meaning |
|---|---|---|
| `catalog` | `workspace` | Unity Catalog catalog |
| `schema` | `chiro_growth` | Schema for data, tools and agent output |
| `warehouse_id` | looked up by name: `Serverless Starter Warehouse` | SQL warehouse for tools and the app |
| `llm_endpoint` | `databricks-gpt-oss-120b` | Model serving endpoint the agents call |
| `clinics_per_run` | `3` | Clinics the Manager investigates per run |
| `max_agent_patients` | `30` | Patients per clinic that get an individual agent review |


## Run the app on your machine

With the bundle deployed and the jobs run once:

```bash
scripts/run_app_locally.sh          # or: scripts/run_app_locally.sh prod
```

It reads the schema, warehouse, model and experiment from `databricks bundle summary` and uses
your CLI login. Open http://localhost:8000.

## Repository layout

```
databricks.yml            bundle: variables and targets
resources/                schema, jobs, app and MLflow experiment definitions
src/chiro_agent/          agent package: data generator, tools, loop, Manager, specialists, measure
src/sql/                  observe step, agent tools (UC functions), output tables
src/jobs/                 job entry points
src/app/                  Databricks App: server.py (API), static/ (the page), live.py (live runs),
                          explain.py (the math behind each figure)
scripts/                  run_app_locally.sh
tests/                    unit tests (generator, outcome model, app API); tests/js for the page
docs/design.md            design notes
```

## Tests

```bash
uv run --group dev pytest
node --test tests/js/*.test.mjs
```

The generator tests check that IDs link up, columns are consistent and every planted problem
stays findable. The measurement tests check that the outcome model rewards matching outreach to
the real reason. The app tests cover the queries, live-run events and API errors against a fake
warehouse.

## Credits

The data generator builds on the synthetic data notebook Xorbix Technologies provided at the
hackathon kickoff, keeping its tables and column names.
