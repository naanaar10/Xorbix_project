"""Runtime settings, passed in by bundle job parameters or app environment variables."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    catalog: str
    schema: str
    warehouse_id: str
    llm_endpoint: str
    experiment_id: str | None = None

    @property
    def fq(self) -> str:
        return f"{self.catalog}.{self.schema}"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            catalog=os.environ["CHIRO_CATALOG"],
            schema=os.environ["CHIRO_SCHEMA"],
            warehouse_id=os.environ["DATABRICKS_WAREHOUSE_ID"],
            llm_endpoint=os.environ["LLM_ENDPOINT"],
            experiment_id=os.environ.get("MLFLOW_EXPERIMENT_ID") or None,
        )
