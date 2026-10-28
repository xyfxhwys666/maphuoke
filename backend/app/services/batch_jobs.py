from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, RLock
from typing import Any, Literal
from uuid import uuid4

from backend.app.batch.importers import CompanyInput
from backend.app.batch.queue import BatchQueue
from backend.app.domain.dedup import company_identity
from backend.app.services.search_task import CompanySearchService
from pydantic import BaseModel, Field

BatchItemStatus = Literal['queued', 'running', 'completed', 'failed']
BatchJobStatus = Literal['created', 'running', 'paused', 'completed', 'completed_with_errors']


def utc_now() -> datetime:
    return datetime.now(UTC)


class BatchItem(BaseModel):
    item_id: str
    company_name: str
    city: str
    row_number: int
    status: BatchItemStatus = 'queued'
    task_id: str | None = None
    candidate_count: int = 0
    error: str | None = None
    retry_count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class BatchJob(BaseModel):
    id: str
    filename: str
    status: BatchJobStatus = 'created'
    total: int
    items: list[BatchItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BatchItemProcessingError(RuntimeError):
    def __init__(self, message: str, *, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


class BatchJobManager:
    def __init__(
        self,
        service: CompanySearchService,
        *,
        max_items: int = 1000,
        request_interval_seconds: float = 0.3,
        background: bool = True,
        repository: Any | None = None,
    ) -> None:
        self.service = service
        self.max_items = max_items
        self.request_interval_seconds = request_interval_seconds
        self.background = background
        self.repository = repository
        self._jobs: dict[str, BatchJob] = {}
        self._queues: dict[str, BatchQueue] = {}
        self._pause_events: dict[str, Event] = {}
        self._item_task_ids: dict[str, str] = {}
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mapsearch-batch')

    def create_job(self, *, filename: str, items: list[CompanyInput]) -> BatchJob:
        if not items:
            raise ValueError('批量文件没有有效公司行')
        unique_items: list[CompanyInput] = []
        seen: set[str] = set()
        for item in items:
            identity = company_identity(item.city, item.company_name)
            if identity in seen:
                continue
            seen.add(identity)
            unique_items.append(item)
        if len(unique_items) > self.max_items:
            raise ValueError(f'批量文件最多支持 {self.max_items} 家公司')
        job_id = f'batch-job-{uuid4().hex}'
        pause_event = Event()
        queue = BatchQueue(
            self._process_item,
            max_queue_size=self.max_items,
            request_interval_seconds=self.request_interval_seconds,
            should_pause=pause_event.is_set,
        )
        queue_ids = queue.enqueue(unique_items)
        job = BatchJob(
            id=job_id,
            filename=filename,
            total=len(queue_ids),
            items=[
                BatchItem(
                    item_id=item_id,
                    company_name=item.company_name,
                    city=item.city,
                    row_number=item.row_number,
                )
                for item_id, item in zip(queue_ids, unique_items, strict=True)
            ],
        )
        with self._lock:
            self._jobs[job.id] = job
            self._queues[job.id] = queue
            self._pause_events[job.id] = pause_event
            self._persist_job(job)
        return self._copy_job(job)

    def get_job(self, job_id: str) -> BatchJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None and self.repository is not None:
                payload = self.repository.get_batch(job_id)
                if payload is not None:
                    job = BatchJob.model_validate(payload)
                    self._jobs[job.id] = job
                    self._restore_runtime(job)
            if job is None:
                raise KeyError(f'batch job not found: {job_id}') from None
            return self._copy_job(job)

    def start(self, job_id: str) -> BatchJob:
        if job_id not in self._jobs:
            self.get_job(job_id)
        with self._lock:
            job = self._job(job_id)
            if job.status != 'created':
                return self._copy_job(job)
            job.status = 'running'
            job.updated_at = utc_now()
            self._persist_job(job)
        if self.background:
            self._executor.submit(self._run, job_id, False)
        else:
            self._run(job_id, False)
        return self.get_job(job_id)

    def retry_errors(self, job_id: str) -> BatchJob:
        if job_id not in self._jobs:
            self.get_job(job_id)
        with self._lock:
            job = self._job(job_id)
            if job.status == 'running':
                return self._copy_job(job)
            if not any(item.status == 'failed' for item in job.items):
                return self._copy_job(job)
            job.status = 'running'
            job.updated_at = utc_now()
            self._persist_job(job)
        if self.background:
            self._executor.submit(self._run, job_id, True)
        else:
            self._run(job_id, True)
        return self.get_job(job_id)

    def pause(self, job_id: str) -> BatchJob:
        if job_id not in self._jobs:
            self.get_job(job_id)
        with self._lock:
            job = self._job(job_id)
            if job.status == 'running':
                self._pause_events[job_id].set()
                job.status = 'paused'
                job.updated_at = utc_now()
                self._persist_job(job)
            return self._copy_job(job)

    def resume(self, job_id: str) -> BatchJob:
        if job_id not in self._jobs:
            self.get_job(job_id)
        with self._lock:
            job = self._job(job_id)
            if job.status != 'paused':
                return self._copy_job(job)
            self._pause_events[job_id].clear()
            job.status = 'running'
            job.updated_at = utc_now()
            self._persist_job(job)
        if self.background:
            self._executor.submit(self._run, job_id, False)
        else:
            self._run(job_id, False)
        return self.get_job(job_id)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str, retry_only: bool) -> None:
        with self._lock:
            job = self._job(job_id)
            queue = self._queues[job_id]
        results = queue.retry_errors() if retry_only else queue.run_all()
        with self._lock:
            for result in results:
                item = next(
                    item
                    for item in job.items
                    if company_identity(item.city, item.company_name)
                    == company_identity(result.city, result.company_name)
                )
                item.status = 'completed' if result.status == 'completed' else 'failed'
                item.error = result.error
                if retry_only:
                    item.retry_count += 1
                item.updated_at = utc_now()
                execution = result.result if isinstance(result.result, dict) else {}
                item.task_id = execution.get('task_id') or item.task_id
                item.candidate_count = int(execution.get('candidate_count', item.candidate_count))
                item.updated_at = utc_now()
                self._persist_job(job)
            if job.status != 'paused':
                job.status = 'completed_with_errors' if any(item.status == 'failed' for item in job.items) else 'completed'
                job.updated_at = utc_now()
                self._persist_job(job)

    def _process_item(self, item: CompanyInput) -> dict[str, Any]:
        identity = company_identity(item.city, item.company_name)
        task_id = self._item_task_ids.get(identity)
        if task_id:
            task = self.service.get_task(task_id)
            discovered = self.service.retry_errors(task.id)
        else:
            task = self.service.create_task(company_name=item.company_name, city=item.city)
            self._item_task_ids[identity] = task.id
            discovered = self.service.discover(task.id)
        result = {
            'task_id': task.id,
            'candidate_count': len(discovered.candidates),
            'task_status': discovered.status,
        }
        if discovered.status != 'candidates_ready':
            detail = '; '.join(discovered.errors) or f'子任务状态为 {discovered.status}'
            raise BatchItemProcessingError(f'{discovered.status}: {detail}', result=result)
        return result

    def _job(self, job_id: str) -> BatchJob:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise KeyError(f'batch job not found: {job_id}') from None

    @staticmethod
    def _copy_job(job: BatchJob) -> BatchJob:
        return job.model_copy(deep=True)

    def _restore_runtime(self, job: BatchJob) -> None:
        pause_event = Event()
        if job.status == 'paused':
            pause_event.set()
        queue = BatchQueue(
            self._process_item,
            max_queue_size=self.max_items,
            request_interval_seconds=self.request_interval_seconds,
            should_pause=pause_event.is_set,
        )
        pending_items = [
            CompanyInput(
                company_name=item.company_name,
                city=item.city,
                row_number=item.row_number,
            )
            for item in job.items
            if item.status in {'queued', 'running', 'failed'}
        ]
        queue.enqueue(pending_items)
        self._queues[job.id] = queue
        self._pause_events[job.id] = pause_event
        for item in job.items:
            if item.task_id:
                self._item_task_ids[company_identity(item.city, item.company_name)] = item.task_id

    def _persist_job(self, job: BatchJob) -> None:
        if self.repository is not None:
            self.repository.save_batch(job)
