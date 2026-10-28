from __future__ import annotations

from typing import Any

from backend.app.domain.evidence import evaluate_delivery_gate
from backend.app.domain.models import DeliveryPolicy, DeliveryResult, LeadRecord
from backend.app.domain.task_state import SearchTask
from backend.app.providers.protocols import ErpAdapter


class DeliveryService:
    def __init__(self, adapter: ErpAdapter) -> None:
        self.adapter = adapter
        self._delivered: set[str] = set()
        self._failed: dict[str, dict[str, Any]] = {}

    def deliver(
        self,
        task: SearchTask,
        lead: LeadRecord,
        *,
        policy: DeliveryPolicy | None = None,
    ) -> DeliveryResult:
        decision = evaluate_delivery_gate(policy or DeliveryPolicy(), lead)
        if decision.status == 'display_only':
            return DeliveryResult(status='display_only', reasons=decision.reasons)
        payload = self.adapter.build_payload(task, lead)
        fingerprint = self.adapter.fingerprint(payload)
        if fingerprint in self._delivered:
            return DeliveryResult(status='duplicate', reasons=['duplicate_payload'], payload=payload)
        result = self.adapter.deliver(payload)
        if result.status == 'delivered':
            self._delivered.add(fingerprint)
            self._failed.pop(fingerprint, None)
        else:
            self._failed[fingerprint] = {'task': task, 'lead': lead, 'payload': payload}
        return result

    def retry_failed(self, fingerprint: str) -> DeliveryResult:
        pending = self._failed.get(fingerprint)
        if pending is None:
            return DeliveryResult(status='failed', error='delivery fingerprint not found')
        result = self.adapter.deliver(pending['payload'])
        if result.status == 'delivered':
            self._delivered.add(fingerprint)
            self._failed.pop(fingerprint, None)
        return result
