"""Test doubles for the SQL warehouse."""
import re
import threading


class FakeWarehouse:
    """Answers each statement by its /* name */ tag and records every call (thread-safe)."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls = []
        self._lock = threading.Lock()

    def query(self, sql, params=None):
        match = re.search(r"/\* (\w+) \*/", sql)
        name = match.group(1) if match else None
        with self._lock:
            self.calls.append({"name": name, "sql": sql, "params": dict(params or {})})
        return [dict(r) for r in self.answers.get(name, [])]

    def called(self, name):
        return [c for c in self.calls if c["name"] == name]
