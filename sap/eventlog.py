"""Append-only, hash-chained event log.

Every recommendation, approval, command, measurement and verification is one
JSON line. Each line carries the SHA-256 of the previous line, so editing or
deleting history breaks the chain and is detected by `verify_chain`.
Works fully offline; lines are synced to the server when a link is available.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path


def _plain(o):
    if is_dataclass(o):
        return {k: _plain(v) for k, v in asdict(o).items()}
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return o


class EventLog:
    GENESIS = "0" * 64

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last = self.GENESIS
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    self._last = json.loads(line)["hash"]

    def append(self, kind: str, payload, actor: str = "controller", ts: float | None = None) -> dict:
        body = {"ts": ts if ts is not None else time.time(), "kind": kind, "actor": actor,
                "payload": _plain(payload), "prev": self._last}
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        rec = {**body, "hash": digest}
        with self.path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self._last = digest
        return rec

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]

    def verify_chain(self) -> tuple[bool, int | None]:
        prev = self.GENESIS
        for i, rec in enumerate(self.records()):
            body = {k: rec[k] for k in ("ts", "kind", "actor", "payload", "prev")}
            if rec["prev"] != prev or hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != rec["hash"]:
                return False, i
            prev = rec["hash"]
        return True, None
