"""The semantic classifier: the model ARG-025 was waiting for (ARG-055).

It fills the `ClassificationModel` interface of Phase 03 without touching it. The inventory keeps
calling `propose(columns)`, keeps its thresholds and keeps its review queue; what it receives now is
a proposal whose confidence has been **calibrated** against the DPO's own decisions (see
`calibration`). Only metadata travels: name, type, table and sibling names, never a value.

The prompt lives in a versioned file and its SHA-256 goes with the classifier, because changing the
prompt is changing the classifier, and the calibration curves have to be refitted afterwards.
"""

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml

from argos_ai.classify.calibration import Calibrator
from argos_ai.gateway import Gateway
from argos_inventory.classify.assisted import ColumnContext, Proposal

PROMPT_FILE = Path(__file__).resolve().parents[4] / "library" / "prompts" / "classify.yaml"
SERVICE = "inventory"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "category", "confidence"],
                "properties": {
                    "key": {"type": "string"},
                    "category": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


class SemanticClassifier:
    """`ClassificationModel` of ARG-025, served through the gateway and calibrated."""

    def __init__(
        self,
        gateway: Gateway,
        calibrator: Calibrator,
        record: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        raw = PROMPT_FILE.read_bytes()
        self._system = str(yaml.safe_load(raw.decode("utf-8"))["system"])
        self._gateway = gateway
        self._calibrator = calibrator
        # Where the declared confidence goes. The review queue of ARG-025 keeps the calibrated
        # one —it is what the triage used— and fitting the next curve on that would feed the
        # calibration its own output. So the declared value is kept here, on the AI side.
        self._record = record or (lambda rows: None)
        self.prompt_sha256 = hashlib.sha256(raw).hexdigest()

    def propose(self, columns: Sequence[ColumnContext]) -> list[Proposal]:
        if not columns:
            return []
        # The inventory calls this synchronously, from a batch job: it owns no event loop.
        return asyncio.run(self.propose_async(columns))

    async def propose_async(self, columns: Sequence[ColumnContext]) -> list[Proposal]:
        """The same proposal, for a caller that already runs an event loop."""
        user = json.dumps(
            [
                {
                    "key": column.key,
                    "name": column.name,
                    "type": column.type,
                    "table": column.table,
                    "siblings": list(column.siblings),
                }
                for column in columns
            ],
            ensure_ascii=False,
        )
        answer = await self._gateway.chat_json(SERVICE, self._system, user, SCHEMA)
        proposals: list[Proposal] = []
        recorded: list[dict[str, Any]] = []
        for item in answer.data["items"]:
            category, declared = str(item["category"]), float(item["confidence"])
            calibrated = self._calibrator.calibrate(category, declared)
            proposals.append(
                Proposal(str(item["key"]), category, calibrated, str(item.get("reason", "")))
            )
            recorded.append(
                {
                    "node_key": str(item["key"]),
                    "category": category,
                    "declared": declared,
                    "calibrated": calibrated,
                    "prompt_sha256": self.prompt_sha256,
                }
            )
        if recorded:
            self._record(recorded)
        return proposals
