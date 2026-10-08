"""Reason, Decide, Act: the Manager agent investigates the clinics with the most revenue at
stake and dispatches specialist agents, which queue actions for staff approval."""
import argparse
import json
import sys


def main():
    p = argparse.ArgumentParser()
    for name in ("--catalog", "--schema", "--warehouse-id", "--llm-endpoint", "--experiment-id", "--src-dir"):
        p.add_argument(name, required=True)
    p.add_argument("--clinics-per-run", type=int, default=3)
    p.add_argument("--max-agent-patients", type=int, default=20)
    p.add_argument("--max-at-risk", type=int, default=120)
    p.add_argument("--only-clinic", default="")
    p.add_argument("--trigger", default="scheduled")
    args = p.parse_args()
    sys.path.insert(0, args.src_dir)

    import mlflow
    from databricks.sdk import WorkspaceClient
    from chiro_agent.config import Settings
    from chiro_agent.director import build_context, run_growth_director

    mlflow.set_experiment(experiment_id=args.experiment_id)
    mlflow.openai.autolog()
    settings = Settings(args.catalog, args.schema, args.warehouse_id, args.llm_endpoint, args.experiment_id)
    ctx = build_context(settings, WorkspaceClient(), max_at_risk=args.max_at_risk,
                        max_agent_patients=args.max_agent_patients)
    result = run_growth_director(ctx, clinics_per_run=args.clinics_per_run,
                                 only_clinic=args.only_clinic or None, trigger=args.trigger)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
