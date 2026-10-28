from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from backend.app.batch.importers import CompanyInput
from backend.app.domain.dedup import company_identity

BatchStatus = Literal['queued', 'running', 'completed', 'failed']


@dataclass
class BatchResult:
    item_id: str
    company_name: str
    city: str
    row_number: int
    status: BatchStatus
    result: Any | None = None
    error: str | None = None
    retry_after: datetime | None = None


class BatchQueue:
    def __init__(
        self,
        processor: Callable[[CompanyInput], Any],
        *,
        max_queue_size: int = 1000,
        request_interval_seconds: float = 0.3,
        sleep_fn: Callable[[float], None] = time.sleep,
        should_pause: Callable[[], bool] | None = None,
    ) -> None:
        self.processor = processor
        self.max_queue_size = max_queue_size
        self.request_interval_seconds = request_interval_seconds
        self.sleep_fn = sleep_fn
        self.should_pause = should_pause
        self._items: dict[str, CompanyInput] = {}
        self._results: dict[str, BatchResult] = {}
        self._identity_to_item: dict[str, str] = {}

    def enqueue(self, items: Iterable[CompanyInput]) -> list[str]:
        ids: list[str] = []
        for item in items:
            if len(self._items) >= self.max_queue_size:
                raise ValueError('batch queue is full')
            identity = company_identity(item.city, item.company_name)
            if identity in self._identity_to_item:
                continue
            item_id = f'batch-{uuid4().hex}'
            self._items[item_id] = item
            self._identity_to_item[identity] = item_id
            self._results[item_id] = BatchResult(
                item_id=item_id,
                company_name=item.company_name,
                city=item.city,
                row_number=item.row_number,
                status='queued',
            )
            ids.append(item_id)
        return ids

    def run_all(self) -> list[BatchResult]:
        return self._run_ids(
            item_id
            for item_id, result in self._results.items()
            if result.status == 'queued'
        )

    def retry_errors(self) -> list[BatchResult]:
        for result in self._results.values():
            if result.status == 'failed':
                result.status = 'queued'
                result.error = None
        return self._run_ids(
            item_id
            for item_id, result in self._results.items()
            if result.status == 'queued'
        )

    def results(self) -> list[BatchResult]:
        return list(self._results.values())

    def _run_ids(self, item_ids: Iterable[str]) -> list[BatchResult]:
        selected: list[BatchResult] = []
        has_processed = False
        for item_id in item_ids:
            if self.should_pause is not None and self.should_pause():
                break
            result = self._results[item_id]
            item = self._items[item_id]
            if has_processed and self.request_interval_seconds > 0:
                self.sleep_fn(self.request_interval_seconds)
            has_processed = True
            result.status = 'running'
            try:
                result.result = self.processor(item)
                result.status = 'completed'
            except Exception as exc:  # noqa: BLE001 - isolate one company in the batch
                result.status = 'failed'
                result.result = getattr(exc, 'result', None)
                result.error = str(exc)
                result.retry_after = datetime.now(UTC)
            selected.append(replace(result))
        return selected
