"""Generate the synthetic clinic network into Delta tables, then verify the planted problems."""
import argparse
import os
import sys
from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql.types import (BooleanType, DateType, DoubleType, IntegerType, StringType,
                               StructField, StructType)


def _add_src_to_path(src_dir: str | None):
    here = src_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)


INT_COLUMNS = {"capacity_patients_per_day", "tenure_months", "lifetime_visit_count", "num_touchpoints",
               "lead_time_days", "impressions", "clicks", "leads_generated", "conversions",
               "prescribed_visits", "cadence_days", "visits_completed", "dropped_after_visit"}
DOUBLE_COLUMNS = {"monthly_lease_cost", "churn_risk_score", "first_response_hours", "revenue", "budget"}
BOOL_COLUMNS = {"active_flag", "converted_flag"}

TABLE_COMMENTS = {
    "locations": "Clinic locations and daily patient capacity.",
    "providers": "Chiropractors, massage therapists and PT assistants, one home clinic each.",
    "patients": "Patient roster (surrogate IDs only, no PHI); status from visit recency.",
    "leads": "Inbound inquiries with first-response time and conversion outcome.",
    "appointments": "Every booked appointment, including future Scheduled ones, with time and cancellation reason.",
    "visits": "Completed appointments with service and revenue.",
    "referrals": "Patient-to-lead referrals.",
    "marketing_campaigns": "Quarterly campaign spend and results by channel.",
    "care_plans": "Prescribed care plans: visits prescribed vs completed, cadence and status.",
    "open_slots": "Unbooked chiropractor appointment slots for the next 14 days.",
    "sim_ground_truth": "Simulator answer key (true dropout reasons). Used only to simulate outcomes; agents never read it.",
}


def spark_schema(columns: list[str]) -> StructType:
    def field(name):
        if name.endswith("_date"):
            t = DateType()
        elif name in INT_COLUMNS:
            t = IntegerType()
        elif name in DOUBLE_COLUMNS:
            t = DoubleType()
        elif name in BOOL_COLUMNS:
            t = BooleanType()
        else:
            t = StringType()
        return StructField(name, t, True)
    return StructType([field(c) for c in columns])


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--as-of", default="", help="YYYY-MM-DD; defaults to today")
    p.add_argument("--num-clinics", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--src-dir", default=None)
    return p.parse_args()


def main():
    args = parse_args()
    _add_src_to_path(args.src_dir)
    from chiro_agent.datagen import COLUMNS, SimConfig, simulate_network

    spark = SparkSession.builder.getOrCreate()
    fq = f"{args.catalog}.{args.schema}"
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    cfg = SimConfig(as_of=as_of, seed=args.seed, num_clinics=args.num_clinics)
    written: set[str] = set()

    def write(table: str, rows: list[tuple]):
        if not rows:
            return
        df = spark.createDataFrame(rows, schema=spark_schema(COLUMNS[table]))
        mode = "append" if table in written else "overwrite"
        df.write.mode(mode).option("overwriteSchema", "true").saveAsTable(f"{fq}.{table}")
        written.add(table)
        print(f"{table}: wrote {len(rows):,} rows ({mode})")

    data = simulate_network(cfg, on_chunk=write)
    for table, rows in data.items():
        write(table, rows)
    spark.sql(f"""CREATE OR REPLACE TABLE {fq}.network_metadata
                  COMMENT 'Reference date the data was simulated as of; tools measure recency from it.'
                  AS SELECT DATE'{as_of}' AS as_of, {args.seed} AS seed, {args.num_clinics} AS num_clinics,
                            current_timestamp() AS generated_at""")
    for table, comment in TABLE_COMMENTS.items():
        spark.sql(f"COMMENT ON TABLE {fq}.{table} IS '{comment}'")

    validate(spark, fq, as_of)


def validate(spark, fq: str, as_of: date):
    """Fail the job if the data lost the patterns the agents are supposed to find."""
    def one(sql):
        return spark.sql(sql).collect()

    arr = one(f"""SELECT SUM(revenue) AS r FROM {fq}.visits
                 WHERE visit_date > date_sub(DATE'{as_of}', 365)""")[0]["r"]
    completion = one(f"""SELECT location_id, AVG(CASE WHEN status='Completed' THEN 1 ELSE 0 END) AS rate
                        FROM {fq}.care_plans WHERE status IN ('Completed','Dropped')
                        GROUP BY location_id ORDER BY rate""")
    conversion = one(f"""SELECT assigned_location_id AS location_id, AVG(CAST(converted_flag AS INT)) AS rate
                        FROM {fq}.leads WHERE created_date < date_sub(DATE'{as_of}', 30)
                        GROUP BY 1 ORDER BY rate""")
    no_show = one(f"""SELECT location_id, AVG(CASE WHEN status='No-Show' THEN 1 ELSE 0 END) AS rate
                     FROM {fq}.appointments WHERE status <> 'Scheduled'
                     GROUP BY location_id ORDER BY rate DESC""")
    print(f"Trailing-12 revenue: ${arr / 1e6:.1f}M")
    print(f"Lowest completion:  {completion[0]['location_id']} {completion[0]['rate']:.1%} "
          f"(best {completion[-1]['location_id']} {completion[-1]['rate']:.1%})")
    print(f"Lowest conversion:  {conversion[0]['location_id']} {conversion[0]['rate']:.1%}")
    print(f"Highest no-show:    {no_show[0]['location_id']} {no_show[0]['rate']:.1%}")
    checks = {
        "revenue ~$100M": 90e6 <= arr <= 115e6,
        "LOC007 lowest completion": completion[0]["location_id"] == "LOC007",
        "LOC003 highest completion": completion[-1]["location_id"] == "LOC003",
        "LOC012 lowest conversion": conversion[0]["location_id"] == "LOC012",
        "LOC019 highest no-show": no_show[0]["location_id"] == "LOC019",
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise AssertionError(f"Planted patterns missing: {failed}")
    print("All planted patterns verified.")


if __name__ == "__main__":
    main()
