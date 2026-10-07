"""Growth Director app: what the agents found, what they queued, whether it worked, and how
they decided. Staff approve outreach here, and anyone can run the Director live on one clinic."""
from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Growth Director", layout="wide")

import data  # noqa: E402
import style  # noqa: E402
from spine import FLAG_ABOVE, spine_svg  # noqa: E402

st.markdown(style.CSS, unsafe_allow_html=True)

GOAL = 250e6
ARM_LABELS = {"agent": "Agent-chosen outreach", "generic": "Generic reminder",
              "holdout": "No outreach (holdout)"}
STEP_PHRASES = {
    "get_network_kpis": "Read the network's KPIs and revenue at stake",
    "compare_clinic_to_network": "Compared {clinic_id} with the network",
    "get_dropoff_by_visit_number": "Checked where {clinic_id} patients drop out",
    "get_cancellation_reasons": "Read why {clinic_id} appointments get cancelled",
    "get_provider_breakdown": "Broke {clinic_id} down by chiropractor",
    "get_lead_response_stats": "Checked how fast {clinic_id} answers leads",
    "get_capacity_by_daypart": "Compared mornings and afternoons at {clinic_id}",
    "record_diagnosis": "Recorded the diagnosis for {location_id}",
    "assign_specialist": "Handed {location_id} to the {specialist} specialist",
    "find_at_risk_patients": "Found patients going quiet at {clinic_id}",
    "get_patient_history": "Read the visit history of {patient_id_in}",
    "find_open_slots": "Looked for open slots at {clinic_id}",
    "queue_action": "Queued {intervention} for {target_id}",
    "get_stale_leads": "Pulled open leads at {clinic_id}",
    "find_reactivation_candidates": "Found lapsed patients at {clinic_id}",
    "get_intervention_performance": "Checked which interventions worked before",
    "final": "Finished",
    "reminder": "Reminded to finish the hand-off",
}
WRITE_TOOLS = {"record_diagnosis", "assign_specialist", "queue_action"}


def money(x: float) -> str:
    if x is None or pd.isna(x):
        return "$0"
    return f"${x / 1e6:.1f}M" if abs(x) >= 1e6 else f"${x / 1e3:.0f}K"


def phrase(name: str, arguments: str) -> str:
    import json
    try:
        args = json.loads(arguments) if arguments and arguments.startswith("{") else {}
    except ValueError:
        args = {}
    template = STEP_PHRASES.get(name, name)
    try:
        return template.format(**{k: v for k, v in args.items()})
    except (KeyError, IndexError):
        return template.split(" {")[0] if "{" in template else template


# ---------------------------------------------------------------- live run
def run_live(clinic: str, patients: int) -> None:
    import mlflow
    from chiro_agent.director import build_context, run_growth_director
    from chiro_agent.measure import measure_unmeasured_runs

    s = data.settings()
    if s.experiment_id:
        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(experiment_id=s.experiment_id)
    mlflow.openai.autolog()
    ctx = build_context(s, data.workspace(), max_at_risk=40, max_agent_patients=patients, max_followups=4)
    with st.status(f"The Director is investigating {clinic}", expanded=True) as status:
        def on_step(step: dict) -> None:
            ctx.steps.append(step)
            who = step["agent"].split(":")[0]
            status.write(f"**{who.capitalize()}**: {phrase(step['name'], step.get('arguments', ''))}")
        ctx.add_step = on_step
        result = run_growth_director(ctx, only_clinic=clinic, trigger="app")
        status.update(label="Simulating outcomes", state="running")
        measure_unmeasured_runs(ctx.wh, s.fq)
        status.update(label=f"Done. {result['actions_queued']} actions queued for {clinic}.", state="complete")
    data.refresh()
    st.session_state["run_id"] = result["run_id"]


# ---------------------------------------------------------------- sidebar
runs = data.runs()
kpis = data.kpis()
flagged = kpis[kpis.total_revenue_at_stake >= FLAG_ABOVE]

