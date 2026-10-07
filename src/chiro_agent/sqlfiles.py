"""Load the bundle's SQL files as individual statements for a given catalog.schema."""
import os

SQL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sql")


def statements(filename: str, fq: str) -> list[str]:
    with open(os.path.join(SQL_DIR, filename)) as f:
        text = f.read().replace("{fq}", fq)
    out = []
    for chunk in text.split("-- @@"):
        body = "\n".join(line for line in chunk.splitlines() if not line.strip().startswith("--"))
        body = body.strip().rstrip(";").strip()
        if body:
            out.append(body)
    return out
