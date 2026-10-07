# Sample data

There are no data files in this repository: the bundle generates everything synthetically.

- Generator: `src/chiro_agent/datagen.py` (pure Python, testable locally)
- Job that writes it to Delta and verifies the planted patterns: `src/jobs/generate_data.py`
- Run it: `databricks bundle run generate_data`

To look at the data locally without Databricks:

```bash
uv run --group dev python -c "
from datetime import date
from chiro_agent.datagen import SimConfig, simulate_network
data = simulate_network(SimConfig(as_of=date.today(), num_clinics=5, history_days=120))
print({table: len(rows) for table, rows in data.items()})"
```