with st.sidebar:
    st.subheader("Run the Director")
    st.caption("Investigate one clinic now and watch each step as it happens.")
    clinic_options = list(kpis.location_id)
    clinic = st.selectbox("Clinic", clinic_options,
                          index=clinic_options.index(flagged.location_id.iloc[0]) if len(flagged) else 0,
                          format_func=lambda c: f"{c} {kpis.set_index('location_id').city[c]}")
    patients = st.slider("Patients to review individually", 2, 8, 4,
                         help="Only applies when the clinic's problem is retention.")
    go = st.button("Run the Director", type="primary", width="stretch")

    st.divider()
    st.subheader("Showing")
    if runs.empty:
        run_id = None
        st.caption("No runs yet. Run the Director, or the nightly job.")
    else:
        labels = {r.run_id: f"{pd.to_datetime(r.started_at):%b %d, %H:%M} ({r.trigger}, {r.clinics_investigated} clinics)"
                  for r in runs.itertuples()}
        ids = list(labels)
        default = st.session_state.get("run_id", ids[0])
        run_id = st.selectbox("Run", ids, index=ids.index(default) if default in ids else 0,
                              format_func=labels.get, label_visibility="collapsed")
    st.caption(f"Model: {data.settings().llm_endpoint}")

# ---------------------------------------------------------------- header + spine
st.markdown("<h1>Growth Director</h1>", unsafe_allow_html=True)
st.markdown('<p class="lede">An agent that finds where the clinic network is losing revenue, works out '
            'why, and queues the fix for staff to approve.</p>', unsafe_allow_html=True)

if go:
    run_live(clinic, patients)
    st.rerun()

network_revenue = kpis.annual_revenue.sum()
st.markdown(style.html_block(f'<p class="headline">{len(flagged)} of {len(kpis)} clinics are out of alignment</p>'
            f'<p class="subline">Together they leave {money(flagged.total_revenue_at_stake.sum())} a year on the '
            f'table. The network does {money(network_revenue)} a year against a {money(GOAL)} goal.</p>'),
            unsafe_allow_html=True)
st.markdown(style.html_block(spine_svg(kpis.to_dict("records"))), unsafe_allow_html=True)

tabs = st.tabs(["What's happening", "Why", "What we're doing", "Did it work", "How the agent decided"])

# ---------------------------------------------------------------- observe
with tabs[0]:
    st.caption("Every clinic, ranked by the revenue it is leaving on the table. Rebuilt at the start of each run.")
    view = kpis.rename(columns={
        "location_id": "Clinic", "city": "City", "annual_revenue": "Revenue / yr",
        "total_revenue_at_stake": "At stake / yr", "largest_lever": "Biggest lever",
        "plan_completion_rate": "Plan completion", "lead_conversion_rate": "Lead conversion",
        "median_response_hours": "Lead reply (hrs)", "no_show_rate": "No-shows",
        "pm_utilization": "Afternoons booked", "at_risk_patients": "Patients going quiet"})
    cols = ["Clinic", "City", "At stake / yr", "Biggest lever", "Revenue / yr", "Plan completion",
            "Lead conversion", "Lead reply (hrs)", "No-shows", "Afternoons booked", "Patients going quiet"]
    view.loc[view["At stake / yr"] < FLAG_ABOVE, "Biggest lever"] = ""
    view["At stake / yr"] = (view["At stake / yr"] / 1e3).round()
    view["Revenue / yr"] = view["Revenue / yr"] / 1e6
    for c in ("Plan completion", "Lead conversion", "No-shows", "Afternoons booked"):
        view[c] = view[c] * 100
    pct = st.column_config.NumberColumn(format="%.0f%%")
    st.dataframe(view[cols], hide_index=True, width="stretch", height=420, column_config={
        "Revenue / yr": st.column_config.NumberColumn(format="$%.2fM"),
        "At stake / yr": st.column_config.NumberColumn(format="$%dK"),
        "Plan completion": pct, "Lead conversion": pct, "No-shows": pct, "Afternoons booked": pct,
        "Lead reply (hrs)": st.column_config.NumberColumn(format="%.1f")})

