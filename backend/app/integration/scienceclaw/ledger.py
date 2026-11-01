"""Append-only, hash-chained evidence ledger (spec 2.1, 12.1).

The bus transports results without letting one worker overwrite another's
output. That is enforced structurally here: the only public mutation is
`append`, records are written as JSON Lines, and each record carries the digest
of the one before it, so a silent edit of an earlier line breaks verification.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .contracts import AgentEvent, ContractViolation, canonical_digest

GENESIS = "0" * 64


class AppendOnlyLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._claimed: set[tuple[str, str]] = set()
        if self.path.exists():
            for event in self.events():
                self._claimed.add((event["agent"], event.get("candidate_id") or ""))

    # -- writing -----------------------------------------------------------

    def append(self, event: AgentEvent) -> str:
        """Append one event and return its chained digest."""
        with self._lock:
            prev = self._last_digest()
            body = event.to_json()
            record = {"prev": prev, "event": body}
            record["digest"] = canonical_digest(record)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
            self._claimed.add((event.agent, event.candidate_id or ""))
            return record["digest"]

    def claim(self, agent: str, candidate_id: str | None) -> None:
        """Reserve an (agent, candidate) output slot.

        A second agent attempting to emit evidence for a slot already owned by a
        different agent is a contract violation, not a last-write-wins update.
        """
        key = (agent, candidate_id or "")
        if key in self._claimed:
            raise ContractViolation(
                f"{agent} already produced evidence for candidate {candidate_id!r}; "
                "evidence artifacts are immutable"
            )

    # -- reading -----------------------------------------------------------

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def events(self) -> list[dict]:
        return [r["event"] for r in self.read_all()]

    def by_agent(self, agent: str) -> list[dict]:
        return [e for e in self.events() if e["agent"] == agent]

    def _last_digest(self) -> str:
        records = self.read_all()
        return records[-1]["digest"] if records else GENESIS

    # -- integrity ---------------------------------------------------------

    def verify(self) -> tuple[bool, str | None]:
        """Recompute the chain. Returns (ok, first_failure_description)."""
        prev = GENESIS
        for i, rec in enumerate(self.read_all()):
            if rec["prev"] != prev:
                return False, f"record {i}: prev digest does not match chain"
            expected = canonical_digest({"prev": rec["prev"], "event": rec["event"]})
            if rec["digest"] != expected:
                return False, f"record {i}: body modified after write (digest mismatch)"
            prev = rec["digest"]
        return True, None
