from datetime import UTC
from hashlib import sha256
from typing import Any

from backend.app.collection.models import CollectionTask
from backend.app.domain.models import DeliveryLedgerEntry, DeliveryResult
from backend.app.domain.task_state import SearchTask
from backend.app.storage.models import (
    BatchJobRow,
    CandidateRow,
    CheckpointRow,
    CollectionCandidateRow,
    CollectionCheckpointRow,
    CollectionResultConsumptionRow,
    CollectionTaskRow,
    CollectionWorkUnitRow,
    DeliveryLedgerRow,
    LeadRow,
    TaskRow,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


_GLOBAL_RESULT_CONSUMPTION_SCOPE = '__global__'


class TaskRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def save(self, task: SearchTask) -> None:
        payload = task.model_dump(mode='json')
        with self.session_factory() as session:
            row = session.get(TaskRow, task.id)
            if row is None:
                session.add(TaskRow(
                    id=task.id,
                    company_name=task.company_name,
                    city=task.city,
                    status=task.status,
                    payload=payload,
                ))
            else:
                row.company_name = task.company_name
                row.city = task.city
                row.status = task.status
                row.payload = payload

            session.execute(delete(CandidateRow).where(CandidateRow.task_id == task.id))
            session.execute(delete(LeadRow).where(LeadRow.task_id == task.id))
            session.execute(delete(CheckpointRow).where(CheckpointRow.task_id == task.id))
            session.add_all([
                CandidateRow(
                    id=self._storage_id(task.id, candidate.candidate_id),
                    task_id=task.id,
                    payload=candidate.model_dump(mode='json'),
                )
                for candidate in task.candidates
            ])
            session.add_all([
                LeadRow(
                    id=self._storage_id(task.id, lead.id),
                    task_id=task.id,
                    candidate_id=lead.id.removeprefix('lead-'),
                    payload=lead.model_dump(mode='json'),
                )
                for lead in task.leads
            ])
            session.add(CheckpointRow(task_id=task.id, payload=task.checkpoint.model_dump(mode='json')))
            session.commit()

    def get(self, task_id: str) -> SearchTask | None:
        with self.session_factory() as session:
            row = session.scalar(select(TaskRow).where(TaskRow.id == task_id))
            return SearchTask.model_validate(row.payload) if row else None

    def get_delivery(self, fingerprint: str) -> DeliveryLedgerEntry | None:
        with self.session_factory() as session:
            row = session.get(DeliveryLedgerRow, fingerprint)
            if row is None:
                return None
            return DeliveryLedgerEntry(
                fingerprint=row.fingerprint,
                task_id=row.task_id,
                lead_id=row.lead_id,
                status=row.status,
                operation_id=row.operation_id,
                error=row.error,
                attempts=row.attempts,
            )

    def record_delivery(
        self,
        *,
        task_id: str,
        lead_id: str,
        fingerprint: str,
        payload: dict[str, Any],
        result: DeliveryResult,
    ) -> DeliveryLedgerEntry:
        status = 'delivered' if result.status == 'delivered' else 'failed'
        with self.session_factory() as session:
            row = session.get(DeliveryLedgerRow, fingerprint)
            if row is None:
                row = DeliveryLedgerRow(
                    id=fingerprint,
                    task_id=task_id,
                    lead_id=lead_id,
                    fingerprint=fingerprint,
                    status=status,
                    operation_id=result.operation_id,
                    payload=payload,
                    error=result.error,
                    attempts=0,
                )
                session.add(row)
            else:
                row.task_id = task_id
                row.lead_id = lead_id
                row.status = status
                row.operation_id = result.operation_id or row.operation_id
                row.payload = payload
                row.error = result.error
            row.attempts += 1
            session.commit()
            return DeliveryLedgerEntry(
                fingerprint=row.fingerprint,
                task_id=row.task_id,
                lead_id=row.lead_id,
                status=row.status,
                operation_id=row.operation_id,
                error=row.error,
                attempts=row.attempts,
            )

    def save_batch(self, batch: Any) -> None:
        payload = batch.model_dump(mode='json')
        with self.session_factory() as session:
            row = session.get(BatchJobRow, batch.id)
            if row is None:
                session.add(BatchJobRow(
                    id=batch.id,
                    filename=batch.filename,
                    status=batch.status,
                    payload=payload,
                ))
            else:
                row.filename = batch.filename
                row.status = batch.status
                row.payload = payload
            session.commit()

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            row = session.get(BatchJobRow, batch_id)
            return dict(row.payload) if row is not None else None

    @staticmethod
    def _storage_id(task_id: str, entity_id: str) -> str:
        return sha256(f'{task_id}:{entity_id}'.encode()).hexdigest()


class CollectionRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def save(self, task: CollectionTask) -> None:
        payload = task.model_dump(mode='json')
        with self.session_factory() as session:
            row = session.get(CollectionTaskRow, task.id)
            if row is None:
                session.add(
                    CollectionTaskRow(
                        id=task.id,
                        name=task.name,
                        request_text=task.request_text,
                        status=task.status,
                        payload=payload,
                    )
                )
            else:
                row.name = task.name
                row.request_text = task.request_text
                row.status = task.status
                row.payload = payload

            session.execute(delete(CollectionWorkUnitRow).where(CollectionWorkUnitRow.task_id == task.id))
            session.execute(delete(CollectionCandidateRow).where(CollectionCandidateRow.task_id == task.id))
            session.execute(delete(CollectionCheckpointRow).where(CollectionCheckpointRow.task_id == task.id))
            session.add_all(
                [
                    CollectionWorkUnitRow(
                        id=self._storage_id(task.id, unit.id),
                        task_id=task.id,
                        work_unit_id=unit.id,
                        city=unit.city,
                        keyword=unit.keyword,
                        status=unit.status,
                        payload=unit.model_dump(mode='json'),
                    )
                    for unit in task.work_units
                ]
            )
            session.add_all(
                [
                    CollectionCandidateRow(
                        id=self._storage_id(task.id, candidate.candidate_id),
                        task_id=task.id,
                        candidate_id=candidate.candidate_id,
                        payload=candidate.model_dump(mode='json'),
                    )
                    for candidate in task.candidates
                ]
            )
            session.add(
                CollectionCheckpointRow(
                    task_id=task.id,
                    payload=task.checkpoint.model_dump(mode='json'),
                )
            )
            session.commit()

    def get(self, task_id: str) -> CollectionTask | None:
        with self.session_factory() as session:
            row = session.scalar(select(CollectionTaskRow).where(CollectionTaskRow.id == task_id))
            if row is None:
                return None
            return self._with_delivery_times(
                self._task_from_row(row),
                session,
            )

    def list(self, *, account_scope: str | None = None) -> list[CollectionTask]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(CollectionTaskRow).order_by(CollectionTaskRow.created_at.desc())
            )
            tasks = [
                self._with_delivery_times(self._task_from_row(row), session)
                for row in rows
            ]
            if account_scope is None:
                return tasks
            return [task for task in tasks if task.account_scope == account_scope]

    def is_result_consumed(self, *, account_scope: str, result_fingerprint: str) -> bool:
        with self.session_factory() as session:
            row = session.get(
                CollectionResultConsumptionRow,
                self._consumption_id(account_scope, result_fingerprint),
            )
            return row is not None

    def record_result_consumption(
        self,
        *,
        account_scope: str,
        result_fingerprint: str,
        source_task_id: str,
    ) -> None:
        row_id = self._consumption_id(account_scope, result_fingerprint)
        with self.session_factory() as session:
            if session.get(CollectionResultConsumptionRow, row_id) is None:
                session.add(CollectionResultConsumptionRow(
                    id=row_id,
                    account_scope=account_scope,
                    result_fingerprint=result_fingerprint,
                    source_task_id=source_task_id,
                ))
                session.commit()

    def claim_result_consumption(
        self,
        *,
        result_fingerprint: str,
        source_task_id: str,
    ) -> bool:
        """Atomically reserve a public result so it is only issued once."""
        with self.session_factory() as session:
            existing = session.scalar(
                select(CollectionResultConsumptionRow).where(
                    CollectionResultConsumptionRow.result_fingerprint == result_fingerprint,
                )
            )
            if existing is not None:
                return False
            session.add(CollectionResultConsumptionRow(
                id=self._consumption_id(
                    _GLOBAL_RESULT_CONSUMPTION_SCOPE,
                    result_fingerprint,
                ),
                account_scope=_GLOBAL_RESULT_CONSUMPTION_SCOPE,
                result_fingerprint=result_fingerprint,
                source_task_id=source_task_id,
            ))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True

    @staticmethod
    def _task_from_row(row: CollectionTaskRow) -> CollectionTask:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return CollectionTask.model_validate(row.payload).model_copy(
            update={'created_at': created_at},
        )

    @staticmethod
    def _with_delivery_times(task: CollectionTask, session: Session) -> CollectionTask:
        rows = session.scalars(
            select(DeliveryLedgerRow).where(
                DeliveryLedgerRow.task_id == task.id,
                DeliveryLedgerRow.status == 'delivered',
            )
        )
        delivery_times = {
            row.lead_id: (
                row.created_at
                if row.created_at.tzinfo is not None
                else row.created_at.replace(tzinfo=UTC)
            )
            for row in rows
        }
        for lead in task.results:
            if lead.delivery_status == 'delivered' and lead.delivery_at is None:
                lead.delivery_at = delivery_times.get(lead.id)
        return task

    def get_delivery(self, fingerprint: str) -> DeliveryLedgerEntry | None:
        with self.session_factory() as session:
            row = session.get(DeliveryLedgerRow, fingerprint)
            if row is None:
                return None
            return DeliveryLedgerEntry(
                fingerprint=row.fingerprint,
                task_id=row.task_id,
                lead_id=row.lead_id,
                status=row.status,
                operation_id=row.operation_id,
                error=row.error,
                attempts=row.attempts,
            )

    def record_delivery(
        self,
        *,
        task_id: str,
        lead_id: str,
        fingerprint: str,
        payload: dict[str, Any],
        result: DeliveryResult,
    ) -> DeliveryLedgerEntry:
        delivery_status = 'delivered' if result.status == 'delivered' else 'failed'
        with self.session_factory() as session:
            row = session.get(DeliveryLedgerRow, fingerprint)
            if row is None:
                row = DeliveryLedgerRow(
                    id=fingerprint,
                    task_id=task_id,
                    lead_id=lead_id,
                    fingerprint=fingerprint,
                    status=delivery_status,
                    operation_id=result.operation_id,
                    payload=payload,
                    error=result.error,
                    attempts=0,
                )
                session.add(row)
            else:
                row.task_id = task_id
                row.lead_id = lead_id
                row.status = delivery_status
                row.operation_id = result.operation_id or row.operation_id
                row.payload = payload
                row.error = result.error
            row.attempts += 1
            session.commit()
            return DeliveryLedgerEntry(
                fingerprint=row.fingerprint,
                task_id=row.task_id,
                lead_id=row.lead_id,
                status=row.status,
                operation_id=row.operation_id,
                error=row.error,
                attempts=row.attempts,
            )

    @staticmethod
    def _storage_id(task_id: str, entity_id: str) -> str:
        return sha256(f'{task_id}:{entity_id}'.encode()).hexdigest()

    @staticmethod
    def _consumption_id(account_scope: str, result_fingerprint: str) -> str:
        return sha256(f'{account_scope}:{result_fingerprint}'.encode()).hexdigest()