if run_id is None:
    for t in tabs[1:]:
        with t:
            st.info("Run the Director to see diagnoses, actions and results here.")
    st.stop()

# ---------------------------------------------------------------- reason + decide
with tabs[1]:
    dx = data.diagnoses(run_id)
    if dx.empty:
        st.info("This run recorded no diagnoses.")
    for d in dx.itertuples():
        st.markdown(style.html_block(f"""
<div class="case">
  <div class="who"><span>{html.escape(d.location_id)} {html.escape(d.city)}: {html.escape(d.problem_type)}</span>
    <span class="stake">{money(d.revenue_at_stake)} a year at stake</span></div>
  <p class="agent-voice">{html.escape(d.root_cause)}</p>
  <div class="evidence">Evidence: {html.escape(d.evidence)}</div>
  <div class="fix">Recommended fix: {html.escape(d.recommended_fix)}</div>
  <div class="handoff">Handed to the {html.escape(d.specialist)} specialist</div>
</div>"""), unsafe_allow_html=True)

# ---------------------------------------------------------------- act
with tabs[2]:
    acts = data.actions(run_id)
    if acts.empty:
        st.info("No actions in this run.")
    else:
        agent = acts[acts.arm == "agent"].copy()
        controls = acts[acts.arm != "agent"]
        st.markdown(f"**{len(agent)} actions drafted by specialists** wait for staff approval. "
                    f"{len(controls)} more patients were set aside at random as control groups "
                    f"({(controls.arm == 'generic').sum()} get a generic reminder, "
                    f"{(controls.arm == 'holdout').sum()} get nothing) so the agent's impact can be measured.")
        editor = st.data_editor(
            agent[["action_id", "status", "location_id", "specialist", "target_id", "intervention", "channel",
                   "offered_slot", "message", "rationale"]],
            hide_index=True, width="stretch", key=f"editor-{run_id}", height=420,
            disabled=["action_id", "location_id", "specialist", "target_id", "intervention", "channel",
                      "offered_slot", "rationale"],
            column_config={
                "action_id": None,
                "status": st.column_config.SelectboxColumn("Decision", options=["Pending", "Approved", "Rejected"], width="small"),
                "location_id": "Clinic", "specialist": "Specialist", "target_id": "Patient or lead",
                "intervention": "Outreach", "channel": "Channel", "offered_slot": "Offered slot",
                "message": st.column_config.TextColumn("Message (editable)", width="large"),
                "rationale": st.column_config.TextColumn("Why the agent chose this", width="large")})
        changed = editor.merge(agent[["action_id", "status", "message"]], on="action_id", suffixes=("", "_old"))
        changed = changed[(changed.status != changed.status_old) | (changed.message != changed.message_old)]
        if st.button(f"Save {len(changed)} decisions" if len(changed) else "Save decisions",
                     disabled=changed.empty):
            data.save_decisions(changed[["action_id", "status", "message"]].to_dict("records"))
            st.success(f"Saved {len(changed)} decisions.")
            st.rerun()

# ---------------------------------------------------------------- measure
with tabs[3]:
    imp = data.impact(run_id)
    if imp.empty:
        st.info("No measured retention outreach in this run yet. Outcomes appear after the measure step.")
    else:
        imp["label"] = imp.arm.map(ARM_LABELS)
        imp["text"] = [f"{r:.0%} ({n} of {p})" for r, n, p in zip(imp.return_rate, imp.patients_returned, imp.patients)]
        agent_row = imp[imp.arm == "agent"].iloc[0] if (imp.arm == "agent").any() else None
        if agent_row is not None:
            st.markdown(style.html_block(f"""
<div class="metric-row">
  <div><div class="value">{agent_row.lift_vs_holdout * 100:+.0f} pts</div><div class="label">more patients came back than with no outreach</div></div>
  <div><div class="value">{money(imp.recovered_revenue.sum())}</div><div class="label">recovered in this run</div></div>
  <div><div class="value">{money(agent_row.annualized_network_revenue)}</div><div class="label">a year if every silent dropout in the network got this</div></div>
</div>"""), unsafe_allow_html=True)
        order = [ARM_LABELS[a] for a in ("agent", "generic", "holdout")]
        base = alt.Chart(imp).encode(
            y=alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelFontSize=14, labelLimit=260, ticks=False, domain=False)),
            x=alt.X("return_rate:Q", title="Share of patients who came back",
                    axis=alt.Axis(format="%", grid=True, gridColor="#D5DDDB", domain=False, tickCount=5),
                    scale=alt.Scale(domain=[0, max(0.5, float(imp.return_rate.max()) * 1.25)])))
        bars = base.mark_bar(cornerRadiusEnd=4, height=26).encode(
            color=alt.condition(alt.datum.arm == "agent", alt.value(style.INDIGO), alt.value(style.SLATE)),
            tooltip=[alt.Tooltip("label:N", title="Group"), alt.Tooltip("return_rate:Q", title="Came back", format=".0%"),
                     alt.Tooltip("patients:Q", title="Patients"), alt.Tooltip("recovered_revenue:Q", title="Recovered", format="$,.0f")])
        labels = base.mark_text(align="left", dx=6, fontSize=14, color=style.INK).encode(text="text:N")
        st.altair_chart((bars + labels).properties(height=170).configure_view(strokeWidth=0)
                        .configure(background="transparent", font="Familjen Grotesk"), width="stretch")
        st.caption("Outcomes are simulated: outreach is not really sent. Each patient has a hidden reason for "
                   "stopping that no agent can see, and outreach that fits that reason is more likely to bring "
                   "them back.")
        with st.expander("See the numbers and the assumptions"):
            st.dataframe(imp[["label", "patients", "patients_returned", "return_rate", "recovered_revenue"]]
                         .rename(columns={"label": "Group", "patients": "Patients", "patients_returned": "Came back",
                                          "return_rate": "Rate", "recovered_revenue": "Recovered ($)"}),
                         hide_index=True, width="stretch")
            from chiro_agent.measure import INTERVENTION_COLUMN, RETURN_PROBABILITY
            st.caption("Chance a patient comes back, by their hidden reason (rows) and the outreach they get (columns).")
            st.dataframe(pd.DataFrame(RETURN_PROBABILITY, index=list(INTERVENTION_COLUMN)).T, width="stretch")

# ---------------------------------------------------------------- reasoning
with tabs[4]:
    run = runs.set_index("run_id").loc[run_id]
    if run.summary:
        st.markdown(style.html_block(f'<p class="agent-voice">{html.escape(run.summary)}</p>'), unsafe_allow_html=True)
    host = data.workspace().config.host.rstrip("/")
    if run.mlflow_experiment_id:
        st.markdown(f"Full traces, with every prompt and tool result, are in "
                    f"[MLflow]({host}/ml/experiments/{run.mlflow_experiment_id}/traces).")
    st_rows = data.steps(run_id)
    show_patients = st.toggle("Show individual patient reviews", value=False)
    if not show_patients:
        st_rows = st_rows[~st_rows.agent.str.startswith("retention:")]
    body = []
    for s in st_rows.itertuples():
        who = s.agent.split(":")[0].capitalize()
        cls = "step write" if s.name in WRITE_TOOLS else "step"
        body.append(f'<div class="{cls}"><span class="agent">{html.escape(who)}</span>'
                    f'<span class="what">{html.escape(phrase(s.name, s.arguments))}</span></div>')
    st.markdown(style.html_block("".join(body)), unsafe_allow_html=True)
